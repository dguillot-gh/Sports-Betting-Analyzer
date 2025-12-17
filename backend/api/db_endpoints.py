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
