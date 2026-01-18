"""
NCAA Men's Basketball (NCAAB) Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under
"""

import logging
import os
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import math
from pathlib import Path
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import shap

# Monkeypatch for Python 3.13 compatibility
import collections
import collections.abc
for name in ['MutableSet', 'MutableMapping', 'Mapping', 'Iterable', 'Callable', 'Sequence']:
    if not hasattr(collections, name):
        setattr(collections, name, getattr(collections.abc, name))

logger = logging.getLogger(__name__)

# Map sportsbook names to Odds API format
SPORTSBOOK_MAP = {
    "fanduel": "fanduel",
    "draftkings": "draftkings",
    "betmgm": "betmgm",
    "pointsbet": "pointsbetus",
    "caesars": "williamhill_us",
}


def _decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


class NCAABPredictor:
    """
    Advanced NCAAB game predictor using team statistics.
    Supports Legacy v1 XGBoost and New v2 Dual Models (ML + O/U).
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
        self.stats_df = None
        self.schedule_df = None
        
        # v1 Model
        self.model = None
        self.explainer = None
        self.model_path = Path(__file__).resolve().parent.parent / "models" / "ncaab_xgb_v1.joblib"
        
        # v2 Models (Side-by-side)
        self.ml_model_v2 = None
        self.ou_model_v2 = None
        self.v2_features = None
        self.model_v2_dir = Path(__file__).resolve().parent.parent / "models"
        
    def _load_data(self):
        """Load historical stats from Parquet files if available."""
        try:
            import pandas as pd
            SCRIPT_DIR = Path(__file__).parent.absolute()
            BACKEND_ROOT = SCRIPT_DIR.parent
            
            possible_paths = [
                BACKEND_ROOT / "data" / "ncaab",
                Path.cwd() / "data" / "ncaab",
                Path.cwd() / "backend" / "data" / "ncaab",
                Path("/app/data/ncaab")
            ]
            
            DATA_DIR = None
            for p in possible_paths:
                if p.exists():
                    DATA_DIR = p
                    break
            
            if not DATA_DIR:
                logger.error("NCAAB data directory NOT found.")
                return

            box_path = DATA_DIR / "ncaab_team_box_history.parquet"
            if box_path.exists():
                self.stats_df = pd.read_parquet(box_path)
                # Ensure date is datetime
                self.stats_df['game_date'] = pd.to_datetime(self.stats_df['game_date'])
                logger.info(f"Loaded {len(self.stats_df)} NCAAB stats rows")
            else:
                logger.warning(f"NCAAB stats file not found at {box_path}")
                
        except Exception as e:
            logger.error(f"Error loading NCAAB data: {e}")

    def _load_models_v2(self):
        """Lazy load v2 models and features list"""
        if self.ml_model_v2 is None:
            try:
                ml_path = self.model_v2_dir / "ncaab_ml_v2.joblib"
                ou_path = self.model_v2_dir / "ncaab_ou_v2.joblib"
                feat_path = self.model_v2_dir / "ncaab_features_v2.joblib"
                
                if ml_path.exists() and ou_path.exists() and feat_path.exists():
                    self.ml_model_v2 = joblib.load(ml_path)
                    self.ou_model_v2 = joblib.load(ou_path)
                    self.v2_features = joblib.load(feat_path)
                    logger.info("Successfully loaded NCAAB v2 models and features")
                else:
                    logger.warning("NCAAB v2 models or features list missing")
            except Exception as e:
                logger.error(f"Failed to load NCAAB v2 models: {e}")

    def _prepare_features_v2(self, home_team: str, away_team: str) -> Optional[pd.DataFrame]:
        """Prepare advanced v2 features for inference"""
        if self.stats_df is None:
            self._load_data()
        if self.stats_df is None or self.v2_features is None:
            return None

        def normalize(n):
            return n.lower().replace(" state", " st").replace(" university", "").replace(";", "").strip()
        
        h_norm = normalize(home_team)
        a_norm = normalize(away_team)

        def get_team_v2_stats(team_name_norm):
            team_mask = self.stats_df['team_display_name'].apply(normalize) == team_name_norm
            team_df = self.stats_df[team_mask]
            
            if team_df.empty:
                return None
            
            max_season = team_df['season'].max()
            team_df = team_df[team_df['season'] == max_season].sort_values('game_date')
            
            if team_df.empty: return None

            core_stats = [
                'team_score', 'opponent_team_score', 'field_goal_pct', 'three_point_field_goal_pct',
                'free_throw_pct', 'total_rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'fouls'
            ]
            
            stats_dict = {}
            for stat in core_stats:
                if stat not in team_df.columns: continue
                
                # Windows
                for w in [5, 10, 20]:
                    recent = team_df[stat].tail(w)
                    stats_dict[f'{stat}_mean_{w}'] = recent.mean()
                    stats_dict[f'{stat}_std_{w}'] = recent.std() if len(recent) > 1 else 0
                    stats_dict[f'{stat}_median_{w}'] = recent.median()
                
                # Season Avg
                stats_dict[f'{stat}_season_avg'] = team_df[stat].mean()
            
            return stats_dict

        h_stats = get_team_v2_stats(h_norm)
        a_stats = get_team_v2_stats(a_norm)
        
        if not h_stats or not a_stats:
            return None

        # Build Matchup Row
        feat_dict = {}
        for k, v in h_stats.items():
            feat_dict[f'{k}_home'] = v
        for k, v in a_stats.items():
            feat_dict[f'{k}_away'] = v
            
        core_stats = [
            'team_score', 'opponent_team_score', 'field_goal_pct', 'three_point_field_goal_pct',
            'free_throw_pct', 'total_rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'fouls'
        ]
        for stat in core_stats:
            if f'{stat}_season_avg' in h_stats and f'{stat}_season_avg' in a_stats:
                feat_dict[f'{stat}_diff_season'] = h_stats[f'{stat}_season_avg'] - a_stats[f'{stat}_season_avg']
            if f'{stat}_mean_10' in h_stats and f'{stat}_mean_10' in a_stats:
                feat_dict[f'{stat}_diff_10'] = h_stats[f'{stat}_mean_10'] - a_stats[f'{stat}_mean_10']

        final_row = {}
        for f in self.v2_features:
            final_row[f] = feat_dict.get(f, 0)
            
        return pd.DataFrame([final_row])

    def predict_v2(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Run v2 inference (Dual Models)"""
        self._load_models_v2()
        if self.ml_model_v2 is None:
            return {}
            
        try:
            X = self._prepare_features_v2(home_team, away_team)
            if X is None:
                return {}
            
            ml_prob = self.ml_model_v2.predict_proba(X)[0][1]
            predicted_total = self.ou_model_v2.predict(X)[0]
            
            return {
                'v2_win_prob': float(ml_prob),
                'v2_total': float(predicted_total),
                'v2_available': True
            }
        except Exception as e:
            logger.error(f"v2 inference failed: {e}")
            return {}

    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """Get team statistics (Legacy PPG-based)"""
        if team_name in self._team_stats_cache:
            return self._team_stats_cache[team_name]
            
        if self.stats_df is None:
            self._load_data()
            
        stats = {
            'ppg': 73.0, 'oppg': 73.0, 
            'pace': 70.0, 'off_efficiency': 1.015, 'def_efficiency': 1.015,
            'win_pct': 0.5,
            'is_default': True
        }

        if self.stats_df is not None and not self.stats_df.empty:
            try:
                def normalize(n):
                    return n.lower().replace(" state", " st").replace(" university", "").replace(";", "").strip()
                
                name_norm = normalize(team_name)
                team_df = self.stats_df[self.stats_df['team_display_name'].str.lower() == team_name.lower()]
                
                if team_df.empty:
                    team_df = self.stats_df[self.stats_df['team_display_name'].apply(normalize) == name_norm]
                
                if team_df.empty:
                    team_df = self.stats_df[self.stats_df['team_display_name'].str.lower().str.contains(team_name.lower(), regex=False)]
                
                if not team_df.empty:
                    max_season = team_df['season'].max()
                    team_df = team_df[team_df['season'] == max_season]
                    
                    if len(team_df) >= 1:
                        games = len(team_df)
                        ppg = team_df['team_score'].mean()
                        oppg = team_df['opponent_team_score'].mean()
                        
                        if 'field_goals_attempted' in team_df.columns:
                            fga = team_df['field_goals_attempted'].mean()
                            fta = team_df['free_throws_attempted'].mean()
                            to = team_df['turnovers'].mean()
                            orb = team_df['offensive_rebounds'].mean()
                            possessions = fga + (0.44 * fta) + to - orb
                            pace = max(60, min(85, possessions))
                            off_eff = ppg / possessions if possessions > 0 else 1.015
                            def_eff = oppg / possessions if possessions > 0 else 1.015
                        else:
                            pace = 70.0; off_eff = ppg / 70.0; def_eff = oppg / 70.0
                            
                        wins = team_df[team_df['team_score'] > team_df['opponent_team_score']].shape[0]
                        win_pct = wins / games
                        
                        stats = {
                            'ppg': float(ppg), 'oppg': float(oppg), 'pace': float(pace),
                            'off_efficiency': float(off_eff), 'def_efficiency': float(def_eff),
                            'win_pct': float(win_pct), 'data_games': games,
                            'season': int(max_season), 'is_default': False
                        }
                        self._team_stats_cache[team_name] = stats
                        return stats
            except Exception as e:
                logger.warning(f"Error calculating stats for {team_name}: {e}")
        
        return stats

    def _load_model(self):
        """Lazy load v1 Legacy Model"""
        if self.model is None and self.model_path.exists():
            try:
                self.model = joblib.load(self.model_path)
                self.explainer = shap.TreeExplainer(self.model)
            except Exception as e:
                logger.error(f"Failed to load XGBoost v1: {e}")

    def predict_xgb_inference(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Run XGBoost v1 (Legacy) inference"""
        self._load_model()
        if self.model is None: return {}
        try:
            # Re-calculating rolling stats for v1 features
            def get_rolling(team):
                team_df = self.stats_df[self.stats_df['team_display_name'] == team]
                if team_df.empty: return None
                team_df = team_df.sort_values('game_date')
                features = ['team_score', 'opponent_team_score', 'field_goals_made', 'field_goals_attempted', 
                    'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made', 
                    'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 
                    'turnovers', 'steals', 'blocks', 'personal_fouls']
                cols_needed = [f for f in features if f in team_df.columns]
                roll_stats = {}
                for col in cols_needed:
                    roll_stats[f'{col}_roll5'] = team_df[col].tail(5).mean()
                    roll_stats[f'{col}_roll10'] = team_df[col].tail(10).mean()
                return roll_stats

            h_feats = get_rolling(home_team)
            a_feats = get_rolling(away_team)
            if not h_feats or not a_feats: return {}
            
            feat_dict = {}
            for k, v in h_feats.items(): feat_dict[f'home_{k}'] = v
            for k, v in a_feats.items(): feat_dict[f'away_{k}'] = v
            X = pd.DataFrame([feat_dict])
            
            prob = self.model.predict_proba(X)[0][1]
            return {
                'xgb_win_prob': float(prob),
                'xgb_pick': home_team if prob > 0.5 else away_team,
                'xgb_available': True
            }
        except Exception as e:
            logger.warning(f"XGBoost v1 inference failed: {e}")
            return {}

    def predict_game(self, home_team: str, away_team: str, 
                     spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """Predict game outcome combining Simple, v1, and v2 models."""
        home_stats = self.get_team_stats(home_team)
        away_stats = self.get_team_stats(away_team)
        
        # Simple/Heuristic Baseline
        home_advantage = 3.5
        avg_pace = (home_stats['pace'] + away_stats['pace']) / 2
        league_ppp = 1.03
        home_expected = avg_pace * (home_stats['off_efficiency'] * away_stats['def_efficiency']) / league_ppp + (home_advantage / 2)
        away_expected = avg_pace * (away_stats['off_efficiency'] * home_stats['def_efficiency']) / league_ppp - (home_advantage / 2)
        
        predicted_margin = home_expected - away_expected
        predicted_total = home_expected + away_expected
        home_win_prob = 1 / (1 + math.exp(-predicted_margin * 0.11))

        result = {
            'home_team': home_team, 'away_team': away_team,
            'predicted_winner': home_team if predicted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 3),
            'away_win_probability': round(1 - home_win_prob, 3),
            'predicted_margin': round(predicted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'confidence': round(0.5 + abs(predicted_margin) * 0.015, 2)
        }

        # XGBoost v1
        v1_res = self.predict_xgb_inference(home_team, away_team)
        if v1_res:
            result['xgb_win_prob'] = round(v1_res['xgb_win_prob'], 3)
            result['xgb_winner'] = v1_res['xgb_pick']
            result['xgb_available'] = True
        
        # XGBoost v2 (New)
        v2_res = self.predict_v2(home_team, away_team)
        if v2_res:
            result['v2_win_prob'] = round(v2_res['v2_win_prob'], 3)
            result['v2_total'] = round(v2_res['v2_total'], 1)
            result['v2_winner'] = home_team if v2_res['v2_win_prob'] > 0.5 else away_team
            result['v2_available'] = True
        else:
            result['v2_available'] = False

        # Betting Edge (using v2 if available, else simple)
        if spread is not None:
            base_margin = result['v2_win_prob'] * 10 - 5 if result.get('v2_available') else predicted_margin 
            # (Simple win probability to margin conversion for value pick)
            line_margin = -spread
            result['spread_pick'] = 'HOME' if (result.get('v2_win_prob', home_win_prob) > 0.5) else 'AWAY'
            
        if over_under is not None:
            base_total = result.get('v2_total', predicted_total)
            result['ou_pick'] = 'OVER' if base_total > over_under else 'UNDER'

        return result


async def get_todays_ncaab_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """Fetch today's NCAAB odds via sbrscrape or Odds API."""
    today = date.today()
    try:
        from sbrscrape import Scoreboard
        sb = Scoreboard(sport="NCAAB", date=today)
        if hasattr(sb, "games") and sb.games:
            games = []
            for game in sb.games:
                gd = {"home_team": game.get('home_team'), "away_team": game.get('away_team'), "status": 'scheduled'}
                if 'total' in game and sportsbook in game.get('total', {}): gd['over_under'] = game['total'][sportsbook]
                if 'away_spread' in game and sportsbook in game.get('away_spread', {}): gd['spread'] = game['away_spread'][sportsbook]
                if 'home_ml' in game and sportsbook in game.get('home_ml', {}): gd['home_moneyline'] = game['home_ml'][sportsbook]
                if 'away_ml' in game and sportsbook in game.get('away_ml', {}): gd['away_moneyline'] = game['away_ml'][sportsbook]
                games.append(gd)
            return {"date": str(today), "games": games, "count": len(games), "source": "sbrscrape"}
    except: pass
    return {"date": str(today), "games": [], "message": "No games found"}


async def analyze_ncaab_matchup(home_team: str, away_team: str, 
                                 spread: float = None, over_under: float = None,
                                 home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive NCAAB matchup analysis."""
    predictor = NCAABPredictor()
    prediction = predictor.predict_game(home_team, away_team, spread, over_under)
    
    if home_ml and away_ml:
        prediction['home_moneyline'] = home_ml
        prediction['away_moneyline'] = away_ml
    
    prediction['model'] = 'v2' if prediction.get('v2_available') else 'simple'
    return prediction
