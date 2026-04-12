import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

from src.database import get_pool
from api.json_utils import sanitize_for_json


def _parse_jsonb(val):
    """Parse a JSONB value that asyncpg may return as a string."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}

CREATE_CACHE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS game_odds_cache (
    id VARCHAR(100) PRIMARY KEY,
    sport VARCHAR(50),
    home_team VARCHAR(100),
    away_team VARCHAR(100),
    game_date TIMESTAMPTZ,
    odds_data JSONB,
    analysis JSONB,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cache_sport ON game_odds_cache(sport);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON game_odds_cache(expires_at);
"""

# New table for Historical Snapshots
CREATE_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS historical_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    sportsbook VARCHAR(50),
    sport VARCHAR(50), -- 'all' or specific sport
    game_count INT,
    value_bet_count INT,
    raw_data JSONB, -- Compressed/minified JSON of the full analysis
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON historical_snapshots(timestamp);
"""

class OddsCacheService:
    def __init__(self):
        self._pool = None

    async def ensure_table(self):
        """Ensure the cache tables exist."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(CREATE_CACHE_TABLE_SQL)
            await conn.execute(CREATE_SNAPSHOTS_TABLE_SQL)
            logger.info("Cache tables ensured.")

    async def store_games(self, sport: str, games: List[Dict[str, Any]], ttl_hours: int = 24):
        """Store multiple games in the cache."""
        pool = await get_pool()
        
        expires_at = datetime.now() + timedelta(hours=ttl_hours)
        count = 0
        
        async with pool.acquire() as conn:
            for game in games:
                try:
                    game_id = game.get("id")
                    if not game_id:
                        # Generate ID if missing
                        home = game.get("home_team", "unknown")
                        away = game.get("away_team", "unknown")
                        date_str = game.get("game_time", "")
                        game_id = f"{sport}_{home}_{away}_{date_str}"

                    # Clean data for storage
                    odds_data = {
                        "spread": game.get("spread"),
                        "over_under": game.get("over_under"),
                        "home_moneyline": game.get("home_moneyline"),
                        "away_moneyline": game.get("away_moneyline")
                    }
                    
                    analysis_data = {
                        "simple_model": game.get("simple_model"),
                        "xgboost_model": game.get("xgboost_model"),
                        "has_value": game.get("has_value", False),
                        "prediction": game.get("prediction")
                    }
                    
                    await conn.execute("""
                        INSERT INTO game_odds_cache (id, sport, home_team, away_team, game_date, odds_data, analysis, fetched_at, expires_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)
                        ON CONFLICT (id) DO UPDATE SET
                            odds_data = EXCLUDED.odds_data,
                            analysis = EXCLUDED.analysis,
                            fetched_at = NOW(),
                            expires_at = EXCLUDED.expires_at
                    """, game_id, sport, game.get("home_team"), game.get("away_team"), 
                       self._parse_date(game.get("game_time")), 
                       json.dumps(sanitize_for_json(odds_data)), json.dumps(sanitize_for_json(analysis_data)), 
                       expires_at)
                    
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to cache game {game.get('home_team')} vs {game.get('away_team')}: {e}")
                    
        return count

    async def store_analysis(self, game_id: str, analysis: Dict[str, Any]):
        """Update the analysis for a cached game."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE game_odds_cache 
                SET analysis = $1, fetched_at = NOW()
                WHERE id = $2
            """, json.dumps(sanitize_for_json(analysis)), game_id)
            return True
            
    async def get_cached_games(self, sport: str, exclude_ids: List[str] = None, include_expired: bool = False) -> List[Dict[str, Any]]:
        """Retrieve cached games, optionally excluding IDs we already have."""
        pool = await get_pool()
        exclude_ids = exclude_ids or []
        
        query = "SELECT * FROM game_odds_cache WHERE sport = $1"
        args = [sport]
        
        if not include_expired:
            query += " AND expires_at > NOW()"
            
        if exclude_ids:
            query += " AND id != ALL($2)"
            args.append(exclude_ids)
            
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            results = []
            for row in rows:
                d = dict(row)
                d['odds_data'] = _parse_jsonb(d.get('odds_data'))
                d['analysis'] = _parse_jsonb(d.get('analysis'))
                results.append(d)
            return results

    async def get_game(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get a single game by ID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM game_odds_cache WHERE id = $1", game_id)
            if not row:
                return None
            d = dict(row)
            d['odds_data'] = _parse_jsonb(d.get('odds_data'))
            d['analysis'] = _parse_jsonb(d.get('analysis'))
            return d

    async def cleanup_expired(self):
        """Remove expired entries."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM game_odds_cache WHERE expires_at < NOW() - INTERVAL '24 hours'")
            return result

    async def save_snapshot(self, snapshot_data: Dict[str, Any]):
        """Save a historical market snapshot."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO historical_snapshots (sportsbook, sport, game_count, value_bet_count, raw_data)
                VALUES ($1, $2, $3, $4, $5)
            """, 
            snapshot_data.get("sportsbook"),
            snapshot_data.get("sport", "all"),
            snapshot_data.get("total_games", 0),
            snapshot_data.get("total_value_bets", 0),
            json.dumps(snapshot_data)
            )
            logger.info(f"Saved historical snapshot for {snapshot_data.get('sport')}")

    def _parse_date(self, date_str):
        if not date_str: return None
        try:
            return datetime.fromisoformat(date_str)
        except:
            return None

_cache_service = None

def get_cache_service():
    global _cache_service
    if _cache_service is None:
        _cache_service = OddsCacheService()
    return _cache_service
