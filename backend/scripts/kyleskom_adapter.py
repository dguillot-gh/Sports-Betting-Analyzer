"""
Kyleskom NBA ML Adapter - Final Production Version
Bridges the reference kyleskom/NBA-Machine-Learning-Sports-Betting repo
with our Model Testing pages.

Uses their pre-trained XGBoost models (68.9% ML accuracy) and data pipeline.
"""

import logging
import os
import re
import sys
import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Path to the cloned reference repo
REFERENCE_REPO_PATH = os.path.join(os.path.dirname(__file__), 'nba_ml_reference')

# Regex for model accuracy parsing
XGB_ACCURACY_PATTERN = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")
NN_ML_PATTERN = re.compile(r"Trained-Model-ML-(\d+(?:\.\d+)?)")
NN_OU_PATTERN = re.compile(r"Trained-Model-OU-(\d+(?:\.\d+)?)")

# --- BoosterWrapper Fix for Joblib/Pickle ---
class BoosterWrapper:
    """Wrapper for XGBoost Booster to satisfy sklearn's CalibratedClassifierCV interface."""
    def __init__(self, booster, num_class):
        self.booster = booster
        self.classes_ = np.arange(num_class)
    def fit(self, X, y): return self
    def predict_proba(self, X):
        import xgboost as xgb
        return self.booster.predict(xgb.DMatrix(X))

# Handle the case where joblib expects BoosterWrapper in __main__ (uvicorn)
try:
    import __main__
    if not hasattr(__main__, 'BoosterWrapper'):
        __main__.BoosterWrapper = BoosterWrapper
except Exception:
    pass

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
except ImportError:
    ONNX_AVAILABLE = False
    logger.warning("ONNX Runtime not available")

# Headers for NBA API
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Team name mapping
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

TEAM_NAME_ALIASES = {
    'LA Clippers': 'Los Angeles Clippers', 'LA Lakers': 'Los Angeles Lakers',
    'LAC': 'Los Angeles Clippers', 'LAL': 'Los Angeles Lakers',
    'GS Warriors': 'Golden State Warriors', 'GSW': 'Golden State Warriors',
    'NY Knicks': 'New York Knicks', 'OKC Thunder': 'Oklahoma City Thunder',
    'NOLA Pelicans': 'New Orleans Pelicans', 'Trail Blazers': 'Portland Trail Blazers',
}

def normalize_team_name(team: str) -> str:
    if team in TEAM_INDEX_CURRENT: return team
    if team in TEAM_NAME_ALIASES: return TEAM_NAME_ALIASES[team]
    team_lower = team.lower()
    for alias, canonical in TEAM_NAME_ALIASES.items():
        if alias.lower() == team_lower: return canonical
    for canonical in TEAM_INDEX_CURRENT.keys():
        if canonical.lower() in team_lower or team_lower in canonical.lower(): return canonical
    return team

