"""
Kyleskom NBA ML Adapter - Fixed Version
Bridges the reference kyleskom/NBA-Machine-Learning-Sports-Betting repo
with our Model Testing pages.

Uses their pre-trained XGBoost models (68.9% ML accuracy) and data pipeline.
This version EXACTLY matches their main.py prediction methodology.
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


# Headers for NBA API (matching reference repo exactly)
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Origin": "https://www.nba.com",
    "Priority": "u=3, i",
    "Referer": "https://www.nba.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0.1 Safari/605.1.15"
}

# Team index mapping (from reference repo's Dictionaries.py)
TEAM_INDEX_CURRENT = {
    'Atlanta Hawks': 0, 'Boston Celtics': 1, 'Brooklyn Nets': 2, 'Charlotte Hornets': 3,
    'Chicago Bulls': 4, 'Cleveland Cavaliers': 5, 'Dallas Mavericks': 6, 'Denver Nuggets': 7,
    'Detroit Pistons': 8, 'Golden State Warriors': 9, 'Houston Rockets': 10, 'Indiana Pacers': 11,
    'Los Angeles Clippers': 12, 'Los Angeles Lakers': 13, 'Memphis Grizzlies': 14, 'Miami Heat': 15,
    'Milwaukee Bucks': 16, 'Minnesota Timberwolves': 17, 'New Orleans Pelicans': 18, 'New York Knicks': 19,
    'Oklahoma City Thunder': 20, 'Orlando Magic': 21, 'Philadelphia 76ers': 22, 'Phoenix Suns': 23,
    'Portland Trail Blazers': 24, 'Sacramento Kings': 25, 'San Antonio Spurs': 26, 'Toronto Raptors': 27,
    'Utah Jazz': 28, 'Washington Wizards': 29
}

# Team name aliases - maps common variations to canonical names
TEAM_NAME_ALIASES = {
    # LA teams - most common mismatch (all possible variations)
    'LA Clippers': 'Los Angeles Clippers',
    'LA Lakers': 'Los Angeles Lakers',
    'L.A. Clippers': 'Los Angeles Clippers',
    'L.A. Lakers': 'Los Angeles Lakers',
    'LAC': 'Los Angeles Clippers',
    'LAL': 'Los Angeles Lakers',
    'Los Angeles': 'Los Angeles Lakers',  # Assume Lakers if just "Los Angeles"
    'Clippers': 'Los Angeles Clippers',
    'Lakers': 'Los Angeles Lakers',
    
    # Golden State variations
    'GS Warriors': 'Golden State Warriors',
    'GSW': 'Golden State Warriors',
    'Golden State': 'Golden State Warriors',
    'Warriors': 'Golden State Warriors',
    
    # Other common variations with abbreviations
    'NY Knicks': 'New York Knicks',
    'New York': 'New York Knicks',
    'NYK': 'New York Knicks',
    'Knicks': 'New York Knicks',
    
    'OKC Thunder': 'Oklahoma City Thunder',
    'OKC': 'Oklahoma City Thunder',
    'Oklahoma City': 'Oklahoma City Thunder',
    'Thunder': 'Oklahoma City Thunder',
    
    'Philly 76ers': 'Philadelphia 76ers',
    'PHI': 'Philadelphia 76ers',
    'Sixers': 'Philadelphia 76ers',
    '76ers': 'Philadelphia 76ers',
    
    'NOLA Pelicans': 'New Orleans Pelicans',
    'NOP': 'New Orleans Pelicans',
    'New Orleans': 'New Orleans Pelicans',
    'Pelicans': 'New Orleans Pelicans',
    
    'Blazers': 'Portland Trail Blazers',
    'Trail Blazers': 'Portland Trail Blazers',
    'POR': 'Portland Trail Blazers',
    'Portland': 'Portland Trail Blazers',
    
    # All teams with city-only and short name versions
    'Boston': 'Boston Celtics',
    'BOS': 'Boston Celtics',
    'Celtics': 'Boston Celtics',
    
    'Brooklyn': 'Brooklyn Nets',
    'BKN': 'Brooklyn Nets',
    'Nets': 'Brooklyn Nets',
    
    'Charlotte': 'Charlotte Hornets',
    'CHA': 'Charlotte Hornets',
    'Hornets': 'Charlotte Hornets',
    
    'Chicago': 'Chicago Bulls',
    'CHI': 'Chicago Bulls',
    'Bulls': 'Chicago Bulls',
    
    'Cleveland': 'Cleveland Cavaliers',
    'CLE': 'Cleveland Cavaliers',
    'Cavaliers': 'Cleveland Cavaliers',
    'Cavs': 'Cleveland Cavaliers',
    
    'Dallas': 'Dallas Mavericks',
    'DAL': 'Dallas Mavericks',
    'Mavericks': 'Dallas Mavericks',
    'Mavs': 'Dallas Mavericks',
    
    'Denver': 'Denver Nuggets',
    'DEN': 'Denver Nuggets',
    'Nuggets': 'Denver Nuggets',
    
    'Detroit': 'Detroit Pistons',
    'DET': 'Detroit Pistons',
    'Pistons': 'Detroit Pistons',
    
    'Houston': 'Houston Rockets',
    'HOU': 'Houston Rockets',
    'Rockets': 'Houston Rockets',
    
    'Indiana': 'Indiana Pacers',
    'IND': 'Indiana Pacers',
    'Pacers': 'Indiana Pacers',
    
    'Memphis': 'Memphis Grizzlies',
    'MEM': 'Memphis Grizzlies',
    'Grizzlies': 'Memphis Grizzlies',
    
    'Miami': 'Miami Heat',
    'MIA': 'Miami Heat',
    'Heat': 'Miami Heat',
    
    'Milwaukee': 'Milwaukee Bucks',
    'MIL': 'Milwaukee Bucks',
    'Bucks': 'Milwaukee Bucks',
    
    'Minnesota': 'Minnesota Timberwolves',
    'MIN': 'Minnesota Timberwolves',
    'Timberwolves': 'Minnesota Timberwolves',
    'Wolves': 'Minnesota Timberwolves',
    
    'Orlando': 'Orlando Magic',
    'ORL': 'Orlando Magic',
    'Magic': 'Orlando Magic',
    
    'Phoenix': 'Phoenix Suns',
    'PHX': 'Phoenix Suns',
    'Suns': 'Phoenix Suns',
    
    'Sacramento': 'Sacramento Kings',
    'SAC': 'Sacramento Kings',
    'Kings': 'Sacramento Kings',
    
    'San Antonio': 'San Antonio Spurs',
    'SAS': 'San Antonio Spurs',
    'Spurs': 'San Antonio Spurs',
    
    'Toronto': 'Toronto Raptors',
    'TOR': 'Toronto Raptors',
    'Raptors': 'Toronto Raptors',
    
    'Utah': 'Utah Jazz',
    'UTA': 'Utah Jazz',
    'Jazz': 'Utah Jazz',
    
    'Washington': 'Washington Wizards',
    'WAS': 'Washington Wizards',
    'Wizards': 'Washington Wizards',
    
    # Atlanta - could be confused
    'Atlanta': 'Atlanta Hawks',
    'ATL': 'Atlanta Hawks',
    'Hawks': 'Atlanta Hawks',
}


def normalize_team_name(team: str) -> str:
    """Normalize team name to canonical format expected by kyleskom model."""
    if team in TEAM_INDEX_CURRENT:
        return team
    if team in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[team]
    # Try case-insensitive match
    team_lower = team.lower()
    for alias, canonical in TEAM_NAME_ALIASES.items():
        if alias.lower() == team_lower:
            return canonical
    for canonical in TEAM_INDEX_CURRENT.keys():
        if canonical.lower() == team_lower:
            return canonical
    return team  # Return original if no match


class KyleskomPredictor:
    """
    Uses kyleskom's pre-trained XGBoost models for NBA predictions.
    This version matches their main.py exactly.
    """
    
    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.df = None  # Raw DataFrame from NBA API (not sorted)
        self._models_loaded = False
        self._data_loaded = False
    
    def load_models(self) -> bool:
        """Load the pre-trained models from the reference repo."""
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available")
            return False
        
        if self._models_loaded:
            return True
        
        try:
            # Find best ML model
            ml_model_files = [
                'XGBoost_68.9%_ML-3.json',
                'XGBoost_68.7%_ML-4.json'
            ]
            
            for fname in ml_model_files:
                ml_path = os.path.join(MODELS_PATH, fname)
                if os.path.exists(ml_path):
                    self.model_ml = xgb.Booster()
                    self.model_ml.load_model(ml_path)
                    logger.info(f"Loaded ML model: {fname}")
                    break
            
            if not self.model_ml:
                logger.error(f"No ML model found in {MODELS_PATH}")
                return False
            
            # Find best OU model
            ou_model_files = [
                'XGBoost_54.8%_UO-8.json',
                'XGBoost_53.7%_UO-9.json'
            ]
            
            for fname in ou_model_files:
                ou_path = os.path.join(MODELS_PATH, fname)
                if os.path.exists(ou_path):
                    self.model_ou = xgb.Booster()
                    self.model_ou.load_model(ou_path)
                    logger.info(f"Loaded OU model: {fname}")
                    break
            
            self._models_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error loading models: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def fetch_data_from_nba_api(self) -> bool:
        """
        Fetch current team stats from NBA API exactly like reference repo's main.py.
        """
        if self._data_loaded and self.df is not None:
            return True
        
        import aiohttp
        
        # Determine current season
        now = datetime.now()
        if now.month >= 10:
            season = f"{now.year}-{str(now.year + 1)[2:]}"
        else:
            season = f"{now.year - 1}-{str(now.year)[2:]}"
        
        # This is the exact same URL format as reference repo
        url = (
            f"https://stats.nba.com/stats/leaguedashteamstats?"
            f"Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&"
            f"ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&"
            f"OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&"
            f"PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season={season}&"
            f"SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&"
            f"TeamID=0&TwoWay=0&VsConference=&VsDivision="
        )
        
        logger.info(f"Fetching NBA team stats for season {season}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=NBA_API_HEADERS, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"NBA API returned {response.status}")
                        return False
                    
                    data = await response.json()
            
            # Parse exactly like reference repo's tools.py to_data_frame function
            result_sets = data.get('resultSets', [])
            if not result_sets:
                logger.error("No resultSets in NBA API response")
                return False
            
            data_list = result_sets[0]
            headers = data_list.get('headers', [])
            rows = data_list.get('rowSet', [])
            
            self.df = pd.DataFrame(data=rows, columns=headers)
            logger.info(f"Fetched {len(self.df)} teams with {len(headers)} columns")
            logger.info(f"Columns: {list(headers)[:10]}...")
            
            self._data_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error fetching from NBA API: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def predict_game(
        self,
        home_team: str,
        away_team: str,
        total_line: float = 225.0,
        home_ml: int = None,
        away_ml: int = None
    ) -> Dict[str, Any]:
        """
        Predict game outcome EXACTLY like reference repo's main.py createTodaysGames function.
        """
        # Normalize team names to handle variations like "LA Clippers" -> "Los Angeles Clippers"
        home_team = normalize_team_name(home_team)
        away_team = normalize_team_name(away_team)
        
        # Load models
        if not self._models_loaded:
            if not self.load_models():
                return {"error": "Could not load kyleskom models"}
        
        # Fetch data
        if not self._data_loaded:
            if not await self.fetch_data_from_nba_api():
                return {"error": "Could not fetch team stats from NBA API"}
        
        # Check if teams exist in our index
        home_idx = TEAM_INDEX_CURRENT.get(home_team)
        away_idx = TEAM_INDEX_CURRENT.get(away_team)
        
        if home_idx is None:
            return {"error": f"Team not found in index: {home_team}"}
        if away_idx is None:
            return {"error": f"Team not found in index: {away_team}"}
        
        # Find teams in DataFrame by TEAM_NAME
        # Note: NBA API may use different names than our canonical (e.g., "LA Clippers" vs "Los Angeles Clippers")
        try:
            # Build reverse mapping for NBA API lookup
            nba_api_name_map = {
                'Los Angeles Clippers': 'LA Clippers',
                'Los Angeles Lakers': 'LA Lakers',
                # Add other possible mismatches
            }
            
            # Try canonical name first, then NBA API variant
            home_api_name = nba_api_name_map.get(home_team, home_team)
            away_api_name = nba_api_name_map.get(away_team, away_team)
            
            # Try canonical name first
            home_row = self.df[self.df['TEAM_NAME'] == home_team]
            if len(home_row) == 0:
                # Try NBA API variant
                home_row = self.df[self.df['TEAM_NAME'] == home_api_name]
            if len(home_row) == 0:
                # Try case-insensitive partial match
                home_row = self.df[self.df['TEAM_NAME'].str.contains(home_team.split()[-1], case=False, na=False)]
            
            away_row = self.df[self.df['TEAM_NAME'] == away_team]
            if len(away_row) == 0:
                away_row = self.df[self.df['TEAM_NAME'] == away_api_name]
            if len(away_row) == 0:
                away_row = self.df[self.df['TEAM_NAME'].str.contains(away_team.split()[-1], case=False, na=False)]
            
            if len(home_row) == 0:
                # Log available teams for debugging
                available = list(self.df['TEAM_NAME'].unique()) if 'TEAM_NAME' in self.df.columns else []
                logger.error(f"Team not found in API data: {home_team}. Available: {available[:5]}...")
                return {"error": f"Team not found in API data: {home_team}"}
            if len(away_row) == 0:
                return {"error": f"Team not found in API data: {away_team}"}
            
            home_series = home_row.iloc[0]
            away_series = away_row.iloc[0]
            
            # Drop TEAM_ID before concatenation (we keep TEAM_NAME for now, drop later)
            home_series = home_series.drop(['TEAM_ID'], errors='ignore')
            away_series = away_series.drop(['TEAM_ID'], errors='ignore')
            
            # Rename away columns with .1 suffix (like Create_Games.py line 79-81)
            away_series_renamed = away_series.rename(
                index={col: f"{col}.1" if col != 'TEAM_NAME' else 'TEAM_NAME.1' for col in away_series.index}
            )
            
            # Concatenate like reference repo (line 66 of main.py)
            stats = pd.concat([home_series, away_series_renamed])
            
            # Add rest days at the end (like Create_Games.py lines 92-93)
            stats['Days-Rest-Home'] = 1
            stats['Days-Rest-Away'] = 1
            
            # Now drop TEAM_NAME and TEAM_NAME.1 (like line 74 of main.py)
            # We do this on the Series before converting to DataFrame
            stats = stats.drop(['TEAM_NAME', 'TEAM_NAME.1'], errors='ignore')
            
            # Convert to DataFrame row format
            data = stats.values.astype(float).reshape(1, -1)
            
            logger.info(f"Feature shape for {home_team} vs {away_team}: {data.shape} (expected 106 for ML)")
            
            if data.shape[1] != 106:
                logger.warning(f"Feature count mismatch! Expected 106, got {data.shape[1]}")
            
            # Create DMatrix and predict
            dmatrix = xgb.DMatrix(data)
            ml_pred = self.model_ml.predict(dmatrix)[0]
            
            # ML model uses multi:softprob with num_class=2
            # Output is [away_win_prob, home_win_prob]
            if len(ml_pred) >= 2:
                away_win_prob = float(ml_pred[0])
                home_win_prob = float(ml_pred[1])
            else:
                home_win_prob = float(ml_pred)
                away_win_prob = 1 - home_win_prob
            
            # O/U prediction
            ou_pred = None
            if self.model_ou and total_line:
                try:
                    # For O/U, we need to add the OU column at the end (107 features total)
                    # Append OU to the data array
                    data_ou = np.append(data, [[total_line]], axis=1)
                    
                    logger.info(f"O/U feature shape: {data_ou.shape} (expected 107 for O/U)")
                    
                    dmatrix_ou = xgb.DMatrix(data_ou)
                    ou_raw = self.model_ou.predict(dmatrix_ou)[0]
                    
                    # OU model uses multi:softprob with num_class=3 (under, over, push)
                    if len(ou_raw) >= 2:
                        under_prob = float(ou_raw[0])
                        over_prob = float(ou_raw[1])
                        ou_pred = {
                            'pick': 'OVER' if over_prob > under_prob else 'UNDER',
                            'confidence': float(round(max(over_prob, under_prob) * 100, 1)),
                            'total_line': float(total_line),
                            'over_prob': float(round(over_prob, 3)),
                            'under_prob': float(round(under_prob, 3))
                        }
                except Exception as ou_error:
                    logger.error(f"O/U prediction error: {ou_error}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            # Calculate EV and Kelly
            ev_home = ev_away = None
            kelly_home = kelly_away = None
            
            if home_ml and away_ml:
                ev_home = self._expected_value(home_win_prob, home_ml)
                ev_away = self._expected_value(away_win_prob, away_ml)
                kelly_home = self._kelly_criterion(home_ml, home_win_prob)
                kelly_away = self._kelly_criterion(away_ml, away_win_prob)
            
            predicted_winner = home_team if home_win_prob > away_win_prob else away_team
            winner_idx = 1 if home_win_prob > away_win_prob else 0
            confidence = float(round(float(ml_pred[winner_idx]) * 100 if len(ml_pred) >= 2 else max(home_win_prob, away_win_prob) * 100, 1))
            
            return {
                'model': 'kyleskom_xgb',
                'model_accuracy': '68.9%',
                'home_team': home_team,
                'away_team': away_team,
                'home_win_probability': float(round(home_win_prob, 4)),
                'away_win_probability': float(round(away_win_prob, 4)),
                'predicted_winner': predicted_winner,
                'confidence': float(confidence),
                'over_under': ou_pred,
                'ev_home': float(ev_home) if ev_home is not None else None,
                'ev_away': float(ev_away) if ev_away is not None else None,
                'kelly_home': float(kelly_home) if kelly_home is not None else None,
                'kelly_away': float(kelly_away) if kelly_away is not None else None,
                'features_used': int(data.shape[1]) if len(data.shape) > 1 else int(len(data)),
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
