"""
Kyleskom NBA ML Adapter
Bridges the reference kyleskom/NBA-Machine-Learning-Sports-Betting repo
with our Model Testing pages.

Uses their pre-trained XGBoost models (68.9% ML accuracy) and data pipeline.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import sys

logger = logging.getLogger(__name__)

# Path to the cloned reference repo
REFERENCE_REPO_PATH = os.path.join(os.path.dirname(__file__), 'nba_ml_reference')
MODELS_PATH = os.path.join(REFERENCE_REPO_PATH, 'Models', 'XGBoost_Models')

# Check if XGBoost available
try:
    import xgboost as xgb
    import numpy as np
    import pandas as pd
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not available")


# Headers for NBA API (from reference repo)
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Team index mapping (from reference repo)
TEAM_INDEX = {
    'Atlanta Hawks': 0, 'Boston Celtics': 1, 'Brooklyn Nets': 2, 'Charlotte Hornets': 3,
    'Chicago Bulls': 4, 'Cleveland Cavaliers': 5, 'Dallas Mavericks': 6, 'Denver Nuggets': 7,
    'Detroit Pistons': 8, 'Golden State Warriors': 9, 'Houston Rockets': 10, 'Indiana Pacers': 11,
    'Los Angeles Clippers': 12, 'Los Angeles Lakers': 13, 'Memphis Grizzlies': 14, 'Miami Heat': 15,
    'Milwaukee Bucks': 16, 'Minnesota Timberwolves': 17, 'New Orleans Pelicans': 18, 'New York Knicks': 19,
    'Oklahoma City Thunder': 20, 'Orlando Magic': 21, 'Philadelphia 76ers': 22, 'Phoenix Suns': 23,
    'Portland Trail Blazers': 24, 'Sacramento Kings': 25, 'San Antonio Spurs': 26, 'Toronto Raptors': 27,
    'Utah Jazz': 28, 'Washington Wizards': 29
}


class KyleskomPredictor:
    """
    Uses kyleskom's pre-trained XGBoost models for NBA predictions.
    """
    
    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.team_stats_df = None
        self._loaded = False
    
    def load_models(self) -> bool:
        """Load the pre-trained models from the reference repo."""
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available")
            return False
        
        try:
            # Load the best ML model (68.9% accuracy)
            ml_model_path = os.path.join(MODELS_PATH, 'XGBoost_68.9%_ML-3.json')
            if not os.path.exists(ml_model_path):
                ml_model_path = os.path.join(MODELS_PATH, 'XGBoost_68.7%_ML-4.json')
            
            if os.path.exists(ml_model_path):
                self.model_ml = xgb.Booster()
                self.model_ml.load_model(ml_model_path)
                logger.info(f"Loaded ML model from {ml_model_path}")
            else:
                logger.error(f"ML model not found at {ml_model_path}")
                return False
            
            # Load the OU model
            ou_model_path = os.path.join(MODELS_PATH, 'XGBoost_54.8%_UO-8.json')
            if not os.path.exists(ou_model_path):
                ou_model_path = os.path.join(MODELS_PATH, 'XGBoost_53.7%_UO-9.json')
            
            if os.path.exists(ou_model_path):
                self.model_ou = xgb.Booster()
                self.model_ou.load_model(ou_model_path)
                logger.info(f"Loaded OU model from {ou_model_path}")
            
            self._loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error loading models: {e}")
            return False
    
    async def fetch_team_stats_from_nba_api(self) -> Optional[pd.DataFrame]:
        """
        Fetch current team stats from NBA API (like reference repo does).
        Returns DataFrame with all team stats.
        """
        import aiohttp
        
        # Determine current season
        now = datetime.now()
        if now.month >= 10:
            season = f"{now.year}-{str(now.year + 1)[2:]}"
        else:
            season = f"{now.year - 1}-{str(now.year)[2:]}"
        
        url = (
            f"https://stats.nba.com/stats/leaguedashteamstats?"
            f"Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&"
            f"ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&"
            f"OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&"
            f"PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season={season}&"
            f"SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&"
            f"TeamID=0&TwoWay=0&VsConference=&VsDivision="
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=NBA_API_HEADERS, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"NBA API returned {response.status}")
                        return None
                    
                    data = await response.json()
            
            result_sets = data.get('resultSets', [])
            if not result_sets:
                return None
            
            team_data = result_sets[0]
            headers = team_data.get('headers', [])
            rows = team_data.get('rowSet', [])
            
            df = pd.DataFrame(rows, columns=headers)
            
            # Sort by team index to match reference repo ordering
            df['TEAM_INDEX'] = df['TEAM_NAME'].map(TEAM_INDEX)
            df = df.sort_values('TEAM_INDEX').reset_index(drop=True)
            
            self.team_stats_df = df
            logger.info(f"Fetched stats for {len(df)} teams from NBA API")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching from NBA API: {e}")
            return None
    
    def calculate_days_rest(self, team_name: str, schedule_df: pd.DataFrame = None) -> int:
        """
        Calculate days since last game for a team.
        Falls back to 1 if schedule not available.
        """
        if schedule_df is None:
            return 1
        
        try:
            team_games = schedule_df[
                (schedule_df['Home Team'] == team_name) | 
                (schedule_df['Away Team'] == team_name)
            ]
            previous_games = team_games[
                team_games['Date'] <= datetime.today()
            ].sort_values('Date', ascending=False).head(1)
            
            if len(previous_games) > 0:
                last_date = previous_games['Date'].iloc[0]
                days_rest = (datetime.today() - last_date).days + 1
                return min(days_rest, 7)  # Cap at 7
            return 2  # Default
            
        except Exception as e:
            logger.warning(f"Error calculating rest for {team_name}: {e}")
            return 1
    
    async def predict_game(
        self,
        home_team: str,
        away_team: str,
        total_line: float = 225.0,
        home_ml: int = None,
        away_ml: int = None
    ) -> Dict[str, Any]:
        """
        Predict game outcome using kyleskom's methodology.
        
        This matches the reference repo's approach:
        1. Fetch all team stats from NBA API
        2. Concatenate home + away team stats
        3. Add Days-Rest-Home and Days-Rest-Away
        4. Run through pre-trained XGBoost models
        """
        if not self._loaded:
            if not self.load_models():
                return {"error": "Could not load kyleskom models"}
        
        # Fetch current team stats if not cached
        if self.team_stats_df is None:
            await self.fetch_team_stats_from_nba_api()
        
        if self.team_stats_df is None:
            return {"error": "Could not fetch team stats from NBA API"}
        
        # Get team indices
        home_idx = TEAM_INDEX.get(home_team)
        away_idx = TEAM_INDEX.get(away_team)
        
        if home_idx is None or away_idx is None:
            return {"error": f"Team not found: {home_team} or {away_team}"}
        
        try:
            # Get team rows (excluding TEAM_ID and TEAM_NAME for model)
            home_row = self.team_stats_df.iloc[home_idx].drop(['TEAM_ID', 'TEAM_NAME', 'TEAM_INDEX'], errors='ignore')
            away_row = self.team_stats_df.iloc[away_idx].drop(['TEAM_ID', 'TEAM_NAME', 'TEAM_INDEX'], errors='ignore')
            
            # Concatenate like reference repo does
            combined = pd.concat([home_row, away_row])
            
            # Add rest days
            combined['Days-Rest-Home'] = self.calculate_days_rest(home_team)
            combined['Days-Rest-Away'] = self.calculate_days_rest(away_team)
            
            # Convert to feature matrix
            data = combined.values.astype(float).reshape(1, -1)
            dmatrix = xgb.DMatrix(data)
            
            # Predict ML (Moneyline)
            ml_pred = self.model_ml.predict(dmatrix)[0]
            
            # ML model outputs [away_win_prob, home_win_prob] or similar
            # Reference repo uses argmax, let's get probabilities
            if len(ml_pred) >= 2:
                away_win_prob = float(ml_pred[0])
                home_win_prob = float(ml_pred[1])
            else:
                home_win_prob = float(ml_pred)
                away_win_prob = 1 - home_win_prob
            
            # Predict O/U if model available
            ou_pred = None
            if self.model_ou:
                # Add OU line to features for O/U prediction
                combined_ou = combined.copy()
                combined_ou['OU'] = total_line
                data_ou = combined_ou.values.astype(float).reshape(1, -1)
                dmatrix_ou = xgb.DMatrix(data_ou)
                ou_pred_raw = self.model_ou.predict(dmatrix_ou)[0]
                
                # O/U model outputs [under_prob, over_prob, push_prob]
                if len(ou_pred_raw) >= 2:
                    under_prob = float(ou_pred_raw[0])
                    over_prob = float(ou_pred_raw[1])
                    ou_pred = {
                        'under_prob': round(under_prob, 3),
                        'over_prob': round(over_prob, 3),
                        'pick': 'OVER' if over_prob > under_prob else 'UNDER',
                        'confidence': round(max(over_prob, under_prob) * 100, 1),
                        'total_line': total_line
                    }
            
            # Calculate EV and Kelly if odds provided
            ev_home = ev_away = None
            kelly_home = kelly_away = None
            
            if home_ml and away_ml:
                ev_home = self._expected_value(home_win_prob, home_ml)
                ev_away = self._expected_value(away_win_prob, away_ml)
                kelly_home = self._kelly_criterion(home_ml, home_win_prob)
                kelly_away = self._kelly_criterion(away_ml, away_win_prob)
            
            predicted_winner = home_team if home_win_prob > away_win_prob else away_team
            confidence = round(max(home_win_prob, away_win_prob) * 100, 1)
            
            return {
                'model': 'kyleskom_xgb',
                'model_accuracy': '68.9%',
                'home_team': home_team,
                'away_team': away_team,
                'home_win_probability': round(home_win_prob, 4),
                'away_win_probability': round(away_win_prob, 4),
                'predicted_winner': predicted_winner,
                'confidence': confidence,
                'over_under': ou_pred,
                'ev_home': ev_home,
                'ev_away': ev_away,
                'kelly_home': kelly_home,
                'kelly_away': kelly_away,
                'features_used': len(combined),
                'rest_home': combined.get('Days-Rest-Home', 1),
                'rest_away': combined.get('Days-Rest-Away', 1),
            }
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"error": str(e)}
    
    def _expected_value(self, win_prob: float, american_odds: int) -> float:
        """Calculate expected value (from reference repo)."""
        if american_odds > 0:
            payout = american_odds
        else:
            payout = (100 / abs(american_odds)) * 100
        
        loss_prob = 1 - win_prob
        ev = (win_prob * payout) - (loss_prob * 100)
        return round(ev, 2)
    
    def _kelly_criterion(self, american_odds: int, model_prob: float) -> float:
        """Calculate Kelly Criterion (from reference repo)."""
        if american_odds >= 100:
            decimal_odds = american_odds / 100
        else:
            decimal_odds = 100 / abs(american_odds)
        
        bankroll_fraction = (100 * (decimal_odds * model_prob - (1 - model_prob))) / decimal_odds
        return round(max(0, bankroll_fraction), 2)


# Singleton instance
_predictor = None

def get_kyleskom_predictor() -> KyleskomPredictor:
    global _predictor
    if _predictor is None:
        _predictor = KyleskomPredictor()
    return _predictor


async def predict_with_kyleskom(
    home_team: str,
    away_team: str,
    total_line: float = 225.0,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Convenience function to make predictions using kyleskom's models.
    """
    predictor = get_kyleskom_predictor()
    return await predictor.predict_game(
        home_team, away_team, total_line, home_ml, away_ml
    )