class KyleskomPredictor:
    def __init__(self):
        self.xgb_ml = None
        self.xgb_ou = None
        self.xgb_ml_calibrator = None
        self.xgb_ou_calibrator = None
        self.nn_ml = None
        self.nn_ou = None
        self.df = None
        self._models_loaded = False
        self._data_loaded = False

    def _select_model_path(self, kind: str, base_path: Path, pattern: re.Pattern, suffix: str = ".json") -> Optional[Path]:
        if not base_path.exists(): return None
        candidates = list(base_path.glob(f"*{suffix}"))
        if not candidates: candidates = list(base_path.glob(f"**/*{suffix}"))
        candidates = [c for c in candidates if kind in c.name and pattern.search(c.name)]
        if not candidates: return None
        def score(path):
            match = pattern.search(path.name)
            return (float(match.group(1)) if match else 0.0, path.stat().st_mtime)
        return max(candidates, key=score)

    def _load_calibrator(self, model_path: Path):
        calibration_path = model_path.with_name(f"{model_path.stem}_calibration.pkl")
        if calibration_path.exists():
            try:
                calibrator = joblib.load(calibration_path)
                logger.info(f"Loaded calibration: {calibration_path.name}")
                return calibrator
            except Exception as e:
                logger.error(f"Failed to load calibrator: {e}")
        return None

    def load_models(self) -> bool:
        if self._models_loaded: return True
        MODELS_ROOT = Path(REFERENCE_REPO_PATH) / 'Models'
        XGB_DIR = MODELS_ROOT / 'XGBoost_Models'
        NN_DIR = MODELS_ROOT / 'NN_Models'
        
        if XGB_AVAILABLE:
            try:
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
                    self.xgb_ou_calibrator = self._load_calibrator(ou_path)
            except Exception as e:
                logger.error(f"Error loading XGBoost: {e}")

        if ONNX_AVAILABLE:
            try:
                search_dir = NN_DIR if NN_DIR.exists() else MODELS_ROOT
                ml_path = self._select_model_path("Trained-Model-ML-", search_dir, NN_ML_PATTERN, suffix=".onnx")
                if ml_path: self.nn_ml = ort.InferenceSession(str(ml_path))
                ou_path = self._select_model_path("Trained-Model-OU-", search_dir, NN_OU_PATTERN, suffix=".onnx")
                if ou_path: self.nn_ou = ort.InferenceSession(str(ou_path))
            except Exception as e:
                logger.error(f"Error loading ONNX: {e}")

        self._models_loaded = True
        return True

    def _predict_probs(self, model, data, calibrator=None):
        if calibrator:
            return calibrator.predict_proba(data)
        return model.predict(xgb.DMatrix(data))

    async def fetch_data_from_nba_api(self) -> bool:
        if self._data_loaded and self.df is not None: return True
        import aiohttp
        now = datetime.now()
        season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
        url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=NBA_API_HEADERS, timeout=30) as response:
                    if response.status != 200: 
                        logger.warning(f"NBA API Fetch returned HTTP {response.status}")
                        return False
                    data = await response.json()
            
            result_sets = data.get('resultSets', [])
            if not result_sets: return False
            
            rows = result_sets[0]['rowSet']
            headers = result_sets[0]['headers']
            self.df = pd.DataFrame(data=rows, columns=headers)
            self._data_loaded = True
            return True
        except Exception as e:
            logger.error(f"NBA API Fetch error: {e}")
            logger.error(traceback.format_exc())
            return False

    async def predict_game(self, home_team: str, away_team: str, total_line: float = 225.0, home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
        home_team, away_team = normalize_team_name(home_team), normalize_team_name(away_team)
        
        # Load models
        if not self._models_loaded: self.load_models()
        
        # Fetch data
        if not self._data_loaded: await self.fetch_data_from_nba_api()

        # If still no data, we cannot proceed with this specific model
        if self.df is None:
            logger.warning(f"Returning error for {home_team} vs {away_team}: No team stats available (API failed)")
            return {"error": "Could not fetch current NBA team stats for kyleskom models."}

        try:
            def find_row(name):
                r = self.df[self.df['TEAM_NAME'] == name]
                if len(r) > 0: return r
                # Fallback to suffix match
                return self.df[self.df['TEAM_NAME'].str.contains(name.split()[-1], case=False, na=False)]

            h_row, a_row = find_row(home_team), find_row(away_team)
            if len(h_row) == 0 or len(a_row) == 0: 
                return {"error": f"Stats missing for {home_team} or {away_team}"}

            h_stats = h_row.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'], errors='ignore')
            a_stats = a_row.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'], errors='ignore').rename(lambda x: f"{x}.1")
            stats = pd.concat([h_stats, a_stats])
            
            # Rest days (simplified default)
            stats['Days-Rest-Home'], stats['Days-Rest-Away'] = 2.0, 2.0
            data = stats.values.astype(float).reshape(1, -1)
            
            # XGB Prediction
            xgb_home_prob = 0.5
            if self.xgb_ml:
                res = self._predict_probs(self.xgb_ml, data, self.xgb_ml_calibrator)[0]
                xgb_home_prob = float(res[1]) if len(res) >= 2 else float(res)

            # NN Prediction (ONNX)
            nn_home_prob = None
            if self.nn_ml:
                try:
                    input_data = data.astype(np.float32)
                    norm = np.linalg.norm(input_data, axis=1, keepdims=True)
                    data_norm = input_data / (norm + 1e-7)
                    input_name = self.nn_ml.get_inputs()[0].name
                    nn_res = self.nn_ml.run(None, {input_name: data_norm})[0]
                    nn_home_prob = float(nn_res[0][1]) if nn_res.shape[1] >= 2 else float(nn_res[0][0])
                except Exception as e:
                    logger.error(f"NN ML Prediction failed: {e}")

            # O/U Prediction
            ou_pred = None
            if self.xgb_ou and total_line:
                # Inject total_line after internal stats (104 columns in kyleskom model)
                data_ou = np.insert(data, 104, total_line, axis=1)
                ou_res = self._predict_probs(self.xgb_ou, data_ou, self.xgb_ou_calibrator)[0]
                if len(ou_res) >= 2:
                    ou_pred = {
                        'pick': 'OVER' if ou_res[1] > ou_res[0] else 'UNDER',
                        'confidence': float(round(max(ou_res) * 100, 1)),
                        'total_line': float(total_line),
                        'over_prob': float(round(ou_res[1], 3)),
                        'under_prob': float(round(ou_res[0], 3))
                    }

            home_win_prob = xgb_home_prob
            away_win_prob = 1 - home_win_prob
            
            return {
                'model': 'kyleskom_ensemble',
                'home_team': home_team, 'away_team': away_team,
                'home_win_probability': float(round(home_win_prob, 4)),
                'away_win_probability': float(round(away_win_prob, 4)),
                'nn_home_win_probability': float(round(nn_home_prob, 4)) if nn_home_prob is not None else None,
                'predicted_winner': home_team if home_win_prob > 0.5 else away_team,
                'confidence': float(round(max(home_win_prob, away_win_prob) * 100, 1)),
                'over_under': ou_pred,
                'ev_home': self._expected_value(home_win_prob, home_ml) if home_ml else None,
                'ev_away': self._expected_value(away_win_prob, away_ml) if away_ml else None,
                'kelly_home': self._kelly_criterion(home_ml, home_win_prob) if home_ml else None
            }
        except Exception as e:
            logger.error(f"Kyleskom Prediction Crash for {home_team} vs {away_team}: {e}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}

    def _expected_value(self, Pwin, odds):
        Mwin = odds if odds > 0 else (100 / abs(odds)) * 100
        return round((Pwin * Mwin) - ((1 - Pwin) * 100), 2)
    def _kelly_criterion(self, odds, prob):
        b = (odds / 100) if odds >= 100 else (100 / abs(odds))
        return max(0, round((100 * (b * prob - (1 - prob))) / b, 2))

_predictor = None
def get_kyleskom_predictor() -> KyleskomPredictor:
    global _predictor
    if _predictor is None: _predictor = KyleskomPredictor()
    return _predictor

async def predict_with_kyleskom(home, away, total=225.0, h_ml=None, a_ml=None):
    return await get_kyleskom_predictor().predict_game(home, away, total, h_ml, a_ml)
