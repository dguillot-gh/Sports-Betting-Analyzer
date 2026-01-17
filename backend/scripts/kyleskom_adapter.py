"""
Kyleskom NBA ML Adapter - Final Production Version
Bridges the reference kyleskom/NBA-Machine-Learning-Sports-Betting repo
with our Model Testing pages.

Uses their pre-trained XGBoost models (68.9% ML accuracy) and data pipeline.
"""

import logging
import os
import re
import asyncio
import sys
import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
import aiohttp
import warnings
import xgboost as xgb

logger = logging.getLogger(__name__)

# For Sklearn compatibility (needed for tags in 1.6+)
try:
    from sklearn.base import BaseEstimator, ClassifierMixin
    SKLEARN_BASE_AVAILABLE = True
except ImportError:
    SKLEARN_BASE_AVAILABLE = False

# Path to the cloned reference repo
REFERENCE_REPO_PATH = os.path.join(os.path.dirname(__file__), 'nba_ml_reference')

# Regex for model accuracy parsing
XGB_ACCURACY_PATTERN = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")
NN_ML_PATTERN = re.compile(r"Trained-Model-ML-(\d+(?:\.\d+)?)")
NN_OU_PATTERN = re.compile(r"Trained-Model-OU-(\d+(?:\.\d+)?)")

# --- BoosterWrapper Fix for Joblib/Pickle & Sklearn 1.6+ ---
base_classes = (BaseEstimator, ClassifierMixin) if SKLEARN_BASE_AVAILABLE else (object,)

class BoosterWrapper(*base_classes):
    """
    Wrapper for XGBoost Booster to satisfy sklearn's CalibratedClassifierCV interface.
    Explicitly set as classifier for Sklearn 1.6+ compatibility.
    """
    _estimator_type = "classifier"

    def __init__(self, booster=None, num_class=2):
        self.booster = booster
        self.num_class = num_class
        try:
            self.classes_ = np.arange(num_class)
        except Exception:
            self.classes_ = np.array([0, 1])
        
    def fit(self, X, y): 
        # Already fitted model
        return self
        
    def predict_proba(self, X):
        import xgboost as xgb
        # Ensure we use DMatrix for booster
        dmat = xgb.DMatrix(X)
        return self.booster.predict(dmat)
    
    # Sklearn boilerplate for parameters
    def get_params(self, deep=True):
        return {"booster": self.booster, "num_class": self.num_class}
    
    def set_params(self, **parameters):
        for parameter, value in parameters.items():
            setattr(self, parameter, value)
        if hasattr(self, 'num_class'):
            self.classes_ = np.arange(self.num_class)
        return self

    def __sklearn_tags__(self):
        """Standardize tags for Sklearn 1.6+ to ensure it's seen as a classifier."""
        return SimpleNamespace(
            estimator_type="classifier",
            classifier_tags=SimpleNamespace(pos_label=None),
            regressor_tags=None,
            transformer_tags=None,
            target_tags=SimpleNamespace(single_output=True, required=False),
            input_tags=SimpleNamespace(
                two_d_array=True, one_d_array=False, three_d_array=False,
                sparse=False, categorical=False, string=False, dict=False,
                pairwise=False, allow_nan=False, positive_only=False
            ),
            array_api_support=False,
            no_validation=False,
            non_deterministic=False,
            requires_fit=True,
            _skip_test=False
        )

