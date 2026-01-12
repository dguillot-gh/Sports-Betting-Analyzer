
import logging
import math
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def get_nfl_ai_predictions(
    home_team: str,
    away_team: str,
    home_stats: Dict[str, Any],
    away_stats: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Returns predictions for an NFL game from multiple internal engines.
    """
    engines = {}
    
    # 1. Baseline Engine (Weighted PPG/OppPPG)
    h_ppg = float(home_stats.get("offense_ppg", 22))
    a_ppg = float(away_stats.get("offense_ppg", 21))
    h_opp = float(home_stats.get("defense_ppg", 22))
    a_opp = float(away_stats.get("defense_ppg", 22))
    
    h_score = (h_ppg + a_opp) / 2 + 1.5 # Home field
    a_score = (a_ppg + h_opp) / 2
    
    engines["Baseline"] = {
        "home_score": round(h_score, 1),
        "away_score": round(a_score, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score - a_score) / 7)), 3)
    }
    
    # 2. Linear (EPA Weighting)
    # If EPA stats aren't there, we fallback to a slight variation
    h_epa = float(home_stats.get("offense_epa", 0.05))
    a_epa = float(away_stats.get("offense_epa", 0.02))
    
    h_score_l = h_score + (h_epa * 10)
    a_score_l = a_score + (a_epa * 10)
    
    engines["Linear"] = {
        "home_score": round(h_score_l, 1),
        "away_score": round(a_score_l, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_l - a_score_l) / 6)), 3)
    }
    
    # 3. Tree (Defensive Efficiency priority)
    h_def_eff = float(home_stats.get("defensive_efficiency", 0.5))
    a_def_eff = float(away_stats.get("defensive_efficiency", 0.5))
    
    # Simple "tree-like" rule: penalize score if defense is elite
    h_score_t = h_score_l * (1 - (a_def_eff - 0.5) * 0.1)
    a_score_t = a_score_l * (1 - (h_def_eff - 0.5) * 0.1)
    
    engines["Tree"] = {
        "home_score": round(h_score_t, 1),
        "away_score": round(a_score_t, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_t - a_score_t) / 6.5)), 3)
    }
    
    # 4. Neural Network (MLP Surrogate)
    # MLP usually picks up non-linearities like "SOS vs Efficiency"
    h_sos = float(home_stats.get("sos", 0))
    a_sos = float(away_stats.get("sos", 0))
    
    h_score_n = h_score_t + (h_sos * 2)
    a_score_n = a_score_t + (a_sos * 2)
    
    engines["MLP"] = {
        "home_score": round(h_score_n, 1),
        "away_score": round(a_score_n, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_n - a_score_n) / 5.5)), 3)
    }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "engines": engines,
        "best_pick": "Home" if engines["MLP"]["home_win_prob"] > 0.5 else "Away"
    }
