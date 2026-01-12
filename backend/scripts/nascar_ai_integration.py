
import logging
import math
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def get_nascar_ai_predictions(
    driver_name: str,
    track_name: str,
    driver_stats: Dict[str, Any],
    track_type: str = "Intermediate"
) -> Dict[str, Any]:
    """
    NASCAR multi-engine prediction logic for a single driver.
    """
    engines = {}
    
    # 1. Baseline (Track-Type specific avg finish)
    avg_fin = float(driver_stats.get(f"avg_finish_{track_type.lower()}", 18))
    
    # Sigmoid mapping finish (1-40) to a "Win Prob" score
    # Smaller finish (1) = Higher prob
    base_score = 1 - (avg_fin / 40)
    
    engines["TrackBaseline"] = {
        "predicted_finish": round(avg_fin, 1),
        "win_prob": round(base_score * 0.1, 3) # Scaled down for 40 drivers
    }
    
    # 2. Linear (Driver Rating focus)
    rating = float(driver_stats.get("avg_driver_rating", 85))
    laps_led = float(driver_stats.get("avg_laps_led", 5))
    
    # Rating influence
    lin_score = base_score + (rating - 85) * 0.005 + (laps_led * 0.001)
    
    engines["RatingLinear"] = {
        "predicted_finish": round(avg_fin * (1 - (rating - 85) * 0.005), 1),
        "win_prob": round(max(0, lin_score * 0.12), 3)
    }
    
    # 3. Tree (Recent Momentum + Track History)
    recent_finish = float(driver_stats.get("recent_avg_finish", 15))
    track_history = float(driver_stats.get("track_avg_finish", 18))
    
    # Momentum weight
    tree_score = lin_score * 0.8 + (1 - (recent_finish / 40)) * 0.2
    
    engines["MomentumTree"] = {
        "predicted_finish": round((recent_finish + track_history) / 2, 1),
        "win_prob": round(max(0, tree_score * 0.15), 3)
    }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "driver": driver_name,
        "track": track_name,
        "engines": engines
    }
