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
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# Import status tracking (in-memory for background task progress)
import_status = {
    "nascar_rda": {
        "status": "idle",  # idle, running, completed, failed
        "started_at": None,
        "completed_at": None,
        "progress": [],
        "result": None,
        "error": None
    },
    "nfl": {
        "status": "idle",
        "started_at": None,
        "completed_at": None,
        "progress": [],
        "result": None,
        "error": None
    },
    "nba": {
        "status": "idle",
        "started_at": None,
        "completed_at": None,
        "progress": [],
        "result": None,
        "error": None
    }
}

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


async def ensure_sport_exists(conn, sport: str) -> int:
    """Ensure a sport exists in the database and return its ID. Creates if missing."""
    sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
    if not sport_id:
        # Auto-create the sport entry
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) VALUES ($1, '{}') RETURNING id""",
            sport
        )
        logger.info(f"Auto-created sport entry for: {sport}")
    return sport_id


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


@router.post("/import/nascar/rda")
async def import_nascar_rda(
    background_tasks: BackgroundTasks,
    series: str = None,
    year_start: int = 2012,
    year_end: int = None,
    clear_existing: bool = False
):
    """
    Import NASCAR data directly from RDA files.
    
    Args:
        series: Optional series filter ('cup', 'xfinity', 'trucks', or None for all)
        year_start: Start year (default: 2012)
        year_end: End year (default: current year)
        clear_existing: Clear existing NASCAR data before import
    """
    from datetime import datetime
    
    if year_end is None:
        year_end = datetime.now().year
    
    # Validate series
    valid_series = [None, 'cup', 'xfinity', 'trucks', 'all']
    if series not in valid_series:
        raise HTTPException(status_code=400, detail=f"Invalid series. Must be one of: {valid_series}")
    
    # Update status and start background import
    import_status["nascar_rda"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": [f"Import started for {series or 'all'} ({year_start}-{year_end})"],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_rda_import, series, year_start, year_end, clear_existing)
    
    return {
        "status": "started",
        "message": f"RDA import started for NASCAR {series or 'all'} ({year_start}-{year_end})",
        "year_range": f"{year_start}-{year_end}",
        "series": series or "all",
        "clear_existing": clear_existing
    }


@router.get("/import/nascar/status")
async def get_nascar_import_status():
    """Get the current status of NASCAR RDA import."""
    return import_status["nascar_rda"]


async def run_rda_import(series: str, year_start: int, year_end: int, clear_existing: bool):
    """Background task for RDA import."""
    logger.info(f"Starting RDA import: series={series}, years={year_start}-{year_end}, clear={clear_existing}")
    
    try:
        if clear_existing:
            import_status["nascar_rda"]["progress"].append("Clearing existing data...")
            # Clear existing NASCAR data
            conn = await get_db_connection()
            try:
                sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
                if sport_id:
                    if series and series != 'all':
                        await conn.execute("DELETE FROM results WHERE sport_id = $1 AND series = $2", sport_id, series)
                        await conn.execute("DELETE FROM stats WHERE series = $1", series)
                        await conn.execute("DELETE FROM entities WHERE sport_id = $1 AND series = $2", sport_id, series)
                        import_status["nascar_rda"]["progress"].append(f"Cleared existing {series} data")
                    else:
                        await conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
                        await conn.execute("DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)", sport_id)
                        await conn.execute("DELETE FROM entities WHERE sport_id = $1", sport_id)
                        import_status["nascar_rda"]["progress"].append("Cleared all NASCAR data")
            finally:
                await conn.close()
        
        import_status["nascar_rda"]["progress"].append("Starting RDA file import...")
        
        # Run RDA import
        from scripts.rda_importer import import_nascar_rda
        result = await import_nascar_rda(
            series=series if series and series != 'all' else None,
            year_start=year_start,
            year_end=year_end
        )
        
        # Update status on completion
        import_status["nascar_rda"]["status"] = "completed"
        import_status["nascar_rda"]["completed_at"] = datetime.now().isoformat()
        import_status["nascar_rda"]["result"] = result
        
        # Add summary to progress
        if result.get("series_results"):
            for sr in result["series_results"]:
                import_status["nascar_rda"]["progress"].append(
                    f"✅ {sr['series']}: {sr['results_imported']} results, {sr['stats_computed']} stats"
                )
        import_status["nascar_rda"]["progress"].append("Import complete!")
        
        logger.info(f"RDA import complete: {result}")
    except Exception as e:
        import_status["nascar_rda"]["status"] = "failed"
        import_status["nascar_rda"]["completed_at"] = datetime.now().isoformat()
        import_status["nascar_rda"]["error"] = str(e)
        import_status["nascar_rda"]["progress"].append(f"❌ Error: {e}")
        logger.error(f"RDA import failed: {e}")
        raise


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
        # Auto-create sport entry if it doesn't exist
        sport_id = await ensure_sport_exists(conn, sport)
        
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
        # Auto-create sport entry if it doesn't exist
        sport_id = await ensure_sport_exists(conn, sport)
        
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
        
        # For NASCAR, get available seasons from results (stats table is empty)
        if sport == "nascar":
            seasons = await conn.fetch("""
                SELECT DISTINCT season FROM results 
                WHERE sport_id = $1 
                  AND metadata->>'driver_id' = $2::text
                  AND season IS NOT NULL
                  AND ($3::text IS NULL OR series = $3)
                ORDER BY season DESC
            """, sport_id, str(entity_id), series)
        else:
            seasons = await conn.fetch("""
                SELECT DISTINCT season FROM stats 
                WHERE entity_id = $1 AND season IS NOT NULL
                ORDER BY season DESC
            """, entity_id)
        available_seasons = [row["season"] for row in seasons]
        
        # For NASCAR, compute stats from results metadata
        stats_by_season = {}
        if sport == "nascar":
            # Get all results for this driver
            all_results = await conn.fetch("""
                SELECT season, metadata
                FROM results
                WHERE sport_id = $1 
                  AND metadata->>'driver_id' = $2::text
                  AND ($3::text IS NULL OR series = $3)
            """, sport_id, str(entity_id), series)
            
            # Organize by season and compute stats
            season_data = {}
            for row in all_results:
                s = str(row["season"]) if row["season"] else "unknown"
                if s not in season_data:
                    season_data[s] = []
                
                # Parse metadata
                try:
                    meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                    if meta:
                        season_data[s].append(meta)
                except:
                    pass
            
            # Compute aggregated stats for each season
            for s, races in season_data.items():
                finishes = [r.get("finish") for r in races if r.get("finish") is not None]
                starts = [r.get("start") for r in races if r.get("start") is not None]
                
                if finishes:
                    stats_by_season[s] = {
                        "races": len(finishes),
                        "wins": sum(1 for f in finishes if f == 1),
                        "top_5": sum(1 for f in finishes if f <= 5),
                        "top_10": sum(1 for f in finishes if f <= 10),
                        "avg_finish": round(sum(finishes) / len(finishes), 1),
                        "best_finish": min(finishes),
                        "poles": sum(1 for s in starts if s == 1),
                        "avg_start": round(sum(starts) / len(starts), 1) if starts else None,
                    }
        else:
            # Get stats from stats table for other sports
            stats_query = """
                SELECT stat_type, season, stats
                FROM stats
                WHERE entity_id = $1
            """
            if season:
                stats_query += f" AND season = {season}"
            stats_query += " ORDER BY season DESC, stat_type"
            
            stats_rows = await conn.fetch(stats_query, entity_id)
            
            # Organize stats by season
            for row in stats_rows:
                s = str(row["season"]) if row["season"] else "career"
                if s not in stats_by_season:
                    stats_by_season[s] = {}
                # stats is a JSONB object, merge it into the season dict
                if row["stats"]:
                    try:
                        stat_data = json.loads(row["stats"]) if isinstance(row["stats"], str) else row["stats"]
                        stats_by_season[s].update(stat_data)
                    except:
                        stats_by_season[s][row["stat_type"]] = row["stats"]
        
        # Get recent results (last 10)
        if sport == "nascar":
            # NASCAR: results table has driver data in metadata (driver_id, finish, start)
            results = await conn.fetch("""
                SELECT r.game_date, r.season, r.series, r.track, r.metadata
                FROM results r
                WHERE r.sport_id = $1 
                  AND r.metadata->>'driver_id' = $2::text
                  AND ($3::text IS NULL OR r.series = $3)
                ORDER BY r.game_date DESC, r.season DESC
                LIMIT 10
            """, sport_id, str(entity_id), series)
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
            # NASCAR: query results table with metadata containing driver_id
            rows = await conn.fetch("""
                SELECT r.game_date, r.season, r.series, r.track, r.metadata
                FROM results r
                WHERE r.sport_id = $1 
                  AND r.metadata->>'driver_id' = $2::text
                ORDER BY r.season DESC, r.game_date DESC
                LIMIT $3
            """, sport_id, str(entity_id), limit)
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


# ============================================
# RACE RESULTS ENDPOINTS
# ============================================

@router.get("/races/{sport}/list")
async def get_race_results_list(
    sport: str,
    series: str = None,
    season: int = None,
    track: str = None,
    driver: str = None,
    finish_max: int = None,  # For filtering wins (finish_max=1) or top 5 (finish_max=5)
    limit: int = 100,
    offset: int = 0
):
    """
    Get race results with filters.
    Filter by series, season, track, driver name, or finish position.
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Build dynamic query
        query = """
            SELECT r.id, r.season, r.series, r.track, r.metadata
            FROM results r
            WHERE r.sport_id = $1
        """
        params = [sport_id]
        param_count = 1
        
        if series:
            param_count += 1
            query += f" AND r.series = ${param_count}"
            params.append(series)
        
        if season:
            param_count += 1
            query += f" AND r.season = ${param_count}"
            params.append(season)
        
        if track:
            param_count += 1
            query += f" AND LOWER(r.track) LIKE LOWER(${param_count})"
            params.append(f"%{track}%")
        
        if driver:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'driver_name') LIKE LOWER(${param_count})"
            params.append(f"%{driver}%")
        
        if finish_max:
            param_count += 1
            query += f" AND (r.metadata->>'finish')::int <= ${param_count}"
            params.append(finish_max)
        
        # Order and paginate
        query += f" ORDER BY r.season DESC, (r.metadata->>'race_num')::int DESC NULLS LAST"
        param_count += 1
        query += f" LIMIT ${param_count}"
        params.append(limit)
        param_count += 1
        query += f" OFFSET ${param_count}"
        params.append(offset)
        
        results = await conn.fetch(query, *params)
        
        # Get total count for pagination
        count_query = """
            SELECT COUNT(*) FROM results r WHERE r.sport_id = $1
        """
        count_params = [sport_id]
        if series:
            count_query += " AND r.series = $2"
            count_params.append(series)
        if season:
            count_query += f" AND r.season = ${len(count_params)+1}"
            count_params.append(season)
        if track:
            count_query += f" AND LOWER(r.track) LIKE LOWER(${len(count_params)+1})"
            count_params.append(f"%{track}%")
        if driver:
            count_query += f" AND LOWER(r.metadata->>'driver_name') LIKE LOWER(${len(count_params)+1})"
            count_params.append(f"%{driver}%")
        if finish_max:
            count_query += f" AND (r.metadata->>'finish')::int <= ${len(count_params)+1}"
            count_params.append(finish_max)
        
        total_count = await conn.fetchval(count_query, *count_params)
        
        # Format results
        race_results = []
        for row in results:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            race_results.append({
                "id": row["id"],
                "season": row["season"],
                "series": row["series"],
                "track": row["track"],
                "race_num": meta.get("race_num"),
                "race_name": meta.get("race_name"),
                "driver": meta.get("driver_name"),
                "finish": meta.get("finish"),
                "start": meta.get("start"),
                "led": meta.get("led"),
                "laps": meta.get("laps"),
                "pts": meta.get("pts"),
                "status": meta.get("status"),
                "team": meta.get("team"),
                "make": meta.get("make"),
                "rating": meta.get("rating"),
            })
        
        return {
            "results": race_results,
            "total": total_count,
            "limit": limit,
            "offset": offset,
        }
    finally:
        await conn.close()


