"""
Odds Cache Service
==================
Caches odds and analysis data so late night games persist on refresh.

Rules:
1. Fresh API data ALWAYS takes priority
2. Cache only fills gaps for games that disappeared from API
3. Games expire 48 hours after game time for morning-after persistence
4. Predictions/model training NOT affected (uses nflverse/hoopR data)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncpg

logger = logging.getLogger(__name__)

from src.config import DATABASE_URL

# Track if table has been initialized this session
_table_initialized = False


# SQL for creating the cache table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS game_odds_cache (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(100) UNIQUE NOT NULL,
    sport VARCHAR(20) NOT NULL,
    game_date TIMESTAMPTZ,
    home_team VARCHAR(100),
    away_team VARCHAR(100),
    odds_data JSONB,
    analysis JSONB,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    
    CONSTRAINT unique_game UNIQUE (game_id)
);

CREATE INDEX IF NOT EXISTS idx_cache_sport_date ON game_odds_cache(sport, game_date);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON game_odds_cache(expires_at);
"""


class OddsCacheService:
    """Service for caching and retrieving odds data."""
    
    def __init__(self, db_url: str = DATABASE_URL):
        self.db_url = db_url
    
    async def ensure_table(self):
        """Create the cache table if it doesn't exist."""
        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute(CREATE_TABLE_SQL)
            logger.info("game_odds_cache table ready")
        finally:
            await conn.close()
    
    async def store_games(self, sport: str, games: List[Dict[str, Any]]) -> int:
        """
        Store or update games in the cache.
        Returns number of games stored.
        Auto-creates table on first use.
        """
        global _table_initialized
        
        conn = await asyncpg.connect(self.db_url)
        stored = 0
        
        try:
            # Auto-create table on first use
            if not _table_initialized:
                await conn.execute(CREATE_TABLE_SQL)
                _table_initialized = True
                logger.info("game_odds_cache table auto-initialized")
            
            for game in games:
                game_id = game.get("id") or game.get("game_id")
                if not game_id:
                    continue
                
                # Parse game date
                game_date = None
                date_str = game.get("commence_time") or game.get("game_date") or game.get("date")
                if date_str:
                    try:
                        if isinstance(date_str, str):
                            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        else:
                            game_date = date_str
                    except:
                        pass
                
                # Set expiration: 48 hours after game time, or 24 hours from now if no date
                if game_date:
                    expires_at = game_date + timedelta(hours=48)
                else:
                    expires_at = datetime.utcnow() + timedelta(hours=24)
                
                # Extract teams
                home_team = game.get("home_team") or game.get("home")
                away_team = game.get("away_team") or game.get("away")
                
                # Store odds and analysis separately
                odds_data = game.get("bookmakers") or game.get("odds") or {}
                analysis = game.get("analysis") or game.get("predictions") or {}
                
                try:
                    await conn.execute("""
                        INSERT INTO game_odds_cache 
                            (game_id, sport, game_date, home_team, away_team, odds_data, analysis, expires_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (game_id) DO UPDATE SET
                            odds_data = EXCLUDED.odds_data,
                            analysis = COALESCE(EXCLUDED.analysis, game_odds_cache.analysis),
                            fetched_at = NOW(),
                            expires_at = EXCLUDED.expires_at
                    """, 
                        str(game_id), sport, game_date, home_team, away_team,
                        json.dumps(odds_data), json.dumps(analysis), expires_at
                    )
                    stored += 1
                except Exception as e:
                    logger.warning(f"Failed to cache game {game_id}: {e}")
            
            return stored
        finally:
            await conn.close()
    
    async def store_analysis(self, game_id: str, analysis: Dict[str, Any]) -> bool:
        """Store analysis results for a specific game."""
        conn = await asyncpg.connect(self.db_url)
        try:
            result = await conn.execute("""
                UPDATE game_odds_cache 
                SET analysis = $2, fetched_at = NOW()
                WHERE game_id = $1
            """, str(game_id), json.dumps(analysis))
            return "UPDATE 1" in result
        finally:
            await conn.close()
    
    async def get_cached_games(
        self, 
        sport: str, 
        exclude_ids: Optional[List[str]] = None,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get cached games for a sport.
        
        Args:
            sport: 'nfl', 'nba', etc.
            exclude_ids: Game IDs to exclude (usually from fresh API data)
            include_expired: If True, include games up to 24h past expiry
        """
        global _table_initialized
        
        try:
            conn = await asyncpg.connect(self.db_url)
        except Exception as e:
            logger.warning(f"Could not connect to database for cache: {e}")
            return []
        
        try:
            # Auto-create table if needed
            if not _table_initialized:
                await conn.execute(CREATE_TABLE_SQL)
                _table_initialized = True
            
            # Build query
            if include_expired:
                # Show games from last 24 hours even if "expired"
                time_filter = "game_date > NOW() - INTERVAL '24 hours'"
            else:
                time_filter = "expires_at > NOW()"
            
            query = f"""
                SELECT game_id, sport, game_date, home_team, away_team, 
                       odds_data, analysis, fetched_at, expires_at
                FROM game_odds_cache
                WHERE sport = $1 AND {time_filter}
                ORDER BY game_date DESC
            """
            
            rows = await conn.fetch(query, sport)
            
            games = []
            exclude_set = set(exclude_ids or [])
            
            for row in rows:
                if row["game_id"] in exclude_set:
                    continue
                
                games.append({
                    "id": row["game_id"],
                    "game_id": row["game_id"],
                    "sport": row["sport"],
                    "game_date": row["game_date"].isoformat() if row["game_date"] else None,
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "odds_data": json.loads(row["odds_data"]) if row["odds_data"] else {},
                    "analysis": json.loads(row["analysis"]) if row["analysis"] else {},
                    "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
                    "is_cached": True  # Mark as cached so UI can indicate
                })
            
            return games
        finally:
            await conn.close()
    
    async def cleanup_expired(self) -> int:
        """Remove games expired more than 24 hours ago."""
        conn = await asyncpg.connect(self.db_url)
        try:
            result = await conn.execute("""
                DELETE FROM game_odds_cache 
                WHERE expires_at < NOW() - INTERVAL '24 hours'
            """)
            deleted = int(result.split()[-1]) if result else 0
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired cached games")
            return deleted
        finally:
            await conn.close()
    
    async def get_game(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific game from cache."""
        conn = await asyncpg.connect(self.db_url)
        try:
            row = await conn.fetchrow("""
                SELECT * FROM game_odds_cache WHERE game_id = $1
            """, str(game_id))
            
            if not row:
                return None
            
            return {
                "id": row["game_id"],
                "game_id": row["game_id"],
                "sport": row["sport"],
                "game_date": row["game_date"].isoformat() if row["game_date"] else None,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "odds_data": json.loads(row["odds_data"]) if row["odds_data"] else {},
                "analysis": json.loads(row["analysis"]) if row["analysis"] else {},
                "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
                "is_cached": True
            }
        finally:
            await conn.close()


# Singleton instance
_cache_service = None

def get_cache_service() -> OddsCacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = OddsCacheService()
    return _cache_service
