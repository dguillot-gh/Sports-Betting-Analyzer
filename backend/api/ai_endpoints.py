
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
from scripts.ai_advisor import get_ai_advisor
from scripts.gemini_predictor import get_quota_status

router = APIRouter(prefix="/ai", tags=["ai_advisor"])

@router.get("/quota")
async def get_ai_quota():
    """Returns the current usage status of the Gemini API."""
    return get_quota_status()

@router.post("/analyze")
async def analyze_matchup(
    sport: str = Query(..., description="Sport category (nba, nfl, etc.)"),
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    # We allow passing stats directly if known, otherwise backend should fetch (future improvement)
    home_stats: Optional[str] = Query(None, description="JSON string of home stats"),
    away_stats: Optional[str] = Query(None, description="JSON string of away stats"),
    short_prompt: bool = Query(False, description="Use a shorter, more concise prompt")
):
    """
    Returns a unified analysis report including multi-engine metrics and LLM insights.
    """
    try:
        import json
        h_stats = json.loads(home_stats) if home_stats else {}
        a_stats = json.loads(away_stats) if away_stats else {}
        
        advisor = get_ai_advisor()
        stats = {"home": h_stats, "away": a_stats}
        
        return await advisor.get_full_analysis(sport, home_team, away_team, stats, short_prompt=short_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