@router.get("/races/{sport}/tracks")
async def get_unique_tracks(sport: str, series: str = None, season: int = None):
    """
    Get list of unique tracks for filter dropdown.
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        query = """
            SELECT DISTINCT track FROM results 
            WHERE sport_id = $1 AND track IS NOT NULL
        """
        params = [sport_id]
        
        if series:
            query += " AND series = $2"
            params.append(series)
        
        if season:
            query += f" AND season = ${len(params)+1}"
            params.append(season)
        
        query += " ORDER BY track"
        
        rows = await conn.fetch(query, *params)
        return {"tracks": [row["track"] for row in rows if row["track"]]}
    finally:
        await conn.close()


@router.get("/races/{sport}/seasons")
async def get_available_seasons(sport: str, series: str = None):
    """
    Get list of available seasons for filter dropdown.
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        query = """
            SELECT DISTINCT season FROM results 
            WHERE sport_id = $1 AND season IS NOT NULL
        """
        params = [sport_id]
        
        if series:
            query += " AND series = $2"
            params.append(series)
        
        query += " ORDER BY season DESC"
        
        rows = await conn.fetch(query, *params)
        return {"seasons": [row["season"] for row in rows]}
    finally:
        await conn.close()


@router.get("/races/{sport}/drivers")
async def get_drivers_with_results(sport: str, series: str = None, season: int = None, search: str = None, limit: int = 50):
    """
    Get list of drivers with results for filter dropdown.
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        query = """
            SELECT DISTINCT metadata->>'driver_name' as driver_name
            FROM results 
            WHERE sport_id = $1 
              AND metadata->>'driver_name' IS NOT NULL
        """
        params = [sport_id]
        
        if series:
            query += " AND series = $2"
            params.append(series)
        
        if season:
            query += f" AND season = ${len(params)+1}"
            params.append(season)
        
        if search:
            query += f" AND LOWER(metadata->>'driver_name') LIKE LOWER(${len(params)+1})"
            params.append(f"%{search}%")
        
        query += " ORDER BY driver_name LIMIT $" + str(len(params)+1)
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        return {"drivers": [row["driver_name"] for row in rows if row["driver_name"]]}
    finally:
        await conn.close()


# =============================================================================
# NFL Import Endpoints
# =============================================================================

@router.post("/import/nfl")
async def import_nfl_data(
    background_tasks: BackgroundTasks,
    clear_existing: bool = False
):
    """
    Start NFL data import from nflverse.
    Downloads data from GitHub releases and imports to PostgreSQL.
    """
    # Check if already running
    if import_status["nfl"]["status"] == "running":
        return {
            "status": "already_running",
            "message": "NFL import is already in progress",
            "started_at": import_status["nfl"]["started_at"]
        }
    
    # Update status and start background import
    import_status["nfl"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": ["NFL import started..."],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_nfl_import, clear_existing)
    
    return {
        "status": "started",
        "message": "NFL data import started (nflverse + Kaggle)",
        "clear_existing": clear_existing
    }


@router.get("/import/nfl/status")
async def get_nfl_import_status():
    """Get the current status of NFL import."""
    return import_status["nfl"]


async def run_nfl_import(clear_existing: bool):
    """Background task for NFL import."""
    try:
        from scripts.nfl_importer import import_all_nfl
        
        def progress_callback(msg):
            import_status["nfl"]["progress"].append(msg)
            logger.info(f"NFL Import: {msg}")
        
        result = await import_all_nfl(
            clear_existing=clear_existing,
            progress_callback=progress_callback
        )
        
        import_status["nfl"]["status"] = "completed" if result.get("status") == "success" else "failed"
        import_status["nfl"]["completed_at"] = datetime.now().isoformat()
        import_status["nfl"]["result"] = result
        
        if result.get("errors"):
            import_status["nfl"]["error"] = "; ".join(result["errors"])
        
    except Exception as e:
        logger.error(f"NFL import failed: {e}")
        import_status["nfl"]["status"] = "failed"
        import_status["nfl"]["completed_at"] = datetime.now().isoformat()
        import_status["nfl"]["error"] = str(e)
        import_status["nfl"]["progress"].append(f"❌ Error: {e}")


# =============================================================================
# NBA Import Endpoints
# =============================================================================

@router.post("/import/nba")
async def import_nba_data(
    background_tasks: BackgroundTasks,
    clear_existing: bool = False
):
    """
    Start NBA data import from hoopR and Kaggle.
    """
    # Check if already running
    if import_status["nba"]["status"] == "running":
        return {
            "status": "already_running",
            "message": "NBA import is already in progress",
            "started_at": import_status["nba"]["started_at"]
        }
    
    # Update status and start background import
    import_status["nba"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": ["NBA import started..."],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_nba_import, clear_existing)
    
    return {
        "status": "started",
        "message": "NBA data import started (hoopR + Kaggle)",
        "clear_existing": clear_existing
    }


@router.get("/import/nba/status")
async def get_nba_import_status():
    """Get the current status of NBA import."""
    return import_status["nba"]


async def run_nba_import(clear_existing: bool):
    """Background task for NBA import."""
    try:
        from scripts.nba_importer import import_all_nba
        
        def progress_callback(msg):
            import_status["nba"]["progress"].append(msg)
            logger.info(f"NBA Import: {msg}")
        
        result = await import_all_nba(
            clear_existing=clear_existing,
            progress_callback=progress_callback
        )
        
        import_status["nba"]["status"] = "completed" if result.get("status") == "success" else "failed"
        import_status["nba"]["completed_at"] = datetime.now().isoformat()
        import_status["nba"]["result"] = result
        
        if result.get("errors"):
            import_status["nba"]["error"] = "; ".join(result["errors"])
        
    except Exception as e:
        logger.error(f"NBA import failed: {e}")
        import_status["nba"]["status"] = "failed"
        import_status["nba"]["completed_at"] = datetime.now().isoformat()
        import_status["nba"]["error"] = str(e)
        import_status["nba"]["progress"].append(f"❌ Error: {e}")


# =============================================================================
# NFL/NBA Profile Endpoints
# =============================================================================

@router.get("/profiles/{sport}/list")
async def get_sport_profiles(
    sport: str,
    entity_type: str = "player",
    search: str = None,
    limit: int = 100
):
    """Get list of players/teams for a sport."""
    if sport not in ["nfl", "nba", "nascar"]:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        query = """
            SELECT id, name, type, series, metadata
            FROM entities
            WHERE sport_id = $1 AND type = $2
        """
        params = [sport_id, entity_type]
        
        if search:
            query += " AND LOWER(name) LIKE LOWER($3)"
            params.append(f"%{search}%")
        
        query += f" ORDER BY name LIMIT ${len(params)+1}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        
        return {
            "entities": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["type"],
                    "series": row["series"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                }
                for row in rows
            ],
            "count": len(rows)
        }
    finally:
        await conn.close()


@router.get("/profiles/{sport}/{name}")
async def get_player_profile(sport: str, name: str):
    """Get detailed player profile with stats."""
    if sport not in ["nfl", "nba", "nascar"]:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Get player entity
        entity = await conn.fetchrow(
            """SELECT id, name, type, series, metadata
               FROM entities
               WHERE sport_id = $1 AND LOWER(name) = LOWER($2)
               LIMIT 1""",
            sport_id, name
        )
        
        if not entity:
            raise HTTPException(status_code=404, detail=f"Player '{name}' not found")
        
        # Get stats
        stats_rows = await conn.fetch(
            """SELECT season, stat_type, stats
               FROM stats
               WHERE entity_id = $1
               ORDER BY season DESC""",
            entity["id"]
        )
        
        # Format stats by season
        stats = {}
        for row in stats_rows:
            season = row["season"]
            if season not in stats:
                stats[season] = {}
            stats[season].update(json.loads(row["stats"]) if row["stats"] else {})
        
        # Get recent games (from results)
        recent_games = await conn.fetch(
            """SELECT season, metadata
               FROM results
               WHERE sport_id = $1 
                 AND (metadata->>'player_name' = $2 OR metadata->>'player_id' = $3)
               ORDER BY season DESC, (metadata->>'week')::int DESC NULLS LAST
               LIMIT 10""",
            sport_id, name, name
        )
        
        return {
            "id": entity["id"],
            "name": entity["name"],
            "type": entity["type"],
            "series": entity["series"],
            "metadata": json.loads(entity["metadata"]) if entity["metadata"] else {},
            "stats": stats,
            "recent_games": [
                {
                    "season": row["season"],
                    **(json.loads(row["metadata"]) if row["metadata"] else {})
                }
                for row in recent_games
            ]
        }
    finally:
        await conn.close()


# =============================================================================
# Game Results Endpoints (NFL/NBA)
# =============================================================================

@router.get("/games/{sport}/list")
async def get_game_results(
    sport: str,
    season: int = None,
    team: str = None,
    player: str = None,
    week: int = None,
    limit: int = 100
):
    """Get game results for NFL or NBA."""
    if sport not in ["nfl", "nba"]:
        raise HTTPException(status_code=400, detail=f"Invalid sport for games: {sport}")
    
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        query = """
            SELECT id, season, series, metadata
            FROM results
            WHERE sport_id = $1
        """
        params = [sport_id]
        
        if season:
            query += f" AND season = ${len(params)+1}"
            params.append(season)
        
        if player:
            query += f" AND (metadata->>'player_name' ILIKE ${len(params)+1} OR metadata->>'player_id' = ${len(params)+1})"
            params.append(f"%{player}%")
        
        if week and sport == "nfl":
            query += f" AND (metadata->>'week')::int = ${len(params)+1}"
            params.append(week)
        
        query += f" ORDER BY season DESC, (metadata->>'week')::int DESC NULLS LAST LIMIT ${len(params)+1}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        
        return {
            "results": [
                {
                    "id": row["id"],
                    "season": row["season"],
                    "series": row["series"],
                    **(json.loads(row["metadata"]) if row["metadata"] else {})
                }
                for row in rows
            ],
            "count": len(rows)
        }
    finally:
        await conn.close()


@router.get("/games/{sport}/seasons")
async def get_available_seasons(sport: str):
    """Get list of available seasons for a sport."""
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            return {"seasons": []}
        
        rows = await conn.fetch(
            """SELECT DISTINCT season FROM results 
               WHERE sport_id = $1 AND season IS NOT NULL
               ORDER BY season DESC""",
            sport_id
        )
        return {"seasons": [row["season"] for row in rows]}
    finally:
        await conn.close()
