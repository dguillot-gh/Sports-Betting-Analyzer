"""
College Baseball Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under
"""

import logging
import os
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import logging
import os
import json
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import math
import pandas as pd
import numpy as np

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Try to import feature engineering from trainer
# If not available (e.g. running as script), define locally
try:
    from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer
except ImportError:
    CollegeBaseballXGBTrainer = None

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


class CollegeBaseballPredictor:
    """
    College baseball predictor using team statistics.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
        # Base runs per game average (lower than metal bat era, but still high)
        self.LEAGUE_AVG_RUNS = 6.5
        
        # Load XGBoost models
        self.model_ml = None
        self.model_ou = None
        self.use_xgb = False
        
        if xgb:
            try:
                models_dir = "models/college_baseball"
                ml_path = os.path.join(models_dir, "cbb_xgb_classifier.json")
                ou_path = os.path.join(models_dir, "cbb_xgb_regressor.json")
                
                if os.path.exists(ml_path) and os.path.exists(ou_path):
                    self.model_ml = xgb.XGBClassifier()
                    self.model_ml.load_model(ml_path)
                    
                    self.model_ou = xgb.XGBRegressor()
                    self.model_ou.load_model(ou_path)
                    
                    self.use_xgb = True
                    logger.info("Loaded College Baseball XGBoost models")
            except Exception as e:
                logger.warning(f"Failed to load XGBoost models: {e}")

    async def _get_rolling_stats(self, team_name: str) -> Optional[Dict]:
        """Fetch rolling stats from DB for a team."""
        try:
            # We need a DB connection
            conn = self.db
            should_close = False
            
            if not conn:
                try:
                    from src.config import DATABASE_URL as CFG_DB
                    db_url = CFG_DB
                except:
                    db_url = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/sports_betting")
                
                import asyncpg
                conn = await asyncpg.connect(db_url)
                should_close = True
            
            # Fetch recent results involving this team
            # We need both home and away games
            query = """
                SELECT metadata 
                FROM results 
                WHERE series = 'college_baseball' 
                  AND (metadata->>'homeTeam' = $1 OR metadata->>'awayTeam' = $1)
                ORDER BY event_date DESC
                LIMIT 20
            """
            rows = await conn.fetch(query, team_name)
            
            if should_close:
                await conn.close()
                
            if not rows or len(rows) < 5:
                return None
                
            # Process history
            history = []
            for row in rows:
                meta = json.loads(row['metadata'])
                is_home = meta.get('homeTeam') == team_name
                
                runs_for = float(meta.get('homeScore', 0) if is_home else meta.get('awayScore', 0))
                runs_against = float(meta.get('awayScore', 0) if is_home else meta.get('homeScore', 0))
                
                history.append({
                    'runs_scored': runs_for,
                    'runs_allowed': runs_against,
                    'won': 1 if runs_for > runs_against else 0
                })
            
            # Calculate stats (history is newest first, so reverse for chronological calc if needed, 
            # but simple averages don't care about order)
            
            # Last 5
            l5 = history[:5]
            runs_scored_l5 = sum(g['runs_scored'] for g in l5) / 5.0
            runs_allowed_l5 = sum(g['runs_allowed'] for g in l5) / 5.0
            
            # Last 10
            l10 = history[:10]
            win_pct_l10 = sum(g['won'] for g in l10) / len(l10)
            
            # Streak
            streak = 0
            for g in history: # these are ordered newest to oldest
                if g['won'] == 1:
                    if streak >= 0: streak += 1
                    else: break
                else:
                    if streak <= 0: streak -= 1
                    else: break
                    
            return {
                'runs_scored_avg_l5': runs_scored_l5,
                'runs_allowed_avg_l5': runs_allowed_l5,
                'win_pct_l10': win_pct_l10,
                'streak': streak
            }
            
        except Exception as e:
            logger.warning(f"Error fetching rolling stats for {team_name}: {e}")
            return None

    async def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Get team statistics. Returns defaults if team not in cache.
        """
        if team_name in self._team_stats_cache:
            return self._team_stats_cache[team_name]
        
        # Try to load from CSV stats
        # We need to find the stats file for this team
        # The importer saves as {sanitized_name}_stats.csv
        try:
            # Simple sanitization to match importer
            safe_id = "".join([c if c.isalnum() else "_" for c in team_name]).strip("_")
            
            # Look in standard data paths
            # Try finding the data dir relative to this script
            from pathlib import Path
            data_dir = Path("/app/data/baseball/stats")
            if not data_dir.exists():
                # Try local relative path (dev env)
                data_dir = Path(__file__).parent.parent / "data" / "baseball" / "stats"
            
            stats_file = data_dir / f"{safe_id}_stats.csv"
            
            if stats_file.exists():
                df = pd.read_csv(stats_file)
                if not df.empty:
                    row = df.iloc[0]
                    games = row.get('G', 0)
                    if games > 0:
                        # Map ncaa-bbStats columns to model features
                        # Using .get for robustness if columns change
                        runs_scored = row.get('R (Batting)', row.get('R', 0))
                        runs_allowed = row.get('R (Pitching)', 0) # Pitching runs allowed
                        
                        # If runs allowed is missing (0), try to estimate from ERA
                        if runs_allowed == 0 and 'ERA' in row:
                            # ERA * Innings / 9 approx Runs? Or just ERA * G?
                            # ERA is earned runs per 9 innings. 
                            # Runs allowed includes unearned. Factor of ~1.1 is typical.
                            # ip = row.get('IP', games * 9)
                            runs_allowed = row.get('ERA', 6.0) * (games * 9) / 9 * 1.15
                        
                        rpg = float(runs_scored) / games
                        rapg = float(runs_allowed) / games
                        
                        stats = {
                            'runs_per_game': rpg,
                            'runs_allowed': rapg,
                            'win_pct': row.get('W', 0) / games,
                            'home_win_pct': 0.65, # Keep defaults for splits if not in data
                            'away_win_pct': 0.45,
                            'sample_size': games
                        }
                        
                        # Cache and return
                        self._team_stats_cache[team_name] = stats
                        return stats
        except Exception as e:
            logger.warning(f"Could not load stats for {team_name}: {e}")

        # If file not found or empty, return None to indicate missing data
        # We generally do not want to use hardcoded defaults for live predictions
        return None
    
    async def predict_game(self, home_team: str, away_team: str, 
                     spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics (and XGBoost if available).
        """
        # Try to get rolling stats for XGBoost
        xgb_prediction = None
        
        if self.use_xgb:
            home_rolling = await self._get_rolling_stats(home_team)
            away_rolling = await self._get_rolling_stats(away_team)
            
            if home_rolling and away_rolling:
                try:
                    # Construct features vector matching trainer
                    features = pd.DataFrame([{
                        'home_runs_scored_avg_l5': home_rolling['runs_scored_avg_l5'],
                        'home_runs_allowed_avg_l5': home_rolling['runs_allowed_avg_l5'],
                        'home_win_pct_l10': home_rolling['win_pct_l10'],
                        'home_streak': home_rolling['streak'],
                        'away_runs_scored_avg_l5': away_rolling['runs_scored_avg_l5'],
                        'away_runs_allowed_avg_l5': away_rolling['runs_allowed_avg_l5'],
                        'away_win_pct_l10': away_rolling['win_pct_l10'],
                        'away_streak': away_rolling['streak'],
                        'is_neutral': 0 # Assumption for now
                    }])
                    
                    # Predict Win Prob
                    win_prob = self.model_ml.predict_proba(features)[0][1]
                    
                    # Predict Total Runs
                    total_runs = self.model_ou.predict(features)[0]
                    
                    xgb_prediction = {
                        'win_prob': float(win_prob),
                        'total_runs': float(total_runs)
                    }
                except Exception as e:
                    logger.error(f"XGBoost prediction failed: {e}")

        # Fallback / Baseline: Pythagorean Expectation
        home_stats = await self.get_team_stats(home_team)
        away_stats = await self.get_team_stats(away_team)
        
        if not home_stats or not away_stats:
            logger.warning(f"Missing stats for {home_team} or {away_team}")
            return {
                'home_team': home_team,
                'away_team': away_team,
                'error': 'Insufficient data',
                'description': 'Team stats not found in database. Please run import.'
            }
        
        # Home court advantage (typically 0.5-1.0 runs)
        home_advantage = 0.8
        
        # Calculate expected runs using Bill James Pythagorean expectation logic modified
        home_off_strength = home_stats['runs_per_game'] / self.LEAGUE_AVG_RUNS
        home_def_strength = home_stats['runs_allowed'] / self.LEAGUE_AVG_RUNS
        
        away_off_strength = away_stats['runs_per_game'] / self.LEAGUE_AVG_RUNS
        away_def_strength = away_stats['runs_allowed'] / self.LEAGUE_AVG_RUNS
        
        home_expected = (self.LEAGUE_AVG_RUNS * home_off_strength * away_def_strength) + (home_advantage / 2)
        away_expected = (self.LEAGUE_AVG_RUNS * away_off_strength * home_def_strength) - (home_advantage / 2)
        
        # Predicted margin
        predicted_margin = home_expected - away_expected
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        # Win probability using logistical Pythagenpat
        exponent = 1.83
        home_win_prob = (home_expected ** exponent) / ((home_expected ** exponent) + (away_expected ** exponent))
        
        # Model confidence
        confidence = min(0.80, 0.5 + abs(predicted_margin) * 0.05)
        
        result = {
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if predicted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 3),
            'away_win_probability': round(1 - home_win_prob, 3),
            'predicted_margin': round(predicted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'home_expected_runs': round(home_expected, 1),
            'away_expected_runs': round(away_expected, 1),
            'confidence': round(confidence, 2),
            'confidence_level': 'high' if confidence >= 0.65 else 'medium' if confidence >= 0.55 else 'low'
        }

        # Merge XGBoost results if available
        if xgb_prediction:
            # Weighted average of Pythagorean and XGBoost
            # Giving more weight to XGBoost as it's trained on recent form
            
            pyth_prob = result['home_win_probability']
            xgb_prob = xgb_prediction['win_prob']
            
            # 70% XGBoost, 30% Pythagorean
            combined_prob = (xgb_prob * 0.7) + (pyth_prob * 0.3)
            
            # Combined Total
            pyth_total = result['predicted_total']
            xgb_total = xgb_prediction['total_runs']
            combined_total = (xgb_total * 0.7) + (pyth_total * 0.3)
            
            result['home_win_probability'] = round(combined_prob, 3)
            result['away_win_probability'] = round(1 - combined_prob, 3)
            result['predicted_total'] = round(combined_total, 1)
            result['predicted_winner'] = home_team if combined_prob > 0.5 else away_team
            
            # Recalculate margin/confidence loosely
            result['predicted_margin'] = round((combined_prob - 0.5) * 10, 1) # Approximation
            result['xgb_available'] = True
            result['xgb_prob'] = round(xgb_prob, 3)
            result['xgb_total'] = round(xgb_total, 1)
        
        # Compare to betting lines
        if spread is not None:
            line_margin = -spread
            model_edge = predicted_margin - line_margin
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if predicted_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 1.5
            
        if over_under is not None:
            ou_edge = predicted_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if predicted_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 1.5
        
        return result


async def get_todays_college_baseball_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's College Baseball odds from The Odds API.
    """
    today = date.today()
    from src.config import ODDS_API_KEY
    odds_api_key = ODDS_API_KEY
    
    if odds_api_key:
        try:
            import httpx
            
            book = SPORTSBOOK_MAP.get(sportsbook, "fanduel")
            url = "https://api.the-odds-api.com/v4/sports/baseball_ncaa/odds"
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
                                                    game_data["over_under"] = outcome.get("point", 9.5)
                                                    break
                            
                            games.append(game_data)
                        except Exception as e:
                            logger.warning(f"Error parsing College Baseball Odds API game: {e}")
                    
                    if games:
                        logger.info(f"Loaded {len(games)} College Baseball games from The Odds API")
                        
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
            logger.warning(f"The Odds API failed for College Baseball: {e}")
    
    # No data available
    return {
        "date": str(today),
        "sportsbook": sportsbook,
        "games": [],
        "message": "No College Baseball games found for today"
    }


async def analyze_college_baseball_matchup(home_team: str, away_team: str, 
                                 spread: float = None, over_under: float = None,
                                 home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive College Baseball matchup analysis."""
    predictor = CollegeBaseballPredictor()
    prediction = await predictor.predict_game(home_team, away_team, spread, over_under)
    
    # If prediction failed (missing stats), return early with safe defaults
    if prediction.get('error'):
        prediction.setdefault('home_win_probability', 0.5)
        prediction.setdefault('away_win_probability', 0.5)
        prediction.setdefault('predicted_winner', home_team)
        prediction.setdefault('predicted_margin', 0.0)
        prediction.setdefault('predicted_total', 0.0)
        prediction.setdefault('confidence', 0.0)
        prediction.setdefault('confidence_level', 'low')
        prediction['value_bets'] = []
        prediction['has_value'] = False
        prediction['model'] = 'none'
        return prediction
    
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
