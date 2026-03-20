from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Query
from typing import List, Dict, Optional, Any
import logging
from scripts.college_baseball_importer import (
    get_teams, 
    get_team_stats, 
    get_team_player_stats, 
    run_college_baseball_import,
    get_import_status
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/baseball/ncaa", tags=["College Baseball"])

@router.get("/teams")
def list_teams(division: int = 1):
    """
    Get list of teams for a specific division.
    """
    try:
        teams = get_teams(division)
        return {
            "division": division,
            "count": len(teams),
            "teams": teams
        }
    except Exception as e:
        logger.error(f"Error listing teams: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def trigger_import(request: Request, background_tasks: BackgroundTasks):
    """
    Trigger the 'one-click' import for all divisions.
    """
    try:
        # Default to ALL divisions (0) and smart year (0)
        background_tasks.add_task(run_college_baseball_import, division=0, year=0)
        return {"status": "started", "message": "College Baseball import started for all divisions."}
    except Exception as e:
        logger.error(f"Error starting import: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
def import_status():
    """
    Get the current status of the import process.
    """
    return get_import_status()

@router.get("/stats/{team_id}")
def get_stats(team_id: str, stat_type: str = "batting", year: int = 2025):
    """
    Get batting or pitching stats for a team.
    """
    try:
        # The importer saves files as {team_id}_{stat_type}.csv
        stats = get_team_player_stats(team_id, stat_type, year)
        return {
            "team_id": team_id,
            "stat_type": stat_type,
            "year": year,   
            "count": len(stats),
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting {stat_type} stats for {team_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/schedule/{team_id}")
def get_schedule_route(team_id: str, year: int = 2025):
    """
    Get schedule for a team.
    Note: Currently returns empty list as per importer limitation, but endpoint exists for future use.
    """
    try:
        # Importer has get_team_schedule but it returns empty list currently
        from scripts.college_baseball_importer import get_team_schedule
        games = get_team_schedule(team_id, year)
        return {
            "team_id": team_id,
            "year": year,
            "count": len(games),
            "games": games
        }
    except Exception as e:
        logger.error(f"Error getting schedule for {team_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
