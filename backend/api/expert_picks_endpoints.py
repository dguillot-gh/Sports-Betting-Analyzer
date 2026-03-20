from fastapi import APIRouter, Request, HTTPException, Query
from typing import List, Optional
from datetime import datetime
import asyncpg
import logging
from src.config import DATABASE_URL
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/expert-picks", tags=["Expert Picks"])
from api.db_endpoints import get_db_connection

class ExpertPick(BaseModel):
    id: int
    created_at: datetime
    sport: str
    game_date: datetime
    away_team: str
    home_team: str
    expert_name: str
    spread_pick_team: Optional[str]
    spread_value: Optional[float]
    total_pick: Optional[str]
    total_value: Optional[float]
    source_url: Optional[str]

@router.get("/{sport}", response_model=List[ExpertPick])
async def get_expert_picks(
    sport: str, 
    date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD. Defaults to today.")
):
    """Fetch expert picks for a given sport and date."""
    if date:
        try:
            target_date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        # Defaults to most recent picks (usually today)
        target_date = datetime.utcnow().date()


    conn = None
    try:
        conn = await get_db_connection(request)
        rows = await conn.fetch("""
            SELECT id, created_at, sport, game_date, away_team, home_team, expert_name, 
                   spread_pick_team, spread_value, total_pick, total_value, source_url
            FROM expert_picks
            WHERE sport = $1 AND game_date = $2
            ORDER BY created_at DESC
        """, sport.upper(), target_date)
        
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching expert picks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            if hasattr(request.app.state, 'pool') and request.app.state.pool:
                await request.app.state.pool.release(conn)
            else:
                await conn.close()

@router.post("/trigger/{sport}")
async def trigger_cbs_scraper(request: Request, sport: str):
    """Manually trigger the CBS Expert Picks scraper."""
    import asyncio
    import os
    
    # Run the scraper as a subprocess or import and run
    # For simplicity and environment consistency, we'll try to run the script via subprocess
    # inside the container context
    try:
        process = await asyncio.create_subprocess_exec(
            'python', '/app/scripts/cbs_scraper.py', 
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return {"status": "success", "output": stdout.decode()}
        else:
            return {"status": "error", "message": stderr.decode()}
    except Exception as e:
        logger.error(f"Error triggering scraper: {e}")
        return {"status": "error", "message": str(e)}
