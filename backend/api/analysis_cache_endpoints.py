from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any, List
import logging
from src.odds_storage import get_odds_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cache", tags=["cache"])

@router.post("/analysis")
async def save_manual_analysis(data: Dict[str, Any] = Body(...)):
    """
    Save a manual analysis result. 
    Expects format: { "sport": "nba", "home_team": "...", "away_team": "...", "analysis": { ... } }
    """
    try:
        storage = get_odds_storage()
        sport = data.get("sport", "nba")
        home = data.get("home_team")
        away = data.get("away_team")
        analysis = data.get("analysis")
        
        if not all([home, away, analysis]):
            raise HTTPException(status_code=400, detail="Missing required fields: home_team, away_team, analysis")
            
        success = await storage.save_analysis(sport, home, away, analysis)
        return {"success": success}
    except Exception as e:
        logger.error(f"Error in save_manual_analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analysis/today")
async def get_todays_analyses():
    """Get all analysis results stored today."""
    try:
        storage = get_odds_storage()
        results = await storage.get_todays_analyses()
        return {"count": len(results), "analyses": results}
    except Exception as e:
        logger.error(f"Error in get_todays_analyses: {e}")
        raise HTTPException(status_code=500, detail=str(e))
