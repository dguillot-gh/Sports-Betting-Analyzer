"""
Database Service Layer
======================

Provides async database queries for the sports betting API.
Falls back to CSV files if database is unavailable or empty.
"""

import asyncpg
import pandas as pd
import json
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Database connection pool
_pool: Optional[asyncpg.Pool] = None

DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"


async def get_pool() -> asyncpg.Pool:
    """Get or create connection pool."""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
            logger.info("Database connection pool created")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
    return _pool


async def is_database_available() -> bool:
    """Check if database is available and has data."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM results")
            return count > 0
    except Exception as e:
        logger.warning(f"Database not available: {e}")
        return False


async def get_sport_id(sport_name: str) -> Optional[int]:
    """Get sport ID by name."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM sports WHERE name = $1", sport_name
        )


# =============================================================================
# Entity Queries (Drivers, Teams, Players)
# =============================================================================

async def get_entities(sport: str, entity_type: str = None, limit: int = 1000) -> List[Dict]:
    """Get entities for a sport."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id(sport)
        if not sport_id:
            return []
        
        if entity_type:
            rows = await conn.fetch(
                """SELECT id, name, type, metadata FROM entities 
                   WHERE sport_id = $1 AND type = $2 
                   ORDER BY name LIMIT $3""",
                sport_id, entity_type, limit
            )
        else:
            rows = await conn.fetch(
                """SELECT id, name, type, metadata FROM entities 
                   WHERE sport_id = $1 
                   ORDER BY name LIMIT $2""",
                sport_id, limit
            )
        
        return [dict(row) for row in rows]


async def get_entity_by_name(sport: str, name: str, entity_type: str = None) -> Optional[Dict]:
    """Get a specific entity by name."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id(sport)
        if not sport_id:
            return None
        
        if entity_type:
            row = await conn.fetchrow(
                """SELECT id, name, type, metadata FROM entities 
                   WHERE sport_id = $1 AND name ILIKE $2 AND type = $3""",
                sport_id, name, entity_type
            )
        else:
            row = await conn.fetchrow(
                """SELECT id, name, type, metadata FROM entities 
                   WHERE sport_id = $1 AND name ILIKE $2""",
                sport_id, name
            )
        
        return dict(row) if row else None


# =============================================================================
# Results Queries (Games, Races)
# =============================================================================

async def get_results(
    sport: str, 
    season: int = None, 
    entity_id: int = None,
    limit: int = 1000
) -> List[Dict]:
    """Get results for a sport, optionally filtered."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id(sport)
        if not sport_id:
            return []
        
        query = "SELECT * FROM results WHERE sport_id = $1"
        params = [sport_id]
        param_num = 2
        
        if season:
            query += f" AND season = ${param_num}"
            params.append(season)
            param_num += 1
        
        query += f" ORDER BY game_date DESC, id DESC LIMIT ${param_num}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


async def get_results_as_dataframe(sport: str, seasons: List[int] = None) -> pd.DataFrame:
    """Get results as a pandas DataFrame for ML training."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id(sport)
        if not sport_id:
            return pd.DataFrame()
        
        if seasons:
            placeholders = ', '.join(f'${i+2}' for i in range(len(seasons)))
            query = f"""
                SELECT r.*, 
                       h.name as home_team, 
                       a.name as away_team
                FROM results r
                LEFT JOIN entities h ON h.id = r.home_entity_id
                LEFT JOIN entities a ON a.id = r.away_entity_id
                WHERE r.sport_id = $1 AND r.season IN ({placeholders})
                ORDER BY r.season, r.game_date
            """
            rows = await conn.fetch(query, sport_id, *seasons)
        else:
            query = """
                SELECT r.*, 
                       h.name as home_team, 
                       a.name as away_team
                FROM results r
                LEFT JOIN entities h ON h.id = r.home_entity_id
                LEFT JOIN entities a ON a.id = r.away_entity_id
                WHERE r.sport_id = $1
                ORDER BY r.season, r.game_date
            """
            rows = await conn.fetch(query, sport_id)
        
        if not rows:
            return pd.DataFrame()
        
        # Convert to DataFrame and expand metadata JSON
        df = pd.DataFrame([dict(row) for row in rows])
        
        # Expand metadata column into separate columns
        if 'metadata' in df.columns:
            metadata_df = pd.json_normalize(df['metadata'].apply(
                lambda x: json.loads(x) if isinstance(x, str) else x or {}
            ))
            df = pd.concat([df.drop('metadata', axis=1), metadata_df], axis=1)
        
        return df


