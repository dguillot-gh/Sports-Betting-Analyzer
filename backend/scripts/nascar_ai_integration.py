
import logging
import math
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import joblib

logger = logging.getLogger(__name__)

# Model paths
MODEL_DIR = Path(__file__).parent.parent.parent / "models" / "nascar" / "csv"
CLF_MODEL_PATH = MODEL_DIR / "classification_model.joblib"
REG_MODEL_PATH = MODEL_DIR / "regression_model.joblib"

# Global cache for models
_models = {
    "classification": None,
    "regression": None
}

def _load_models():
    """Lazy load models."""
    global _models
    if _models["classification"] is None and CLF_MODEL_PATH.exists():
        try:
            _models["classification"] = joblib.load(CLF_MODEL_PATH)
            logger.info(f"Loaded NASCAR classification model from {CLF_MODEL_PATH}")
        except Exception as e:
            logger.error(f"Failed to load NASCAR classification model: {e}")

    if _models["regression"] is None and REG_MODEL_PATH.exists():
        try:
            _models["regression"] = joblib.load(REG_MODEL_PATH)
            logger.info(f"Loaded NASCAR regression model from {REG_MODEL_PATH}")
        except Exception as e:
            logger.error(f"Failed to load NASCAR regression model: {e}")

def get_nascar_ai_predictions(
    driver_name: str,
    track_name: str,
    driver_stats: Dict[str, Any],
    track_type: str = "Intermediate"
) -> Dict[str, Any]:
    """
    NASCAR multi-engine prediction logic for a single driver.
    Uses trained XGBoost models if available, falling back to heuristics.
    """
    # Ensure models are loaded
    _load_models()
    
    engines = {}
    
    # helper for safe float conversion
    def val(key, default=0.0):
        return float(driver_stats.get(key, default))
        
    def sval(key, default="Unknown"):
        return str(driver_stats.get(key, default))

    # --- Feature Vector Preparation ---
    # Must match the EXACT columns used during training (nascar_config.yaml)
    features = {
        # Categorical
        'driver': driver_name,
        'track': track_name,
        'track_type': track_type,
        'manu': sval('manufacturer', 'Unknown'),
        'team_name': sval('team', 'Unknown'),
        'status': 'Running', # Assumption for pre-race prediction
        
        # Numeric - Core
        'year': datetime.now().year,
        'race_num': 1, # Placeholder
        'start': val('avg_start', 20),
        'car_num': 0, # Placeholder
        'laps': 200, # Placeholder
        'laps_led': val('avg_laps_led', 0),
        'stage_1': 0, # Placeholder
        'stage_2': 0, # Placeholder
        'stage_points': val('stage_points', 0),
        
        # Numeric - Enhanced
        'pole_position': 1 if val('avg_start') <= 1.5 else 0,
        'qualified_top5': 1 if val('avg_start') <= 5.5 else 0,
        'qualified_top10': 1 if val('avg_start') <= 10.5 else 0,
        'is_road_course': 1 if 'road' in track_type.lower() else 0,
        'is_superspeedway': 1 if 'super' in track_type.lower() else 0,
        'is_short_track': 1 if 'short' in track_type.lower() else 0,
        'career_races': val('career_races', 100),
        'career_wins': val('career_wins', 5),
        'career_win_pct': val('career_win_pct', 0.05),
        'career_top5': val('career_top5', 20),
        'career_top10': val('career_top10', 40),
        'career_avg_finish': val('career_avg_finish', 18),
        'races_at_track': val('races_at_track', 5),
        'wins_at_track': val('wins_at_track', 0),
        'avg_finish_at_track': val(f'avg_finish_{track_type.lower()}', 18),
        'best_finish_at_track': val('best_finish_at_track', 5),
        'avg_finish_last_3': val('recent_avg_finish', 15),
        'avg_finish_last_5': val('recent_avg_finish', 15),
        'avg_finish_last_10': val('recent_avg_finish', 15),
        'team_wins_this_season': 0,
        'team_top5_this_season': 0,
        'team_avg_finish_this_season': 15,
        'manu_wins_this_season': 0,
        'manu_win_pct_this_season': 0,
        
        # Numeric - Scraped
        'scraped_avg_speed_rank': val('avg_speed_rank', 20),
        'scraped_avg_finish': val('recent_avg_finish', 15),
        'scraped_best_finish': 5,
        'scraped_races_count': 5,
        'track_specific_speed': val('avg_speed_rank', 20),
        'track_specific_finish': val(f'avg_finish_{track_type.lower()}', 18),
        'track_experience': val('races_at_track', 5)
    }
    
    # Convert to DataFrame for prediction
    df = pd.DataFrame([features])
    
    # --- 1. XGBoost Classification (Win Probability) ---
    if _models["classification"]:
        try:
            # Predict probability of class 1 (Win)
            win_prob = _models["classification"].predict_proba(df)[0][1]
            engines["XGBoostClassifier"] = {
                "predicted_finish": 1.0, # Placeholder
                "win_prob": round(float(win_prob), 4),
                "confidence": "High"
            }
        except Exception as e:
            logger.warning(f"NASCAR classification prediction failed: {e}")

    # --- 2. XGBoost Regression (Projected Finish) ---
    if _models["regression"]:
        try:
            pred_finish = _models["regression"].predict(df)[0]
            # Infer win prob from finish position (heuristic fallback for regression)
            implied_prob = max(0.001, 1 - (pred_finish / 40)) * 0.1
            
            engines["XGBoostRegressor"] = {
                "predicted_finish": round(float(pred_finish), 1),
                "win_prob": round(implied_prob, 3),
                "confidence": "High"
            }
        except Exception as e:
            logger.warning(f"NASCAR regression prediction failed: {e}")

    # --- 3. Fallback Heuristics (if models failed or missing) ---
    
    if not engines:
        # Baseline
        avg_fin = val(f"avg_finish_{track_type.lower()}", 18)
        base_score = 1 - (avg_fin / 40)
        
        engines["TrackBaseline"] = {
            "predicted_finish": round(avg_fin, 1),
            "win_prob": round(base_score * 0.1, 3)
        }
        
        # Momentum
        recent = val("recent_avg_finish", 15)
        rating = val("avg_driver_rating", 85)
        
        lin_score = base_score + (rating - 85) * 0.005
        
        engines["RatingLinear"] = {
            "predicted_finish": round(avg_fin * 0.7 + recent * 0.3, 1),
            "win_prob": round(max(0, lin_score * 0.12), 3)
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "driver": driver_name,
        "track": track_name,
        "engines": engines,
        "features_used": features
    }
