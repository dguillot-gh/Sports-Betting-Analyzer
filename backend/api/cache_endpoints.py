"""
Odds Cache API Endpoints
========================
Endpoints for caching and retrieving odds data so late night games persist on refresh.
"""

from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cache", tags=["odds-cache"])
from api.db_endpoints import get_db_connection


# Import cache service lazily to avoid circular imports
def get_cache():
    from src.odds_cache import get_cache_service
    return get_cache_service()


class CacheGamesRequest(BaseModel):
    """Request to cache multiple games."""
    sport: str
    games: List[Dict[str, Any]]


class CacheAnalysisRequest(BaseModel):
    """Request to cache analysis for a specific game."""
    game_id: str
    analysis: Dict[str, Any]


@router.post("/init")
async def init_cache_table(request: Request):
    """Initialize the cache table (run once)."""
    try:
        cache = get_cache()
        await cache.ensure_table()
        return {"success": True, "message": "Cache table ready"}
    except Exception as e:
        logger.error(f"Failed to init cache table: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/games")
async def cache_games(request: Request):
    """
    Cache games with their odds data.
    Call this after fetching fresh odds from the API.
    """
    try:
        cache = get_cache()
        stored = await cache.store_games(request.sport, request.games)
        return {"success": True, "stored": stored}
    except Exception as e:
        logger.error(f"Failed to cache games: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analysis")
async def cache_analysis(request: Request):
    """
    Cache analysis/predictions for a specific game.
    Call this after running predictions.
    """
    try:
        cache = get_cache()
        success = await cache.store_analysis(request.game_id, request.analysis)
        return {"success": success}
    except Exception as e:
        logger.error(f"Failed to cache analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/games/{sport}")
async def get_cached_games(
    sport: str,
    exclude: Optional[str] = Query(None, description="Comma-separated game IDs to exclude"),
    include_expired: bool = Query(False, description="Include games up to 24h past expiry")
):
    """
    Get cached games for a sport.
    
    Use 'exclude' to skip games you already have from the live API.
    This returns only the cached games that fill the gaps.
    """
    try:
        cache = get_cache()
        
        exclude_ids = []
        if exclude:
            exclude_ids = [id.strip() for id in exclude.split(",")]
        
        games = await cache.get_cached_games(sport, exclude_ids, include_expired)
        return {"games": games, "count": len(games), "is_cached": True}
    except Exception as e:
        logger.error(f"Failed to get cached games: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/game/{game_id}")
async def get_cached_game(request: Request, game_id: str):
    """Get a specific game from cache."""
    try:
        cache = get_cache()
        game = await cache.get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found in cache")
        return game
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cached game: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cleanup")
async def cleanup_expired(request: Request):
    """Remove games expired more than 24 hours ago."""
    try:
        cache = get_cache()
        deleted = await cache.cleanup_expired()
        return {"success": True, "deleted": deleted}
    except Exception as e:
        logger.error(f"Failed to cleanup cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def cache_stats(request: Request):
    """Get cache statistics."""
    try:
        import asyncpg
        from src.odds_cache import DATABASE_URL
        
        conn = await get_db_connection(request)
        try:
            stats = {}
            
            # Count by sport
            rows = await conn.fetch("""
                SELECT sport, COUNT(*) as count 
                FROM game_odds_cache 
                GROUP BY sport
            """)
            stats["by_sport"] = {row["sport"]: row["count"] for row in rows}
            
            # Count expired vs active
            active = await conn.fetchval("""
                SELECT COUNT(*) FROM game_odds_cache WHERE expires_at > NOW()
            """)
            expired = await conn.fetchval("""
                SELECT COUNT(*) FROM game_odds_cache WHERE expires_at <= NOW()
            """)
            stats["active"] = active
            stats["expired"] = expired
            
            return stats
        finally:
            if hasattr(request.app.state, 'pool') and request.app.state.pool:
                await request.app.state.pool.release(conn)
            else:
                await conn.close()
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
