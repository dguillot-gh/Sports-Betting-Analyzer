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
    Simple NCAAB game predictor using team statistics.
    Uses points per game, home-field advantage, and simple heuristics.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
        self.stats_df = None
        self.schedule_df = None
        self.model = None
        self.explainer = None
        self.model_path = Path(__file__).resolve().parent.parent / "models" / "ncaab_xgb_v1.joblib"
        # self._load_data()  <-- Refactored to lazy load in get_team_stats
        
    def _load_data(self):
        """Load historical stats from Parquet files if available."""
        try:
            import pandas as pd
            # Use absolute path detection
            SCRIPT_DIR = Path(__file__).parent.absolute()
            BACKEND_ROOT = SCRIPT_DIR.parent
            
            # Try multiple possible locations for data
            possible_paths = [
                BACKEND_ROOT / "data" / "ncaab",      # Standard Docker: /app/data/ncaab
                Path.cwd() / "data" / "ncaab",        # Alternate Docker
                Path.cwd() / "backend" / "data" / "ncaab", # Local Dev
                Path("/app/data/ncaab")               # Explicit Docker
            ]
            
            DATA_DIR = None
            for p in possible_paths:
                if p.exists():
                    DATA_DIR = p
                    break
            
            if not DATA_DIR:
                # Advanced Debugging
                logger.error(f"NCAAB data directory NOT found. Searched: {[str(p) for p in possible_paths]}")
                # Log what IS there
                try:
                    app_data = Path("/app/data")
                    if app_data.exists():
                        logger.info(f"Contents of /app/data: {os.listdir('/app/data')}")
                    
                    backend_ncaab = Path("/app/backend/data/ncaab")
                    if backend_ncaab.exists():
                        logger.info(f"Contents of /app/backend/data/ncaab: {os.listdir('/app/backend/data/ncaab')}")
                    else:
                        logger.warning(f"/app/backend/data/ncaab does not exist!")
                        
                    if not app_data.exists():
                        logger.warning(f"/app/data does not exist in container! Creating fallback...")
                        app_data.mkdir(parents=True, exist_ok=True)
                except Exception as debug_ex:
                    logger.error(f"Failed to list /app/data: {debug_ex}")
                
                # Fallback: create the directory to avoid further "not found" errors, 
                # though it will be empty until data is imported or mounted.
                DATA_DIR = Path("/app/data/ncaab")
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                return

            box_path = DATA_DIR / "ncaab_team_box_history.parquet"
            if box_path.exists():
                self.stats_df = pd.read_parquet(box_path)
                logger.info(f"Loaded {len(self.stats_df)} NCAAB stats rows from {box_path}")
            else:
                logger.warning(f"NCAAB stats file not found at {box_path}")
                # List files in DATA_DIR for debugging
                try:
                    logger.info(f"Contents of {DATA_DIR}: {os.listdir(DATA_DIR)}")
                except: pass
                
        except Exception as e:
            logger.error(f"Error loading NCAAB data: {e}")

    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Get team statistics from loaded data or fall back to defaults.
        """
        if team_name in self._team_stats_cache:
            return self._team_stats_cache[team_name]
            
        # Lazy load data on first request
        if self.stats_df is None:
            self._load_data()
            
        # Default stats - using 73.0 to match dataset mean (73.0 * 2 = 146.0)
        stats = {
            'ppg': 73.0, 'oppg': 73.0, 
            'pace': 70.0, 'off_efficiency': 1.015, 'def_efficiency': 1.015,
            'win_pct': 0.5,
            'is_default': True
        }

        if self.stats_df is not None and not self.stats_df.empty:
            try:
                # Normalize names for matching
                def normalize(n):
                    return n.lower().replace(" state", " st").replace(" university", "").replace(";", "").strip()
                
                name_norm = normalize(team_name)
                
                # 1. Try exact match on display name
                team_df = self.stats_df[self.stats_df['team_display_name'].str.lower() == team_name.lower()]
                
                # 2. Try match on normalized display name
                if team_df.empty:
                    team_df = self.stats_df[self.stats_df['team_display_name'].apply(normalize) == name_norm]
                
                # 3. Try "contains" match
                if team_df.empty:
                    team_df = self.stats_df[self.stats_df['team_display_name'].str.lower().str.contains(team_name.lower(), regex=False)]
                
                # 4. Try normalized "contains"
                if team_df.empty:
                     # Use team_name parts (e.g. "Duke" from "Duke Blue Devils")
                     parts = team_name.split()
                     if parts:
                         main_part = parts[0].lower()
                         team_df = self.stats_df[self.stats_df['team_display_name'].str.lower().str.contains(main_part, regex=False)]

                if not team_df.empty:
                    # Use only the most recent season available in data
                    max_season = team_df['season'].max()
                    team_df = team_df[team_df['season'] == max_season]
                    
                    if len(team_df) >= 1: # Even 1 game is better than default
                        games = len(team_df)
                        ppg = team_df['team_score'].mean()
                        oppg = team_df['opponent_team_score'].mean()
                        
                        # Estimate Possessions
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
                            pace = 70.0
                            off_eff = ppg / 70.0
                            def_eff = oppg / 70.0
                            
                        # Win Pct
                        wins = team_df[team_df['team_score'] > team_df['opponent_team_score']].shape[0]
                        win_pct = wins / games
                        
                        stats = {
                            'ppg': float(ppg),
                            'oppg': float(oppg),
                            'pace': float(pace),
                            'off_efficiency': float(off_eff),
                            'def_efficiency': float(def_eff),
                            'win_pct': float(win_pct),
                            'data_games': games,
                            'season': int(max_season),
                            'is_default': False
                        }
                        logger.info(f"Matched {team_name} to {len(team_df)} games from season {max_season}")
                        self._team_stats_cache[team_name] = stats
                        return stats
                    else:
                        logger.warning(f"Found match for {team_name} but no games in recent season")
                else:
                    logger.warning(f"No NCAAB stats found for team: {team_name}")
                        
            except Exception as e:
                logger.warning(f"Error calculating stats for {team_name}: {e}")
        
        # Always return stats dictionary, even if default
        return stats

    def _load_model(self):
        """Lazy load XGBoost model"""
        if self.model is None and self.model_path.exists():
            try:
                self.model = joblib.load(self.model_path)
                logger.info(f"Loaded XGBoost model from {self.model_path}")
                # Initialize SHAP explainer
                # TreeExplainer is fast for XGBoost
                self.explainer = shap.TreeExplainer(self.model)
            except Exception as e:
                logger.error(f"Failed to load XGBoost model: {e}")

    def _prepare_features(self, home_team: str, away_team: str) -> Optional[pd.DataFrame]:
        """Prepare features for XGBoost inference"""
        if self.stats_df is None:
            self._load_data()
            
        if self.stats_df is None or self.stats_df.empty:
            return None
            
        # Helper to get recent rolling stats
        def get_rolling(team):
            # Same normalization as get_team_stats might be needed, but for now exact match
            # In production, this needs robust matching. We'll reuse the logic if possible.
            team_df = self.stats_df[self.stats_df['team_display_name'] == team]
            if team_df.empty: 
                # Try finding by partial match like get_team_stats does
                # (Skipping robust matching for brevity, relying on user input matching data)
                return None
            
            # Sort by date
            team_df = team_df.sort_values('game_date')
            last_row = team_df.iloc[-1]
            
            # We need rolling stats. 
            # Ideally we recalculate rolling on the fly or use the pre-calculated ones if we had a feature store.
            # Here we will approximate by taking the team's average over the season if rolling isn't efficient 
            # Or better: Calculate rolling on the full DF for this team then take last.
            
            features = ['team_score', 'opponent_team_score', 'field_goals_made', 'field_goals_attempted', 
                'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made', 
                'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 
                'turnovers', 'steals', 'blocks', 'personal_fouls']
                
            cols_needed = [f for f in features if f in team_df.columns]
            
            roll_stats = {}
            for col in cols_needed:
                # Calculate simple mean of last 5 and 10 games
                roll_stats[f'{col}_roll5'] = team_df[col].tail(5).mean()
                roll_stats[f'{col}_roll10'] = team_df[col].tail(10).mean()
                
            return roll_stats

        home_feats = get_rolling(home_team)
        away_feats = get_rolling(away_team)
        
        if not home_feats or not away_feats:
            return None
            
        # Combine
        feat_dict = {}
        for k, v in home_feats.items():
            feat_dict[f'home_{k}'] = v
        for k, v in away_feats.items():
            feat_dict[f'away_{k}'] = v
            
        # Ensure column order matches training? XGBoost generally handles dicts or DMatrix with names.
        # But safest to convert to DF
        return pd.DataFrame([feat_dict])

    def predict_xgb_inference(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Run XGBoost inference"""
        self._load_model()
        if self.model is None:
            return {}
            
        try:
            X = self._prepare_features(home_team, away_team)
            if X is None:
                return {}
            
            # Align columns if possible (XGBoost might complain about feature mismatch)
            # We trust the feature names match the training script logic
            
            prob = self.model.predict_proba(X)[0][1] # Probability of Class 1 (Win)
            
            # SHAP Explanation
            explanation = {}
            if self.explainer:
                try:
                    shap_values = self.explainer.shap_values(X)
                    # shap_values is array [samples, features] or list for multi-class
                    # Binary classification: might be (1, N)
                    vals = shap_values[0] if isinstance(shap_values, list) else shap_values[0]
                    
                    # Get feature names
                    feature_names = X.columns.tolist()
                    
                    # Pair feat + value
                    feat_contrib = list(zip(feature_names, vals))
                    
                    # Sort by absolute impact
                    feat_contrib.sort(key=lambda x: abs(x[1]), reverse=True)
                    
                    # Get top 3 positive (pushes to WIN) and top 3 negative (pushes to LOSS)
                    top_features = []
                    for name, impact in feat_contrib[:5]: # Top 5 total impact
                        direction = "Favors Home" if impact > 0 else "Favors Away"
                        # Clean name
                        clean_name = name.replace('home_', 'Home ').replace('away_', 'Away ').replace('_roll5', ' (L5)').replace('_roll10', ' (L10)').replace('_', ' ').title()
                        
                        top_features.append({
                            'feature': clean_name,
                            'impact': float(impact),
                            'direction': direction
                        })
                        
                    explanation = {'top_features': top_features}
                except Exception as ex:
                    logger.warning(f"SHAP failed: {ex}")

            return {
                'xgb_win_prob': float(prob),
                'xgb_pick': home_team if prob > 0.5 else away_team,
                'xgb_confidence': float(abs(prob - 0.5) * 2), # Scale 0.5-1.0 to 0-1.0
                'explanation': explanation
            }
        except Exception as e:
            logger.warning(f"XGBoost inference failed: {e}")
            return {}

    
    def predict_game(self, home_team: str, away_team: str, 
                     spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics.
        """
        # (Keep existing logic but prepare for data integration)
        home_stats = self.get_team_stats(home_team)
        away_stats = self.get_team_stats(away_team)
        
        # Home court advantage 
        home_advantage = 3.5
        
        # Calculate expected points based on Tempo-Free metrics if available
        # Adjusted Pace = (Home Pace + Away Pace) / 2
        # Adjusted Off Eff = (Home Off Eff + Away Def Eff) ... simplified
        
        avg_pace = (home_stats['pace'] + away_stats['pace']) / 2
        
        # Home Expected = Pace * Home Off Eff * Away Def Eff / Avg Efficiency (approx 1.03)
        # Using a simpler multiplicative model relative to league average (~1.03 PPP)
        league_ppp = 1.03
        
        home_expected = avg_pace * (home_stats['off_efficiency'] * away_stats['def_efficiency']) / league_ppp + (home_advantage / 2)
        away_expected = avg_pace * (away_stats['off_efficiency'] * home_stats['def_efficiency']) / league_ppp - (home_advantage / 2)
        
        # Fallback to simple PPG if efficiency seems way off (e.g. bad data)
        if home_expected < 40 or home_expected > 130:
             home_expected = (home_stats['ppg'] + away_stats['oppg']) / 2 + home_advantage / 2
             away_expected = (away_stats['ppg'] + home_stats['oppg']) / 2 - home_advantage / 2

        predicted_margin = home_expected - away_expected
        predicted_total = home_expected + away_expected
        
        # Win probability (logistic)
        home_win_prob = 1 / (1 + math.exp(-predicted_margin * 0.11))
        
        confidence = min(0.75, 0.5 + abs(predicted_margin) * 0.015)
        
        # Boost confidence if we have real data
        if home_stats.get('data_games', 0) > 5 and away_stats.get('data_games', 0) > 5:
            confidence = min(0.85, confidence + 0.1)

        result = {
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if predicted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 3),
            'away_win_probability': round(1 - home_win_prob, 3),
            'predicted_margin': round(predicted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'confidence': round(confidence, 2)
        }

        # XGBoost Integration
        xgb_res = self.predict_xgb_inference(home_team, away_team)
        if xgb_res:
            result['xgb_win_prob'] = round(xgb_res['xgb_win_prob'], 3)
            result['xgb_winner'] = xgb_res['xgb_pick']
            # Composite Confidence? Or just expose separately
            result['xgb_available'] = True
            result['explanation'] = xgb_res.get('explanation', {})
        else:
            result['xgb_available'] = False
        
        # Betting/Edge Analysis
        if spread is not None:
            line_margin = -spread
            model_edge = predicted_margin - line_margin
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if predicted_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 2.5
            
        if over_under is not None:
            ou_edge = predicted_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if predicted_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 3.0
        
        return result


async def get_todays_ncaab_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's NCAAB odds. Uses sbrscrape as primary, Odds API as fallback.
    """
    today = date.today()
    
    # Try sbrscrape first
    try:
        from sbrscrape import Scoreboard
        sb = Scoreboard(sport="NCAAB", date=today)
        
        if hasattr(sb, "games") and sb.games:
            games = []
            for game in sb.games:
                try:
                    game_data = {
                        "home_team": game.get('home_team', 'Unknown'),
                        "away_team": game.get('away_team', 'Unknown'),
                        "home_score": game.get('home_score'),
                        "away_score": game.get('away_score'),
                        "status": game.get('status', 'scheduled'),
                    }
                    
                    if 'total' in game and sportsbook in game.get('total', {}):
                        game_data['over_under'] = game['total'][sportsbook]
                    if 'away_spread' in game and sportsbook in game.get('away_spread', {}):
                        game_data['spread'] = game['away_spread'][sportsbook]
                    if 'home_ml' in game and sportsbook in game.get('home_ml', {}):
                        game_data['home_moneyline'] = game['home_ml'][sportsbook]
                    if 'away_ml' in game and sportsbook in game.get('away_ml', {}):
                        game_data['away_moneyline'] = game['away_ml'][sportsbook]
                        
                    games.append(game_data)
                except Exception as e:
                    logger.warning(f"Error parsing NCAAB game: {e}")
            
            if games:
                logger.info(f"Loaded {len(games)} NCAAB games from sbrscrape")
                return {
                    "date": str(today),
                    "sportsbook": sportsbook,
                    "games": games,
                    "count": len(games),
                    "source": "sbrscrape"
                }
    except Exception as e:
        logger.warning(f"sbrscrape failed for NCAAB: {e}")
    
    # Fallback to The Odds API
    from src.config import ODDS_API_KEY
    odds_api_key = ODDS_API_KEY
    
    if odds_api_key:
        try:
            import httpx
            
            book = SPORTSBOOK_MAP.get(sportsbook, "fanduel")
            url = "https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds"
            params = {
                "apiKey": odds_api_key,
                "regions": "us",
                "markets": "h2h,totals",
                "bookmakers": book,
            }
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    games = []
                    for event in data:
                        try:
                            home_team = event.get("home_team", "")
                            away_team = event.get("away_team", "")
                            
                            game_data = {
                                "home_team": home_team,
                                "away_team": away_team,
                                "game_time": event.get("commence_time", ""),
                                "status": "scheduled",
                            }
                            
                            # Extract odds from bookmakers
                            for bookmaker in event.get("bookmakers", []):
                                if bookmaker.get("key") == book:
                                    for market in bookmaker.get("markets", []):
                                        if market.get("key") == "h2h":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == home_team:
                                                    game_data["home_moneyline"] = _decimal_to_american(outcome.get("price", 2.0))
                                                elif outcome.get("name") == away_team:
                                                    game_data["away_moneyline"] = _decimal_to_american(outcome.get("price", 2.0))
                                        elif market.get("key") == "totals":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == "Over":
                                                    game_data["over_under"] = outcome.get("point", 140.0)
                                                    break
                            
                            games.append(game_data)
                        except Exception as e:
                            logger.warning(f"Error parsing NCAAB Odds API game: {e}")
                    
                    if games:
                        logger.info(f"Loaded {len(games)} NCAAB games from The Odds API")
                        
                        api_quota = {
                            "requests_remaining": int(response.headers.get("x-requests-remaining", 0)),
                            "requests_used": int(response.headers.get("x-requests-used", 0)),
                        }
                        
                        return {
                            "date": str(today),
                            "sportsbook": sportsbook,
                            "games": games,
                            "count": len(games),
                            "source": "the-odds-api",
                            "api_quota": api_quota
                        }
                else:
                    logger.warning(f"Odds API returned {response.status_code}")
                    
        except Exception as e:
            logger.warning(f"The Odds API failed for NCAAB: {e}")
    
    # No data available
    return {
        "date": str(today),
        "sportsbook": sportsbook,
        "games": [],
        "message": "No NCAAB games found for today"
    }


async def analyze_ncaab_matchup(home_team: str, away_team: str, 
                                 spread: float = None, over_under: float = None,
                                 home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive NCAAB matchup analysis."""
    predictor = NCAABPredictor()
    prediction = predictor.predict_game(home_team, away_team, spread, over_under)
    
    # Add moneyline analysis if provided
    if home_ml and away_ml:
        def implied_prob(odds):
            if odds > 0:
                return 100 / (odds + 100)
            else:
                return abs(odds) / (abs(odds) + 100)
        
        home_implied = implied_prob(home_ml)
        away_implied = implied_prob(away_ml)
        
        prediction['home_moneyline'] = home_ml
        prediction['away_moneyline'] = away_ml
        prediction['home_implied_prob'] = round(home_implied, 3)
        prediction['away_implied_prob'] = round(away_implied, 3)
        
        home_edge = prediction['home_win_probability'] - home_implied
        prediction['home_ml_edge'] = round(home_edge * 100, 1)
        prediction['ml_pick'] = home_team if home_edge > 0 else away_team
        prediction['ml_value'] = abs(home_edge) >= 0.05
    
    # Value bets summary
    value_bets = []
    if prediction.get('ml_value'):
        value_bets.append(f"ML: {prediction['ml_pick']}")
    if prediction.get('spread_value'):
        value_bets.append(f"Spread: {prediction['spread_pick']}")
    if prediction.get('ou_value'):
        value_bets.append(f"Total: {prediction['ou_pick']}")
    
    prediction['value_bets'] = value_bets
    prediction['has_value'] = len(value_bets) > 0
    prediction['model'] = 'simple'
    
    return prediction
