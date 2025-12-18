"""
Database Import API Endpoints
=============================

Add these endpoints to app.py for database import functionality.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import asyncpg
import pandas as pd
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

router = APIRouter(prefix="/db", tags=["database"])


class ImportRequest(BaseModel):
    sport: str
    source: str = "csv"  # 'csv', 'kaggle'
    file_path: Optional[str] = None


class ImportResponse(BaseModel):
    success: bool
    message: str
    rows_imported: int = 0
    sport: str


class ImportStatus(BaseModel):
    sport: str
    source: str
    rows_imported: int
    status: str
    imported_at: str


async def get_db_connection():
    """Get database connection."""
    try:
        return await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")


@router.get("/health")
async def database_health():
    """Check database connectivity."""
    try:
        conn = await get_db_connection()
        result = await conn.fetchval("SELECT COUNT(*) FROM sports")
        await conn.close()
        return {"status": "healthy", "sports_count": result}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/stats")
async def database_stats():
    """Get database statistics."""
    conn = await get_db_connection()
    try:
        stats = {}
        
        # Count records per table
        tables = ['sports', 'entities', 'results', 'race_results', 'stats', 'models', 'predictions']
        for table in tables:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            stats[table] = count
        
        # Count per sport
        sport_counts = await conn.fetch("""
            SELECT s.name, COUNT(r.id) as result_count, COUNT(DISTINCT e.id) as entity_count
            FROM sports s
            LEFT JOIN results r ON r.sport_id = s.id
            LEFT JOIN entities e ON e.sport_id = s.id
            GROUP BY s.id, s.name
        """)
        stats['by_sport'] = {row['name']: {'results': row['result_count'], 'entities': row['entity_count']} 
                            for row in sport_counts}
        
        return stats
    finally:
        await conn.close()


@router.get("/import/history")
async def get_import_history():
    """Get import history."""
    conn = await get_db_connection()
    try:
        rows = await conn.fetch("""
            SELECT ih.*, s.name as sport_name
            FROM import_history ih
            JOIN sports s ON s.id = ih.sport_id
            ORDER BY ih.imported_at DESC
            LIMIT 50
        """)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


@router.post("/import/csv/{sport}")
async def import_csv_to_database(sport: str, background_tasks: BackgroundTasks):
    """Import CSV data for a sport into the database."""
    valid_sports = ['nascar', 'nfl', 'nba']
    if sport not in valid_sports:
        raise HTTPException(status_code=400, detail=f"Invalid sport. Must be one of: {valid_sports}")
    
    # Run import in background
    background_tasks.add_task(run_csv_import, sport)
    
    return {"status": "started", "message": f"Import started for {sport}. Check /db/import/history for status."}


async def run_csv_import(sport: str):
    """Background task to run CSV import."""
    from scripts.migrate_data import run_migration
    await run_migration(sport)


@router.post("/import/kaggle/{sport}")
async def import_kaggle_to_database(sport: str, dataset_id: str, background_tasks: BackgroundTasks):
    """Download from Kaggle and import to database."""
    # This will:
    # 1. Download from Kaggle (using existing data_sources.py)
    # 2. Import to PostgreSQL
    
    background_tasks.add_task(run_kaggle_import, sport, dataset_id)
    
    return {"status": "started", "message": f"Kaggle import started for {sport} from {dataset_id}"}


async def run_kaggle_import(sport: str, dataset_id: str):
    """Background task for Kaggle import."""
    logger.info(f"Starting Kaggle import: {sport} from {dataset_id}")
    
    # Step 1: Download from Kaggle
    from src.data_sources import KaggleDataSource
    kaggle = KaggleDataSource()
    
    try:
        # Download dataset
        download_path = kaggle.download_dataset(dataset_id, sport)
        logger.info(f"Downloaded to {download_path}")
        
        # Step 2: Import to database
        from scripts.migrate_data import run_migration
        await run_migration(sport)
        
        logger.info(f"Kaggle import complete for {sport}")
    except Exception as e:
        logger.error(f"Kaggle import failed: {e}")


@router.delete("/clear/{sport}")
async def clear_sport_data(sport: str):
    """Clear all data for a sport (careful!)."""
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Delete in order (foreign keys)
        await conn.execute("DELETE FROM predictions WHERE model_id IN (SELECT id FROM models WHERE sport_id = $1)", sport_id)
        await conn.execute("DELETE FROM models WHERE sport_id = $1", sport_id)
        await conn.execute("DELETE FROM race_results WHERE result_id IN (SELECT id FROM results WHERE sport_id = $1)", sport_id)
        await conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
        await conn.execute("DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)", sport_id)
        await conn.execute("DELETE FROM entities WHERE sport_id = $1", sport_id)
        
        return {"success": True, "message": f"Cleared all data for {sport}"}
    finally:
        await conn.close()


# ============================================
# PROFILE ENDPOINTS
# ============================================

@router.get("/profiles/{sport}/list")
async def get_profile_list(sport: str, entity_type: str = None, series: str = None, search: str = None, limit: int = 500):
    """
    Get list of entities (players/drivers/teams) for a sport.
    
    Args:
        sport: 'nascar', 'nfl', 'nba'
        entity_type: optional filter ('player', 'driver', 'team')
        series: NASCAR series filter ('cup', 'xfinity', 'trucks')
        search: optional name search
        limit: max results (default 500)
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Build query based on sport
        if sport == 'nascar':
            default_type = 'driver'
        else:
            default_type = 'player'
        
        type_filter = entity_type or default_type
        
        query = """
            SELECT DISTINCT e.id, e.name, e.type, e.series, e.metadata
            FROM entities e
            WHERE e.sport_id = $1 AND e.type = $2
        """
        params = [sport_id, type_filter]
        
        # Add series filter for NASCAR
        if series and sport == 'nascar':
            query += f" AND e.series = ${len(params) + 1}"
            params.append(series)
        
        if search:
            query += f" AND e.name ILIKE ${len(params) + 1}"
            params.append(f"%{search}%")
        
        query += f" ORDER BY e.name LIMIT ${len(params) + 1}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        
        return {
            "sport": sport,
            "entity_type": type_filter,
            "series": series,
            "count": len(rows),
            "entities": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["type"],
                    "series": row["series"],
                    "metadata": row["metadata"] if row["metadata"] else {}
                }
                for row in rows
            ]
        }
    finally:
        await conn.close()


