
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from scripts.gemini_predictor import get_gemini_predictor
from scripts.nfl_ai_integration import get_nfl_ai_predictions
from scripts.nba_ai_integration import get_nba_ai_predictions
from scripts.ncaab_ai_integration import get_ncaab_ai_predictions
from scripts.nascar_ai_integration import get_nascar_ai_predictions

logger = logging.getLogger(__name__)

class AIAdvisor:
    """
    Unified entry point for multi-engine predictions + Gemini insights.
    """
    async def get_full_analysis(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        results = {
            "sport": sport,
            "matchup": f"{away_team} @ {home_team}",
            "timestamp": datetime.now().isoformat(),
            "engines": {},
            "llm_insight": None
        }
        
        # 1. Get Multi-Engine Predictions
        try:
            if sport.lower() == "nba":
                ai_data = get_nba_ai_predictions(home_team, away_team, stats.get("home", {}), stats.get("away", {}))
                results["engines"] = ai_data.get("predictions", {})
            elif sport.lower() == "nfl":
                ai_data = get_nfl_ai_predictions(home_team, away_team, stats.get("home", {}), stats.get("away", {}))
                results["engines"] = ai_data.get("engines", {})
            elif sport.lower() == "ncaab":
                ai_data = get_ncaab_ai_predictions(home_team, away_team, stats.get("home", {}), stats.get("away", {}))
                results["engines"] = ai_data.get("engines", {})
            elif sport.lower() == "nascar":
                ai_data = get_nascar_ai_predictions(home_team, away_team, stats.get("home", {}))
                results["engines"] = ai_data.get("engines", {})
        except Exception as e:
            logger.error(f"Error getting multi-engine predictions for {sport}: {e}")

        # 2. Get LLM Insight (Gemini)
        try:
            gemini = get_gemini_predictor()
            results["llm_insight"] = await gemini.get_insight(sport, home_team, away_team, stats, game_date=results["timestamp"])
        except Exception as e:
            logger.error(f"Error getting Gemini insight: {e}")

        return results

_advisor = None
def get_ai_advisor():
    global _advisor
    if _advisor is None:
        _advisor = AIAdvisor()
    return _advisor
