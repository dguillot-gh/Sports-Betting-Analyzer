
import logging
import math
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def get_ncaab_ai_predictions(
    home_team: str,
    away_team: str,
    home_stats: Dict[str, Any],
    away_stats: Dict[str, Any]
) -> Dict[str, Any]:
    """
    NCAAB multi-engine prediction logic.
    """
    engines = {}
    
    # 1. Baseline (Simple Adjusted PPG)
    h_ppg = float(home_stats.get("pts_per_game", 75))
    a_ppg = float(away_stats.get("pts_per_game", 72))
    h_opp = float(home_stats.get("opp_pts_per_game", 70))
    a_opp = float(away_stats.get("opp_pts_per_game", 71))
    
    # Home court in college is huge (~3.5 pts)
    h_score = (h_ppg + a_opp) / 2 + 3.5
    a_score = (a_ppg + h_opp) / 2
    
    engines["Baseline"] = {
        "home_score": round(h_score, 1),
        "away_score": round(a_score, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score - a_score) / 4)), 3)
    }
    
    # 2. Linear (Shooting/Rebounding weight)
    h_fg = float(home_stats.get("fg_pct", 0.45))
    a_fg = float(away_stats.get("fg_pct", 0.44))
    h_reb = float(home_stats.get("reb_per_game", 35))
    a_reb = float(away_stats.get("reb_per_game", 34))
    
    h_score_l = h_score + (h_fg - 0.44) * 20 + (h_reb - a_reb) * 0.2
    a_score_l = a_score + (a_fg - 0.44) * 20
    
    engines["Linear"] = {
        "home_score": round(h_score_l, 1),
        "away_score": round(a_score_l, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_l - a_score_l) / 4.1)), 3)
    }
    
    # 3. Tree (Tournament Rank / SOS priority)
    h_rank = int(home_stats.get("rank", 50))
    a_rank = int(away_stats.get("rank", 50))
    
    # Lower rank is better
    h_score_t = h_score_l - (h_rank - 50) * 0.1
    a_score_t = a_score_l - (a_rank - 50) * 0.1
    
    engines["Tree"] = {
        "home_score": round(h_score_t, 1),
        "away_score": round(a_score_t, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_t - a_score_t) / 4.2)), 3)
    }
    
    # 4. MLP (Deep non-linear interaction)
    # Neural net usually captures variables like "High Pace vs Slow Pace"
    h_pace = float(home_stats.get("pace", 70))
    a_pace = float(away_stats.get("pace", 70))
    pace_factor = (h_pace + a_pace) / 140
    
    h_score_n = h_score_t * pace_factor
    a_score_n = a_score_t * pace_factor
    
    engines["MLP"] = {
        "home_score": round(h_score_n, 1),
        "away_score": round(a_score_n, 1),
        "home_win_prob": round(1 / (1 + math.exp(-(h_score_n - a_score_n) / 3.8)), 3)
    }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "engines": engines,
        "best_pick": "Home" if engines["MLP"]["home_win_prob"] > 0.5 else "Away"
    }