@router.get("/profiles/{sport}/{name}")
async def get_entity_profile(sport: str, name: str, series: str = None, season: int = None):
    """
    Get full profile for an entity with stats and recent results.
    
    Args:
        sport: 'nascar', 'nfl', 'nba'
        name: entity name (player/driver name)
        series: NASCAR series filter ('cup', 'xfinity', 'trucks')
        season: optional season filter
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Find entity - include series filter for NASCAR
        if series and sport == 'nascar':
            entity = await conn.fetchrow("""
                SELECT id, name, type, series, metadata
                FROM entities
                WHERE sport_id = $1 AND name ILIKE $2 AND series = $3
                LIMIT 1
            """, sport_id, f"%{name}%", series)
        else:
            entity = await conn.fetchrow("""
                SELECT id, name, type, series, metadata
                FROM entities
                WHERE sport_id = $1 AND name ILIKE $2
                LIMIT 1
            """, sport_id, f"%{name}%")
        
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity '{name}' not found in {sport}" + (f" ({series})" if series else ""))
        
        entity_id = entity["id"]
        
        # Get available seasons - filter by series if specified
        if series and sport == 'nascar':
            seasons = await conn.fetch("""
                SELECT DISTINCT season FROM stats 
                WHERE entity_id = $1 AND season IS NOT NULL AND series = $2
                ORDER BY season DESC
            """, entity_id, series)
        else:
            seasons = await conn.fetch("""
                SELECT DISTINCT season FROM stats 
                WHERE entity_id = $1 AND season IS NOT NULL
                ORDER BY season DESC
            """, entity_id)
        available_seasons = [row["season"] for row in seasons]
        
        # Get stats
        stats_query = """
            SELECT stat_type, value, season
            FROM stats
            WHERE entity_id = $1
        """
        if season:
            stats_query += f" AND season = {season}"
        stats_query += " ORDER BY season DESC, stat_type"
        
        stats_rows = await conn.fetch(stats_query, entity_id)
        
        # Organize stats by season
        stats_by_season = {}
        for row in stats_rows:
            s = row["season"] or "career"
            if s not in stats_by_season:
                stats_by_season[s] = {}
            stats_by_season[s][row["stat_type"]] = row["value"]
        
        # Get recent results (last 10)
        if sport == "nascar":
            results = await conn.fetch("""
                SELECT r.game_date, r.metadata, rr.finish_position, rr.start_position, rr.laps_led
                FROM results r
                JOIN race_results rr ON rr.result_id = r.id
                WHERE rr.entity_id = $1
                ORDER BY r.game_date DESC
                LIMIT 10
            """, entity_id)
        else:
            # NBA/NFL - entity could be home or away
            results = await conn.fetch("""
                SELECT r.game_date, r.season, r.home_score, r.away_score, r.metadata,
                       h.name as home_team, a.name as away_team
                FROM results r
                LEFT JOIN entities h ON h.id = r.home_entity_id
                LEFT JOIN entities a ON a.id = r.away_entity_id
                WHERE r.home_entity_id = $1 OR r.away_entity_id = $1
                ORDER BY r.game_date DESC
                LIMIT 10
            """, entity_id)
        
        return {
            "entity": {
                "id": entity["id"],
                "name": entity["name"],
                "type": entity["type"],
                "metadata": entity["metadata"] if entity["metadata"] else {}
            },
            "sport": sport,
            "available_seasons": available_seasons,
            "stats": stats_by_season,
            "recent_results": [dict(row) for row in results]
        }
    finally:
        await conn.close()


@router.get("/profiles/{sport}/{name}/history")
async def get_entity_history(sport: str, name: str, limit: int = 50):
    """
    Get full result history for an entity.
    
    Args:
        sport: 'nascar', 'nfl', 'nba'
        name: entity name
        limit: max results
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Find entity
        entity = await conn.fetchrow("""
            SELECT id, name, type FROM entities
            WHERE sport_id = $1 AND name ILIKE $2
            LIMIT 1
        """, sport_id, f"%{name}%")
        
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")
        
        entity_id = entity["id"]
        
        if sport == "nascar":
            rows = await conn.fetch("""
                SELECT r.game_date, r.season, r.metadata as race_info,
                       rr.finish_position, rr.start_position, rr.laps_led, rr.points
                FROM results r
                JOIN race_results rr ON rr.result_id = r.id
                WHERE rr.entity_id = $1
                ORDER BY r.game_date DESC
                LIMIT $2
            """, entity_id, limit)
        else:
            rows = await conn.fetch("""
                SELECT r.game_date, r.season, r.home_score, r.away_score, r.metadata,
                       h.name as home_team, a.name as away_team
                FROM results r
                LEFT JOIN entities h ON h.id = r.home_entity_id
                LEFT JOIN entities a ON a.id = r.away_entity_id
                WHERE r.home_entity_id = $1 OR r.away_entity_id = $1
                ORDER BY r.game_date DESC
                LIMIT $2
            """, entity_id, limit)
        
        return {
            "entity": entity["name"],
            "sport": sport,
            "count": len(rows),
            "history": [dict(row) for row in rows]
        }
    finally:
        await conn.close()


