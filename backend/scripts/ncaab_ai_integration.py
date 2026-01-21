
import logging
from datetime import datetime
from typing import Dict, Any, List

# Use the established Predictor
try:
    from scripts.ncaab_predictor import NCAABPredictor
except ImportError:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from scripts.ncaab_predictor import NCAABPredictor

logger = logging.getLogger(__name__)

# Global instance for caching
_predictor = None

def get_ncaab_predictor():
    global _predictor
    if _predictor is None:
        _predictor = NCAABPredictor()
    return _predictor

def get_ncaab_ai_predictions(
    home_team: str,
    away_team: str,
    home_stats: Dict[str, Any],
    away_stats: Dict[str, Any]
) -> Dict[str, Any]:
    """
    NCAAB multi-engine prediction logic using the real NCAABPredictor.
    Returns:
       - Heuristic Model (Baseline)
       - XGBoost Model (Advanced)
       - SHAP Explanations
    """
    engines = {}
    
    try:
        predictor = get_ncaab_predictor()
        
        # 1. Run Prediction (Handling data loading internally if needed)
        # Note: predictor expects standardized names. We might need to handle loose matching if coming from unknown source.
        # But usually 'home_team' and 'away_team' from frontend are clean enough or normalized there.
        
        # We pass 0 spread/total just to get the raw probabilities
        pred_result = predictor.predict_game(home_team, away_team)
        
        if "error" in pred_result:
            # Fallback if team not found or data missing
            logger.warning(f"NCAAB Predictor error for {home_team} vs {away_team}: {pred_result['error']}")
            return _fallback_logic(home_team, away_team, home_stats, away_stats)

        # 2. Extract Heuristic Engine
        h_prob_heur = pred_result.get("home_win_probability", 0.5)
        engines["Heuristic (Stats)"] = {
            "home_score": pred_result.get("predicted_score_home", 0),
            "away_score": pred_result.get("predicted_score_away", 0),
            "home_win_prob": round(h_prob_heur, 3),
            "confidence": "Medium",
            "description": "Based on Adjusted Efficiency & Pace"
        }
        
        # 3. Extract XGBoost v1 (Legacy)
        if pred_result.get("xgb_win_prob") is not None:
            xgb_prob = pred_result["xgb_win_prob"]
            engines["XGBoost (ML)"] = {
                "home_win_prob": round(xgb_prob, 3),
                "confidence": "High" if abs(xgb_prob - 0.5) > 0.15 else "Low",
                "description": "Gradient Boosting on Rolling Stats (L5/L10)"
            }
        
        # 4. Extract High-Accuracy XGBoost v2 (New)
        if pred_result.get("v2_available"):
            v2_prob = pred_result["v2_win_prob"]
            v2_factors = pred_result.get("v2_factors", [])
            
            engines["XGBoost v2 (High Accuracy)"] = {
                "home_win_prob": round(v2_prob, 3),
                "predicted_total": pred_result.get("v2_total"),
                "confidence": "Highest" if abs(v2_prob - 0.5) > 0.2 else "High",
                "description": "Advanced Dual-Model with Torvik Integration",
                "factors": v2_factors,
                "radar": pred_result.get("v2_radar", {}),
                # Frontend expects Factors to be inside a 'top_features' property of the explanation
                "explanation": {"top_features": v2_factors}
            }
            
            # Map to legacy key "XGBoost (ML)" as well if it doesn't already exist or to override it with V2 accuracy
            # The frontend specifically looks for "XGBoost (ML)" in some rationale blocks
            engines["XGBoost (ML)"] = {
                "home_win_prob": round(v2_prob, 3),
                "confidence": "Highest" if abs(v2_prob - 0.5) > 0.2 else "High",
                "description": "XGBoost v2 (Upgraded)",
                "explanation": {"top_features": v2_factors}
            }
        
    except Exception as e:
        logger.error(f"Error in NCAAB AI integration: {e}")
        return _fallback_logic(home_team, away_team, home_stats, away_stats)
    
    return {
        "timestamp": datetime.now().isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "engines": engines,
        "best_pick": _determine_best_pick(engines)
    }

def _determine_best_pick(engines):
    # Prefer XGBoost if available, else Heuristic
    if "XGBoost (ML)" in engines:
        prob = engines["XGBoost (ML)"]["home_win_prob"]
        return "Home" if prob > 0.5 else "Away"
    elif "Heuristic (Stats)" in engines:
        prob = engines["Heuristic (Stats)"]["home_win_prob"]
        return "Home" if prob > 0.5 else "Away"
    return "Unknown"

def _fallback_logic(home_team, away_team, home_stats, away_stats):
    """Original simple logic as fallback"""
    import math
    h_ppg = float(home_stats.get("pts_per_game", 75))
    a_ppg = float(away_stats.get("pts_per_game", 72))
    h_opp = float(home_stats.get("opp_pts_per_game", 70))
    a_opp = float(away_stats.get("opp_pts_per_game", 71))
    
    h_score = (h_ppg + a_opp) / 2 + 3.5
    a_score = (a_ppg + h_opp) / 2
    
    return {
        "timestamp": datetime.now().isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "engines": {
            "Baseline (Fallback)": {
                "home_score": round(h_score, 1),
                "away_score": round(a_score, 1),
                "home_win_prob": round(1 / (1 + math.exp(-(h_score - a_score) / 4)), 3)
            }
        },
        "best_pick": "Home" if h_score > a_score else "Away"
    }
