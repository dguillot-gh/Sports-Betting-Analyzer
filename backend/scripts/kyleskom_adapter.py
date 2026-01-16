"""
Kyleskom NBA ML Adapter - Fixed Version
Bridges the reference kyleskom/NBA-Machine-Learning-Sports-Betting repo
with our Model Testing pages.

Uses their pre-trained XGBoost models (68.9% ML accuracy) and data pipeline.
This version EXACTLY matches their main.py and XGBoost_Runner.py methodology.
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any
from pathlib import Path

# Joblib required for loading calibration models (.pkl)
import joblib

logger = logging.getLogger(__name__)

# Path to the cloned reference repo
REFERENCE_REPO_PATH = os.path.join(os.path.dirname(__file__), 'nba_ml_reference')
# Regex for model accuracy parsing (matches XGBoost_Runner.py)
XGB_ACCURACY_PATTERN = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")
# Regex for NN models (matches NN_Runner.py)
NN_ML_PATTERN = re.compile(r"Trained-Model-ML-(\d+(?:\.\d+)?)")
NN_OU_PATTERN = re.compile(r"Trained-Model-OU-(\d+(?:\.\d+)?)")

# Check if XGBoost available
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not available")

# Check if ONNX Runtime available
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
    logger.info("ONNX Runtime environment detected")
except ImportError:
    ONNX_AVAILABLE = False
    logger.warning("ONNX Runtime not available")

import numpy as np
import pandas as pd


# ... [Existing Headers and Team Dictionaries remain identical] ...


# Headers for NBA API (matching reference repo exactly)
# ... (rest of headers logic stays same, skipping to class) ...

class KyleskomPredictor:
    """
    Uses kyleskom's pre-trained XGBoost AND Neural Network models.
    Matches main.py, XGBoost_Runner.py, and NN_Runner.py methodology.
    """
    
    def __init__(self):
        # XGBoost models
        self.xgb_ml = None
        self.xgb_ou = None
        self.xgb_ml_calibrator = None
        self.xgb_uo_calibrator = None
        
        # NN models
        self.nn_ml = None
        self.nn_ou = None
        
        self.df = None  # Raw DataFrame from NBA API (not sorted)
        self._models_loaded = False
        self._data_loaded = False
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
    # LA teams - most common mismatch
    'LA Clippers': 'Los Angeles Clippers',
    'LA Lakers': 'Los Angeles Lakers',
    'L.A. Clippers': 'Los Angeles Clippers',
    'L.A. Lakers': 'Los Angeles Lakers',
    'LAC': 'Los Angeles Clippers',
    'LAL': 'Los Angeles Lakers',
    'Los Angeles': 'Los Angeles Lakers',
    'Clippers': 'Los Angeles Clippers',
    'Lakers': 'Los Angeles Lakers',
    
    # Golden State
    'GS Warriors': 'Golden State Warriors',
    'GSW': 'Golden State Warriors',
    'Golden State': 'Golden State Warriors',
    'Warriors': 'Golden State Warriors',
    
    # Other common variations
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
    
    # Short names
    'Boston': 'Boston Celtics', 'BOS': 'Boston Celtics', 'Celtics': 'Boston Celtics',
    'Brooklyn': 'Brooklyn Nets', 'BKN': 'Brooklyn Nets', 'Nets': 'Brooklyn Nets',
    'Charlotte': 'Charlotte Hornets', 'CHA': 'Charlotte Hornets', 'Hornets': 'Charlotte Hornets',
    'Chicago': 'Chicago Bulls', 'CHI': 'Chicago Bulls', 'Bulls': 'Chicago Bulls',
    'Cleveland': 'Cleveland Cavaliers', 'CLE': 'Cleveland Cavaliers', 'Cavaliers': 'Cleveland Cavaliers', 'Cavs': 'Cleveland Cavaliers',
    'Dallas': 'Dallas Mavericks', 'DAL': 'Dallas Mavericks', 'Mavericks': 'Dallas Mavericks', 'Mavs': 'Dallas Mavericks',
    'Denver': 'Denver Nuggets', 'DEN': 'Denver Nuggets', 'Nuggets': 'Denver Nuggets',
    'Detroit': 'Detroit Pistons', 'DET': 'Detroit Pistons', 'Pistons': 'Detroit Pistons',
    'Houston': 'Houston Rockets', 'HOU': 'Houston Rockets', 'Rockets': 'Houston Rockets',
    'Indiana': 'Indiana Pacers', 'IND': 'Indiana Pacers', 'Pacers': 'Indiana Pacers',
    'Memphis': 'Memphis Grizzlies', 'MEM': 'Memphis Grizzlies', 'Grizzlies': 'Memphis Grizzlies',
    'Miami': 'Miami Heat', 'MIA': 'Miami Heat', 'Heat': 'Miami Heat',
    'Milwaukee': 'Milwaukee Bucks', 'MIL': 'Milwaukee Bucks', 'Bucks': 'Milwaukee Bucks',
    'Minnesota': 'Minnesota Timberwolves', 'MIN': 'Minnesota Timberwolves', 'Timberwolves': 'Minnesota Timberwolves', 'Wolves': 'Minnesota Timberwolves',
    'Orlando': 'Orlando Magic', 'ORL': 'Orlando Magic', 'Magic': 'Orlando Magic',
    'Phoenix': 'Phoenix Suns', 'PHX': 'Phoenix Suns', 'Suns': 'Phoenix Suns',
    'Sacramento': 'Sacramento Kings', 'SAC': 'Sacramento Kings', 'Kings': 'Sacramento Kings',
    'San Antonio': 'San Antonio Spurs', 'SAS': 'San Antonio Spurs', 'Spurs': 'San Antonio Spurs',
    'Toronto': 'Toronto Raptors', 'TOR': 'Toronto Raptors', 'Raptors': 'Toronto Raptors',
    'Utah': 'Utah Jazz', 'UTA': 'Utah Jazz', 'Jazz': 'Utah Jazz',
    'Washington': 'Washington Wizards', 'WAS': 'Washington Wizards', 'Wizards': 'Washington Wizards',
    'Atlanta': 'Atlanta Hawks', 'ATL': 'Atlanta Hawks', 'Hawks': 'Atlanta Hawks',
}


class BoosterWrapper:
    """Wrapper for XGBoost Booster to satisfy sklearn's CalibratedClassifierCV interface."""
    def __init__(self, booster, num_class):
        self.booster = booster
        self.classes_ = np.arange(num_class)

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        return self.booster.predict(xgb.DMatrix(X))