# Handle the case where joblib expects BoosterWrapper in __main__ (uvicorn)
try:
    import __main__
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
        self._lock = asyncio.Lock()

    def _select_model_path(self, kind: str, base_path: Path, pattern: re.Pattern, suffix: str = ".json") -> Optional[Path]:
        if not base_path.exists(): return None
        candidates = list(base_path.glob(f"*{suffix}"))
        if not candidates: candidates = list(base_path.glob(f"**/*{suffix}"))
        candidates = [c for c in candidates if kind in c.name and pattern.search(c.name)]
        logger.info(f"Model discovery for '{kind}' in {base_path}: {len(candidates)} candidates found")
        if not candidates: return None
        def score(path):
            match = pattern.search(path.name)
            s = (float(match.group(1)) if match else 0.0, path.stat().st_mtime)
            logger.debug(f"Candidate: {path.name} score: {s}")
            return s
        best = max(candidates, key=score)
        logger.info(f"Selected best model for '{kind}': {best.name}")
        return best

    def _load_calibrator(self, model_path: Path):
        try:
            # Check for _calibration.pkl in the same folder (observed in logs)
            cal_path = model_path.with_name(model_path.stem + "_calibration.pkl")
            if not cal_path.exists():
                # Fallback to sibling "Calibrators" folder with .joblib (original logic)
                cal_dir = model_path.parent.parent / "Calibrators"
                cal_path = cal_dir / (model_path.stem + ".joblib")
                
            if cal_path.exists():
                try:
                    with warnings.catch_warnings(record=True) as w:
                        warnings.simplefilter("always")
                        calibrator = joblib.load(cal_path)
                        for row in w:
                            if "InconsistentVersionWarning" in str(row.message):
                                logger.warning(f"Calibration version mismatch detected for {cal_path.name}. Falling back to raw probabilities.")
                                return None
                    logger.info(f"Loaded calibration: {cal_path.name}")
                    return calibrator
                except Exception as e:
                    logger.warning(f"Error loading calibrator {cal_path.name}: {e}")
                    return None
            return None
        except Exception as e:
            logger.error(f"Failed to load calibrator: {e}")
            return None

    def load_models(self) -> bool:
        if self._models_loaded: return True
        
        if not os.path.exists(REFERENCE_REPO_PATH):
            logger.error(f"Reference repo not found at {REFERENCE_REPO_PATH}")
            self._models_loaded = True # Don't retry every time
            return False
            
        MODELS_ROOT = Path(REFERENCE_REPO_PATH) / 'Models'
        XGB_DIR = MODELS_ROOT / 'XGBoost_Models'
        NN_DIR = MODELS_ROOT / 'NN_Models'
        
        logger.info(f"Loading Kyleskom models from {MODELS_ROOT}")
        logger.info(f"ONNX Status: {'Available' if ONNX_AVAILABLE else 'NOT AVAILABLE'}")
        
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
                if ml_path:
                    logger.info(f"Loading NN ML: {ml_path.name}")
                    self.nn_ml = ort.InferenceSession(str(ml_path))
                else:
                    logger.warning("NN ML model not found (.onnx)")

                ou_path = self._select_model_path("Trained-Model-OU-", search_dir, NN_OU_PATTERN, suffix=".onnx")
                if ou_path:
                    logger.info(f"Loading NN OU: {ou_path.name}")
                    self.nn_ou = ort.InferenceSession(str(ou_path))
                else:
                    logger.warning("NN OU model not found (.onnx)")
            except Exception as e:
                logger.error(f"Error loading ONNX: {e}")
        else:
            logger.warning("ONNX Runtime NOT available - NN models skipped")

        self._models_loaded = True
        return True

    def _predict_probs(self, model, data, calibrator=None):
        if calibrator:
            try:
                probs = calibrator.predict_proba(data)
                # Check if calibrator returned nan or zeros (common on mismatch)
                if np.isnan(probs).any() or np.all(probs == 0):
                    logger.warning("Calibrator returned invalid values. Falling back to raw probabilities.")
                else:
                    return probs
            except Exception as e:
                logger.warning(f"Calibration prediction failed ({e}). Falling back to raw.")
        
        # Fallback to raw Booster probabilities
        return model.predict(xgb.DMatrix(data))

    async def fetch_data_from_nba_api(self, retry_count=2) -> bool:
        async with self._lock:
            if self.df is not None: return True
            try:
                from scripts.nba_cache import get_nba_df
                cached_df = get_nba_df()
                if cached_df is not None:
                    self.df = cached_df
                    self._data_loaded = True
                    logger.info("Kyleskom adapter using shared NBA data cache")
                    return True
            except Exception as e:
                logger.warning(f"Error checking shared cache: {e}")

            if self._data_loaded: return True 
            
            now = datetime.now()
            season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
            url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
            
            logger.info(f"Kyleskom adapter starting direct NBA API fetch for season {season}")
            
            success = False
            for attempt in range(retry_count):
                try:
                    async with aiohttp.ClientSession() as session:
                        timeout = 10 if attempt == 0 else 20
                        async with session.get(url, headers=NBA_API_HEADERS, timeout=timeout) as response:
                            if response.status == 200:
                                data = await response.json()
                                result_sets = data.get('resultSets', [])
                                if result_sets:
                                    rows = result_sets[0]['rowSet']
                                    headers = result_sets[0]['headers']
                                    self.df = pd.DataFrame(data=rows, columns=headers)
                                    from scripts.nba_cache import set_nba_df
                                    set_nba_df(self.df)
                                    success = True
                                    logger.info(f"Kyleskom adapter fetched {len(self.df)} teams")
                                    break
                            else:
                                logger.warning(f"NBA API status {response.status}")
                except Exception as e:
                    logger.error(f"NBA API Fetch error: {e}")
                
                if not success and attempt < retry_count - 1:
                    await asyncio.sleep(1)
            
            self._data_loaded = True 
            return success

    async def predict_game(self, home_team: str, away_team: str, total_line: float = None, home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
        home_team, away_team = normalize_team_name(home_team), normalize_team_name(away_team)
        if not self._models_loaded: self.load_models()
        if self.df is None: await self.fetch_data_from_nba_api()
        if self.df is None: return {"error": "NBA team stats unavailable (API fetch failed)."}

        try:
            def find_row(name):
                r = self.df[self.df['TEAM_NAME'] == name]
                if len(r) > 0: return r
                return self.df[self.df['TEAM_NAME'].str.contains(name.split()[-1], case=False, na=False)]

            h_row, a_row = find_row(home_team), find_row(away_team)
            if len(h_row) == 0 or len(a_row) == 0: return {"error": f"Stats missing for {home_team} or {away_team}"}

            # Ensure exactly 52 stats per team to match training data indices
            # Drop non-stat columns and slice to the standard 52 features (GP through PLUS_MINUS_RANK)
            h_raw = h_row.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'], errors='ignore')
            a_raw = a_row.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'], errors='ignore')
            
            # Slice to exactly 52 to avoid API-added columns like CFID
            h_stats = h_raw.iloc[:52]
            a_stats = a_raw.iloc[:52].rename(lambda x: f"{x}.1")
            
            stats = pd.concat([h_stats, a_stats])
            stats['Days-Rest-Home'], stats['Days-Rest-Away'] = 2.0, 2.0
            data = stats.values.astype(float).reshape(1, -1)
            
            xgb_home_prob = 0.5
            xgb_error = None
            if self.xgb_ml:
                try:
                    res = self._predict_probs(self.xgb_ml, data, self.xgb_ml_calibrator)[0]
                    xgb_home_prob = float(res[1]) if len(res) >= 2 else float(res[0])
                except Exception as e:
                    xgb_error = str(e)
                    logger.error(f"XGB Prediction failed: {e}")

            nn_home_prob = None
            nn_error = None
            if self.nn_ml:
                try:
                    input_data = data.astype(np.float32)
                    norm = np.linalg.norm(input_data, axis=1, keepdims=True)
                    data_norm = input_data / (norm + 1e-7)
                    input_name = self.nn_ml.get_inputs()[0].name
                    nn_res = self.nn_ml.run(None, {input_name: data_norm})[0]
                    nn_home_prob = float(nn_res[0][1]) if nn_res.shape[1] >= 2 else float(nn_res[0][0])
                except Exception as e:
                    nn_error = str(e)
                    logger.error(f"NN Prediction failed: {e}")

            ou_pred = None
            if self.xgb_ou and total_line:
                try:
                    # Realign: The model expects 107 features. 
                    # Training data order: [Stats(104), OU(1), Rest(2)]
                    # Current data has [Stats(104), Rest(2)]. We must insert OU at index 104.
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
                except Exception as e:
                    logger.error(f"O/U Prediction failed: {e}")

            if xgb_error and (nn_error or self.nn_ml is None):
                return {"error": f"ML engines failed: XGB({xgb_error})"}

            home_win_prob = xgb_home_prob
            away_win_prob = 1 - home_win_prob
            
            predicted_winner = home_team if home_win_prob > 0.5 else away_team
            avg_conf = float(round(max(home_win_prob, away_win_prob) * 100, 1))
            home_ev = self._expected_value(home_win_prob, home_ml) if home_ml else None
            away_ev = self._expected_value(away_win_prob, away_ml) if away_ml else None
            home_kelly = self._kelly_criterion(home_ml, home_win_prob) if home_ml else None
            away_kelly = self._kelly_criterion(away_ml, away_win_prob) if away_ml else None
            
            result = {
                'model': 'kyleskom_ensemble',
                'home_team': home_team, 'away_team': away_team,
                'home_win_probability': float(round(home_win_prob, 4)),
                'away_win_probability': float(round(away_win_prob, 4)),
                'nn_home_win_probability': float(round(nn_home_prob, 4)) if nn_home_prob is not None else None,
                'predicted_winner': predicted_winner,
                'confidence': avg_conf,
                'over_under': ou_pred,
                'ev_home': home_ev,
                'ev_away': away_ev,
                'kelly_home': home_kelly,
                'kelly_away': away_kelly,
                'xgb_error': xgb_error, 'nn_error': nn_error
            }
            logger.info(f"NBA Prediction Result: Winner={predicted_winner}, XGB Home={home_win_prob:.1%}")
            return result
        except Exception as e:
            logger.error(f"Kyleskom Orchestration Crash: {e}")
            return {"error": str(e)}

    def _expected_value(self, Pwin: float, odds: int) -> float:
        # Return as fraction (e.g. 0.05 for 5% EV) for frontend "P1" formatting
        Mwin = odds if odds > 0 else (100 / abs(odds)) * 100
        return round(((Pwin * Mwin) - ((1 - Pwin) * 100)) / 100, 4)

    def _kelly_criterion(self, odds: int, prob: float) -> float:
        # Return as fraction (e.g. 0.01 for 1% stake) for frontend "P1" formatting
        b = (odds / 100) if odds >= 100 else (100 / abs(odds))
        raw_kelly = (b * prob - (1 - prob)) / b
        return max(0, round(raw_kelly, 4))

_predictor = None
def get_kyleskom_predictor() -> KyleskomPredictor:
    global _predictor
    if _predictor is None: _predictor = KyleskomPredictor()
    return _predictor

async def predict_with_kyleskom(home, away, total=None, h_ml=None, a_ml=None):
    return await get_kyleskom_predictor().predict_game(home, away, total, h_ml, a_ml)
