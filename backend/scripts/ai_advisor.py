
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from scripts.gemini_predictor import get_gemini_predictor
from scripts.nfl_ai_integration import get_nfl_ai_predictions
from scripts.nba_ai_integration import get_nba_ai_predictions
from scripts.ncaab_ai_integration import get_ncaab_ai_predictions
from scripts.nascar_ai_integration import get_nascar_ai_predictions
from services.sportsbookwire_service import get_sportsbookwire_service

logger = logging.getLogger(__name__)

class AIAdvisor:
    """
    Unified entry point for multi-engine predictions + Gemini insights.
    """
    async def get_full_analysis(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any], short_prompt: bool = False) -> Dict[str, Any]:
        results = {
            "sport": sport,
            "matchup": f"{away_team} @ {home_team}",
            "timestamp": datetime.now().isoformat(),
            "engines": {},
            "third_opinion": None,
            "llm_insight": None
        }
        
        # 1. Get Multi-Engine Predictions
        ai_data = {}
        try:
            if sport.lower() == "nba":
                ai_data = get_nba_ai_predictions(home_team, away_team, stats.get("home", {}), stats.get("away", {}))
                results["engines"] = ai_data.get("predictions", {})
                
                # Fetch SportsbookWire as third opinion for NBA
                try:
                    sbw_service = get_sportsbookwire_service()
                    results["third_opinion"] = await sbw_service.get_picks(home_team, away_team)
                except Exception as sbwe:
                    logger.error(f"SportsbookWire fetch failed: {sbwe}")
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
        # We enrich the stats with the engine results so Gemini can reference SHAP factors etc.
        try:
            gemini = get_gemini_predictor()
            analysis_stats = {**stats, "ml_engines": results["engines"]}
            results["llm_insight"] = await gemini.get_insight(sport, home_team, away_team, analysis_stats, game_date=results["timestamp"], short_prompt=short_prompt)
        except Exception as e:
            logger.error(f"Error getting Gemini insight: {e}")

        return results

_advisor = None
def get_ai_advisor():
    global _advisor
    if _advisor is None:
        _advisor = AIAdvisor()
    return _advisor