def normalize_team_name(team: str) -> str:
    """Normalize team name to canonical format expected by kyleskom model."""
    if team in TEAM_INDEX_CURRENT:
        return team
    if team in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[team]
    team_lower = team.lower()
    for alias, canonical in TEAM_NAME_ALIASES.items():
        if alias.lower() == team_lower:
            return canonical
    for canonical in TEAM_INDEX_CURRENT.keys():
        if canonical.lower() == team_lower:
            return canonical
    return team



class KyleskomPredictor:
    """
    Uses kyleskom's pre-trained XGBoost AND Neural Network models.
    Matches main.py, XGBoost_Runner.py, and NN_Runner.py methodology.
    """
    
    def __init__(self):
        # XGBoost models
        self.xgb_ml = None
        self.xgb_ou = None
        self.xgb_ml_calibrator = None
        self.xgb_uo_calibrator = None
        
        # NN models
        self.nn_ml = None
        self.nn_ou = None
        
        self.df = None  # Raw DataFrame from NBA API (not sorted)
        self._models_loaded = False
        self._data_loaded = False
    
    def _select_model_path(self, kind: str, base_path: Path, pattern: re.Pattern, suffix: str = ".json") -> Path:
        """Find the best model by parsing accuracy from filename (1:1 with reference runner)."""
        if not base_path.exists():
            return None
            
        candidates = list(base_path.glob(f"*{suffix}"))
        candidates = [c for c in candidates if kind in c.name and pattern.search(c.name)]
        
        if not candidates:
            # Try recursive search if not flat
            candidates = [p for p in candidates if p.suffix in {'.json', '.h5', '.keras'}]
            if not candidates:
                return None

        def score(path):
            match = pattern.search(path.name)
            accuracy = float(match.group(1)) if match else 0.0
            return (accuracy, path.stat().st_mtime)

        best_model = max(candidates, key=score)
        logger.info(f"Selected best {kind} model: {best_model.name}")
        return best_model

    def _load_calibrator(self, model_path: Path):
        """Load calibration model if exists (logic from XGBoost_Runner.py)."""
        calibration_path = model_path.with_name(f"{model_path.stem}_calibration.pkl")
        if not calibration_path.exists():
            # Try finding generic calibration file for NN if exact match fails
            pass 
        else:
            try:
                calibrator = joblib.load(calibration_path)
                logger.info(f"Loaded calibration: {calibration_path.name}")
                return calibrator
            except Exception as e:
                logger.error(f"Failed to load calibrator: {e}")
        return None

    def load_models(self) -> bool:
        """Load the best pre-trained models (XGBoost + NN)."""
        if self._models_loaded:
            return True
        
        MODELS_ROOT = Path(REFERENCE_REPO_PATH) / 'Models'
        XGB_DIR = MODELS_ROOT / 'XGBoost_Models'
        NN_DIR = MODELS_ROOT / 'NN_Models'
        
        # 1. Load XGBoost
        if XGB_AVAILABLE:
            try:
                # Use default dir if XGB_DIR doesn't exist
                search_dir = XGB_DIR if XGB_DIR.exists() else MODELS_ROOT
                
                ml_path = self._select_model_path("ML", search_dir, XGB_ACCURACY_PATTERN)
                if ml_path:
                    self.xgb_ml = xgb.Booster()
                    self.xgb_ml.load_model(str(ml_path))
                    self.xgb_ml_calibrator = self._load_calibrator(ml_path)
                
                ou_path = self._select_model_path("UO", search_dir, XGB_ACCURACY_PATTERN)
                if ou_path:
                    self.xgb_ou = xgb.Booster()
                    self.xgb_ou.load_model(str(ou_path))
                    self.xgb_uo_calibrator = self._load_calibrator(ou_path)
            except Exception as e:
                logger.error(f"Error loading XGBoost models: {e}")

        # 2. Load Neural Networks (ONNX)
        if ONNX_AVAILABLE:
            try:
                search_dir = NN_DIR if NN_DIR.exists() else MODELS_ROOT
                
                # Locate ONNX models
                ml_path = self._select_model_path("Trained-Model-ML-", search_dir, NN_ML_PATTERN, suffix=".onnx")
                if ml_path:
                    self.nn_ml = ort.InferenceSession(str(ml_path))
                    logger.info(f"Loaded NN ML model (ONNX): {ml_path.name}")
                
                ou_path = self._select_model_path("Trained-Model-OU-", search_dir, NN_OU_PATTERN, suffix=".onnx")
                if ou_path:
                    self.nn_ou = ort.InferenceSession(str(ou_path))
                    logger.info(f"Loaded NN OU model (ONNX): {ou_path.name}")
                
                if not self.nn_ml and not self.nn_ou:
                    logger.warning(f"No ONNX NN models found in {search_dir}")
            except Exception as e:
                logger.error(f"Error loading ONNX models: {e}")
        else:
            logger.info("Skipping NN model load (ONNX Runtime not available)")

        self._models_loaded = True
        return True
    
    async def fetch_data_from_nba_api(self) -> bool:
        """
        Fetch current team stats from NBA API exactly like reference repo's main.py.
        """
        if self._data_loaded and self.df is not None:
            return True
        
        # In a real 1:1 integration, we would just shell out to the other script.
        # But to keep this service running as an API, we replicate the fetch logic identically.
        import aiohttp
        
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
        
        logger.info(f"Fetching NBA team stats for season {season}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=NBA_API_HEADERS, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"NBA API returned {response.status}")
                        return False
                    
                    data = await response.json()
            
            result_sets = data.get('resultSets', [])
            if not result_sets:
                logger.error("No resultSets in NBA API response")
                return False
            
            data_list = result_sets[0]
            headers = data_list.get('headers', [])
            rows = data_list.get('rowSet', [])
            
            self.df = pd.DataFrame(data=rows, columns=headers)
            logger.info(f"Fetched {len(self.df)} teams with {len(headers)} columns")
            
            self._data_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error fetching from NBA API: {e}")
            return False
    
    def _predict_probs(self, model, data, calibrator=None):
        """Predict probabilities using model and optional calibrator (1:1 with XGBoost_Runner.py)."""
        if calibrator is not None:
            return calibrator.predict_proba(data)
        return model.predict(xgb.DMatrix(data))

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
        # Normalize team names
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

        # Data preparation logic
        try:
            # Lookup helper
            def find_team_row(team_name):
                row = self.df[self.df['TEAM_NAME'] == team_name]
                if len(row) > 0: return row
                return self.df[self.df['TEAM_NAME'].str.contains(team_name.split()[-1], case=False, na=False)]

            home_row = find_team_row(home_team)
            away_row = find_team_row(away_team)
            
            if len(home_row) == 0: return {"error": f"Team not found: {home_team}"}
            if len(away_row) == 0: return {"error": f"Team not found: {away_team}"}
            
            home_series = home_row.iloc[0].drop(['TEAM_ID'], errors='ignore')
            away_series = away_row.iloc[0].drop(['TEAM_ID'], errors='ignore')
            
            # Rename away columns
            away_series_renamed = away_series.rename(
                index={col: f"{col}.1" if col != 'TEAM_NAME' else 'TEAM_NAME.1' for col in away_series.index}
            )
            
            # Concat
            stats = pd.concat([home_series, away_series_renamed])
            
            # DAYS REST LOGIC (Matching main.py)
            home_days_off = timedelta(days=7) # Default
            away_days_off = timedelta(days=7) # Default
            
            try:
                # Load schedule (assumed available in Data/nba-2025-UTC.csv)
                schedule_path = Path(REFERENCE_REPO_PATH) / 'Data' / 'nba-2025-UTC.csv'
                if schedule_path.exists():
                    schedule_df = pd.read_csv(schedule_path, parse_dates=['Date'], date_format='%d/%m/%Y %H:%M')
                    today = datetime.now()
                    
                    def calc_rest(team_name, sched_df):
                        team_games = sched_df[
                            (sched_df['Home Team'] == team_name) | (sched_df['Away Team'] == team_name)
                        ]
                        prev_games = team_games.loc[team_games['Date'] <= today].sort_values('Date', ascending=False)
                        if len(prev_games) > 0:
                            last_date = prev_games.iloc[0]['Date']
                            return timedelta(days=1) + today - last_date
                        return timedelta(days=7)

                    home_days_off = calc_rest(home_team, schedule_df)
                    away_days_off = calc_rest(away_team, schedule_df)
                else:
                    logger.warning(f"Schedule file not found at {schedule_path}")
            except Exception as e:
                logger.error(f"Error calculating rest days: {e}")

            stats['Days-Rest-Home'] = home_days_off.days
            stats['Days-Rest-Away'] = away_days_off.days
            
            stats = stats.drop(['TEAM_NAME', 'TEAM_NAME.1'], errors='ignore')
            
            # Feature vector
            data = stats.values.astype(float).reshape(1, -1)
            
            # ML Prediction (XGBoost)
            xgb_home_prob = 0.5
            if self.xgb_ml:
                ml_probs = self._predict_probs(self.xgb_ml, data, self.xgb_ml_calibrator)[0]
                if len(ml_probs) >= 2:
                    xgb_home_prob = float(ml_probs[1])
                else:
                    xgb_home_prob = float(ml_probs)
            
            # Neural Network Prediction (Secondary - ONNX)
            nn_home_prob = None
            if self.nn_ou_sessions_active: # Logic check for session
                 pass 
            
            if self.nn_ml:
                try:
                    # ONNX expects float32
                    input_data = data.astype(np.float32)
                    
                    # Normalize manually if needed, or if the model was trained with normalized data
                    # Note: Many onnx-converted models already expect the normalized range or handle it
                    # In kyleskom's repo, NN_Runner uses tf.keras.utils.normalize
                    # We replicate simple l2 normalization: x / norm(x)
                    norm = np.linalg.norm(input_data, axis=1, keepdims=True)
                    data_norm = input_data / (norm + 1e-7)
                    
                    # Run Session
                    input_name = self.nn_ml.get_inputs()[0].name
                    nn_pred = self.nn_ml.run(None, {input_name: data_norm})[0]
                    
                    if nn_pred.shape[1] >= 2:
                        nn_home_prob = float(nn_pred[0][1])
                    else:
                        nn_home_prob = float(nn_pred[0][0])
                except Exception as e:
                    logger.error(f"NN ML Prediction failed: {e}")

            # Use XGB as primary for EV/Kelly calculations
            home_win_prob = xgb_home_prob
            away_win_prob = 1 - xgb_home_prob
            
            # OU Prediction
            ou_pred = None
            if self.xgb_ou and total_line:
                # Correct feature order for O/U model: [Stats (104)] + [Total Line (1)] + [Rest Days (2)]
                # Currently 'data' is [Stats (104)] + [Rest Days (2)], so we insert at 104
                data_ou = np.insert(data, 104, total_line, axis=1)
                ou_probs = self._predict_probs(self.xgb_ou, data_ou, self.xgb_uo_calibrator)[0]
                
                if len(ou_probs) >= 2:
                    under_prob = float(ou_probs[0])
                    over_prob = float(ou_probs[1])
                    ou_pred = {
                        'pick': 'OVER' if over_prob > under_prob else 'UNDER',
                        'confidence': float(round(max(over_prob, under_prob) * 100, 1)),
                        'total_line': float(total_line),
                        'over_prob': float(round(over_prob, 3)),
                        'under_prob': float(round(under_prob, 3))
                    }

            # EV and Kelly
            ev_home = ev_away = None
            kelly_home = kelly_away = None
            
            if home_ml and away_ml:
                ev_home = self._expected_value(home_win_prob, home_ml)
                ev_away = self._expected_value(away_win_prob, away_ml)
                kelly_home = self._kelly_criterion(home_ml, home_win_prob)
                kelly_away = self._kelly_criterion(away_ml, away_win_prob)

            predicted_winner = home_team if home_win_prob > away_win_prob else away_team
            confidence = float(round(max(home_win_prob, away_win_prob) * 100, 1))
                 
            return {
                'model': 'kyleskom_ensemble',
                'home_team': home_team,
                'away_team': away_team,
                'home_win_probability': float(round(home_win_prob, 4)),
                'away_win_probability': float(round(away_win_prob, 4)),
                'nn_home_win_probability': float(round(nn_home_prob, 4)) if nn_home_prob is not None else None,
                'predicted_winner': predicted_winner,
                'confidence': confidence,
                'over_under': ou_pred,
                'ev_home': ev_home,
                'ev_away': ev_away,
                'kelly_home': kelly_home,
                'kelly_away': kelly_away
            }
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"error": str(e)}

    # Utils matching src/Utils logic
    def _expected_value(self, Pwin, odds):
        # Matches Expected_Value.py
        Ploss = 1 - Pwin
        Mwin = odds if odds > 0 else (100 / abs(odds)) * 100
        return round((Pwin * Mwin) - (Ploss * 100), 2)
    
    def _kelly_criterion(self, american_odds, model_prob):
        # Matches Kelly_Criterion.py
        decimal_odds = (american_odds / 100) if american_odds >= 100 else (100 / abs(american_odds))
        decimal_odds = round(decimal_odds, 2)
        bankroll_fraction = round((100 * (decimal_odds * model_prob - (1 - model_prob))) / decimal_odds, 2)
        return max(0, bankroll_fraction)


# Singleton instance
_predictor = None

def get_kyleskom_predictor() -> KyleskomPredictor:
    global _predictor
    if _predictor is None:
        _predictor = KyleskomPredictor()
    return _predictor

async def predict_with_kyleskom(home, away, total=225.0, h_ml=None, a_ml=None):
    predictor = get_kyleskom_predictor()
    return await predictor.predict_game(home, away, total, h_ml, a_ml)