class PredictionRecord(BaseModel):
    sport: str
    entity_name: str
    task: str  # classification or regression
    prediction: float
    probability: Optional[float] = None
    confidence: Optional[str] = None
    input_features: Optional[dict] = None


@router.post("/predictions")
async def store_prediction(prediction: PredictionRecord):
    """Store a prediction in the database for tracking."""
    conn = await get_db_connection()
    try:
        # Get sport ID
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", prediction.sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{prediction.sport}' not found")
        
        # Get or create model record
        model_id = await conn.fetchval(
            """SELECT id FROM models WHERE sport_id = $1 AND task = $2 LIMIT 1""",
            sport_id, prediction.task
        )
        
        if not model_id:
            # Create a model record if it doesn't exist
            model_id = await conn.fetchval(
                """INSERT INTO models (sport_id, task, model_path, is_active) 
                   VALUES ($1, $2, 'auto', true) RETURNING id""",
                sport_id, prediction.task
            )
        
        # Store prediction
        await conn.execute(
            """INSERT INTO predictions (model_id, input_features, prediction, probability, confidence)
               VALUES ($1, $2, $3, $4, $5)""",
            model_id,
            json.dumps(prediction.input_features or {}),
            prediction.prediction,
            prediction.probability,
            prediction.confidence
        )
        
        return {"success": True, "message": "Prediction stored"}
    finally:
        await conn.close()


@router.get("/predictions/{sport}")
async def get_predictions(sport: str, limit: int = 50):
    """Get recent predictions for a sport."""
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        rows = await conn.fetch("""
            SELECT p.*, m.task
            FROM predictions p
            JOIN models m ON m.id = p.model_id
            WHERE m.sport_id = $1
            ORDER BY p.created_at DESC
            LIMIT $2
        """, sport_id, limit)
        
        return [dict(row) for row in rows]
    finally:
        await conn.close()



# ============================================
# NEW WORKFLOW FOR KAGGLE DATA
# ============================================
"""
OLD WORKFLOW (CSV files):
1. User clicks "Update Data" in UI
2. Kaggle API downloads CSV to data/{sport}/
3. Python loads CSV on each API request
4. Memory-heavy, slow for large files

NEW WORKFLOW (PostgreSQL):
1. User clicks "Update Data" in UI
2. Kaggle API downloads CSV to data/{sport}/
3. POST /db/import/kaggle/{sport} called
4. Background task imports CSV to PostgreSQL
5. Python queries PostgreSQL (fast, indexed)
6. CSV files can be deleted after import

BENEFITS:
- Faster queries (indexed)
- Less memory usage
- Concurrent access
- Mobile-ready
"""
