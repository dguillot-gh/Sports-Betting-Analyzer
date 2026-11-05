from fastapi import APIRouter, Request, HTTPException, Body
from typing import Dict, Any, List
import logging
from src.odds_storage import get_odds_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cache", tags=["cache"])

@router.get("/analysis/today")
async def get_todays_analyses(request: Request):
    """Get all analysis results stored today."""
    try:
        storage = get_odds_storage()
        results = await storage.get_todays_analyses()
        return {"count": len(results), "analyses": results}
    except Exception as e:
        logger.error(f"Error in get_todays_analyses: {e}")
        raise HTTPException(status_code=500, detail=str(e))