# =============================================================================
# Stats Queries
# =============================================================================

async def get_entity_stats(entity_id: int, stat_type: str = None) -> List[Dict]:
    """Get stats for an entity."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if stat_type:
            rows = await conn.fetch(
                """SELECT * FROM stats 
                   WHERE entity_id = $1 AND stat_type = $2
                   ORDER BY stat_date DESC, id DESC""",
                entity_id, stat_type
            )
        else:
            rows = await conn.fetch(
                """SELECT * FROM stats 
                   WHERE entity_id = $1
                   ORDER BY stat_date DESC, id DESC""",
                entity_id
            )
        
        return [dict(row) for row in rows]


async def get_player_stats_dataframe(sport: str) -> pd.DataFrame:
    """Get all player stats as DataFrame for analysis."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id(sport)
        if not sport_id:
            return pd.DataFrame()
        
        rows = await conn.fetch("""
            SELECT e.name as player, e.type, s.stat_type, s.season, s.stats
            FROM stats s
            JOIN entities e ON e.id = s.entity_id
            WHERE e.sport_id = $1 AND e.type = 'player'
        """, sport_id)
        
        if not rows:
            return pd.DataFrame()
        
        df = pd.DataFrame([dict(row) for row in rows])
        
        # Expand stats JSON
        if 'stats' in df.columns:
            stats_df = pd.json_normalize(df['stats'].apply(
                lambda x: json.loads(x) if isinstance(x, str) else x or {}
            ))
            df = pd.concat([df.drop('stats', axis=1), stats_df], axis=1)
        
        return df


# =============================================================================
# NASCAR-Specific Queries
# =============================================================================

async def get_nascar_race_results(
    season: int = None,
    driver: str = None,
    track: str = None,
    limit: int = 5000
) -> pd.DataFrame:
    """Get NASCAR race results with full metadata."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sport_id = await get_sport_id('nascar')
        if not sport_id:
            return pd.DataFrame()
        
        query = """
            SELECT r.season, r.track, r.metadata
            FROM results r
            WHERE r.sport_id = $1
        """
        params = [sport_id]
        param_num = 2
        
        if season:
            query += f" AND r.season = ${param_num}"
            params.append(season)
            param_num += 1
        
        if track:
            query += f" AND r.track ILIKE ${param_num}"
            params.append(f"%{track}%")
            param_num += 1
        
        query += f" ORDER BY r.season DESC, r.id LIMIT ${param_num}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        
        if not rows:
            return pd.DataFrame()
        
        # Build DataFrame from metadata
        data = []
        for row in rows:
            record = {
                'season': row['season'],
                'track': row['track'],
            }
            if row['metadata']:
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
                record.update(metadata)
            data.append(record)
        
        df = pd.DataFrame(data)
        
        # Filter by driver if specified
        if driver and 'driver' in df.columns:
            df = df[df['driver'].str.contains(driver, case=False, na=False)]
        
        return df


# =============================================================================
# Database Health Check
# =============================================================================

async def get_database_stats() -> Dict[str, Any]:
    """Get database statistics."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            stats = {}
            
            # Count per table
            for table in ['sports', 'entities', 'results', 'stats', 'models', 'predictions']:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                stats[table] = count
            
            # Count per sport
            sport_counts = await conn.fetch("""
                SELECT s.name, 
                       COUNT(DISTINCT e.id) as entities,
                       COUNT(DISTINCT r.id) as results
                FROM sports s
                LEFT JOIN entities e ON e.sport_id = s.id
                LEFT JOIN results r ON r.sport_id = s.id
                GROUP BY s.id, s.name
            """)
            stats['by_sport'] = {row['name']: {'entities': row['entities'], 'results': row['results']} 
                                 for row in sport_counts}
            
            return stats
    except Exception as e:
        return {'error': str(e)}


# =============================================================================
# Cleanup
# =============================================================================

async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")
