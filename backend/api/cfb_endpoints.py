"""
College Football API Endpoints
Provides REST API access to CFB data from CollegeFootballData.com
"""

from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cfb", tags=["College Football"])

from scripts.college_football_importer import (
    run_college_football_import,
    get_cfb_teams,
    get_cfb_games,
    get_cfb_player_stats,
    get_current_season
)


@router.get("/status")
async def cfb_status(request: Request):
    """Check if CFB features are available (API key configured)."""
    from src.config import COLLEGE_FOOTBALL_API_KEY
    return {
        "available": bool(COLLEGE_FOOTBALL_API_KEY),
        "current_season": get_current_season(),
        "message": "CFB features ready" if COLLEGE_FOOTBALL_API_KEY else "COLLEGE_FOOTBALL_API_KEY not configured"
    }


@router.post("/import")
async def trigger_cfb_import(
    year: Optional[int] = Query(None, description="Season year"),
    conference: Optional[str] = Query(None, description="Filter by conference"),
    import_type: str = Query("all", description="teams, games, stats, or all")
):
    """Trigger a CFB data import."""
    result = await run_college_football_import(
        year=year,
        conference=conference,
        import_type=import_type
    )
    return result


@router.get("/teams")
async def list_cfb_teams(
    year: Optional[int] = Query(None, description="Season year"),
    conference: Optional[str] = Query(None, description="Filter by conference")
):
    """Get list of CFB teams."""
    teams = await get_cfb_teams(year=year)
    
    if conference:
        teams = [t for t in teams if t.get("conference") == conference]
    
    return {
        "year": year or get_current_season(),
        "count": len(teams),
        "teams": teams
    }


@router.get("/teams/{team_id}")
async def get_cfb_team(request: Request, team_id: str, year: Optional[int] = Query(None)):
    """Get details for a specific team."""
    teams = await get_cfb_teams(year=year)
    
    # Match by ID or school name
    team = next(
        (t for t in teams if str(t.get("id")) == team_id or t.get("school", "").lower() == team_id.lower()),
        None
    )
    
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    
    return team


@router.get("/games")
async def list_cfb_games(
    year: Optional[int] = Query(None, description="Season year"),
    week: Optional[int] = Query(None, description="Week number"),
    team: Optional[str] = Query(None, description="Filter by team name")
):
    """Get CFB games/schedule."""
    games = await get_cfb_games(year=year, week=week)
    
    if team:
        team_lower = team.lower()
        games = [
            g for g in games 
            if team_lower in g.get("home_team", "").lower() 
            or team_lower in g.get("away_team", "").lower()
        ]
    
    return {
        "year": year or get_current_season(),
        "week": week,
        "count": len(games),
        "games": games
    }


@router.get("/stats/players")
async def list_cfb_player_stats(
    year: Optional[int] = Query(None, description="Season year"),
    team: Optional[str] = Query(None, description="Filter by team name"),
    position: Optional[str] = Query(None, description="Filter by position"),
    limit: int = Query(100, description="Max results to return")
):
    """Get CFB player statistics."""
    stats = await get_cfb_player_stats(year=year, team=team)
    
    if position:
        pos_lower = position.lower()
        stats = [s for s in stats if pos_lower in s.get("position", "").lower()]
    
    # Limit results
    stats = stats[:limit]
    
    return {
        "year": year or get_current_season(),
        "count": len(stats),
        "players": stats
    }


@router.get("/conferences")
async def list_cfb_conferences(request: Request, year: Optional[int] = Query(None)):
    """Get list of unique conferences."""
    teams = await get_cfb_teams(year=year)
    
    conferences = list(set(
        t.get("conference") for t in teams 
        if t.get("conference")
    ))
    conferences.sort()
    
    return {
        "year": year or get_current_season(),
        "conferences": conferences
    }
