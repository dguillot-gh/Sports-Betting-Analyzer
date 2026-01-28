"""
Database Import API Endpoints
=============================

Add these endpoints to app.py for database import functionality.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
# import asyncpg  <-- Moved to local function scope
# import pandas as pd  <-- Moved to local function scope
import json
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Database URL
from src.config import DATABASE_URL

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
    },
    "ncaab": {
        "status": "idle",
        "started_at": None,
        "completed_at": None,
        "progress": [],
        "result": None,
        "error": None
    },
    "baseball": {
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
    source: str = "csv"  # 'csv' or 'parquet'
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
        import asyncpg
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
    """Get import history from scheduler logs."""
    conn = await get_db_connection()
    try:
        # Check if import_logs exists
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'import_logs')"
        )
        
        if not table_exists:
            return []
            
        rows = await conn.fetch("""
            SELECT id, sport as topic, status, 
                   start_time as date, 
                   rows_imported as details,
                   error_message
            FROM import_logs
            ORDER BY start_time DESC
            LIMIT 50
        """)
        
        # Format for frontend (frontend expects: date, topic, details)
        history = []
        for row in rows:
            details = {
                "status": row['status'],
                "rows": row['details'],
                "error": row['error_message']
            }
            history.append({
                "date": row['date'].isoformat() if row['date'] else None,
                "topic": row['topic'],
                "details": details
            })
            
        return history
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []
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
    """Background task to run full data import pipeline with status tracking."""
    logger.info(f"Running manual import for {sport}...")
    
    # Initialize status
    import_status[sport] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": [f"Starting {sport} import..."],
        "result": None,
        "error": None
    }
    
    conn = None
    log_id = None
    
    try:
        conn = await get_db_connection()
        
        # Create log entry
        try:
            log_id = await conn.fetchval("""
                INSERT INTO import_logs (sport, status, start_time)
                VALUES ($1, 'IN_PROGRESS', NOW())
                RETURNING id
            """, sport)
        except Exception as e:
            logger.warning(f"Could not create import log: {e}")

        # Progress callback to update global state
        def update_progress(msg):
            if sport in import_status:
                import_status[sport]["progress"].append(msg)
                # Keep log size manageable
                if len(import_status[sport]["progress"]) > 100:
                    import_status[sport]["progress"] = import_status[sport]["progress"][-100:]

        result = None
        if sport == 'nba':
            from scripts.nba_importer import import_all_nba
            result = await import_all_nba(clear_existing=False, progress_callback=update_progress)
        elif sport == 'nfl':
            from scripts.nfl_importer import import_all_nfl
            result = await import_all_nfl(clear_existing=False, progress_callback=update_progress)
        else:
            from scripts.migrate_data import run_migration
            await run_migration(sport)
            result = {"status": "completed", "message": "Legacy migration ran"}

        # Success handling
        import_status[sport]["status"] = "completed"
        import_status[sport]["completed_at"] = datetime.now().isoformat()
        import_status[sport]["result"] = result
        import_status[sport]["progress"].append("Import completed successfully!")
        
        # Calculate rows based on result format
        rows = 0
        if isinstance(result, dict):
             # Sum up all "imported" keys we know about across all sports
             count_keys = [
                 "games_imported", "players_imported", "stats_computed", 
                 "schedules_imported", "weekly_stats_imported", "season_stats_imported",
                 "imported_teams", "box_scores_imported", "br_stats_imported", 
                 "br_stats_computed", "games_processed", "rows"
             ]
             for key in count_keys:
                 rows += result.get(key, 0)
        
        # Update log
        if log_id:
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'SUCCESS', end_time = NOW(), rows_imported = $2
                WHERE id = $1
            """, log_id, rows)
            
    except Exception as e:
        logger.error(f"Manual import for {sport} failed: {e}")
        
        # Failure handling
        import_status[sport]["status"] = "failed"
        import_status[sport]["completed_at"] = datetime.now().isoformat()
        import_status[sport]["error"] = str(e)
        import_status[sport]["progress"].append(f"Error: {str(e)}")
        
        # Update log
        if log_id and conn:
            try:
                await conn.execute("""
                    UPDATE import_logs 
                    SET status = 'FAILED', end_time = NOW(), error_message = $2
                    WHERE id = $1
                """, log_id, str(e))
            except:
                pass
    finally:
        if conn:
            await conn.close()


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
    """Background task for RDA import with DB logging."""
    logger.info(f"Starting RDA import: series={series}, years={year_start}-{year_end}, clear={clear_existing}")
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        # 1. Create IN_PROGRESS log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('nascar', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        if clear_existing:
            import_status["nascar_rda"]["progress"].append("Clearing existing data...")
            # Reuse existing connection or create new one for clear
            clear_conn = await get_db_connection()
            try:
                sport_id = await clear_conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
                if sport_id:
                    if series and series != 'all':
                        await clear_conn.execute("DELETE FROM results WHERE sport_id = $1 AND series = $2", sport_id, series)
                        await clear_conn.execute("DELETE FROM stats WHERE series = $1", series)
                        await clear_conn.execute("DELETE FROM entities WHERE sport_id = $1 AND series = $2", sport_id, series)
                        import_status["nascar_rda"]["progress"].append(f"Cleared existing {series} data")
                    else:
                        await clear_conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
                        await clear_conn.execute("DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)", sport_id)
                        await clear_conn.execute("DELETE FROM entities WHERE sport_id = $1", sport_id)
                        import_status["nascar_rda"]["progress"].append("Cleared all NASCAR data")
            finally:
                await clear_conn.close()
        
        import_status["nascar_rda"]["progress"].append("Starting RDA file import...")
        
        # 2. Run RDA import
        from scripts.rda_importer import import_nascar_rda
        result = await import_nascar_rda(
            series=series if series and series != 'all' else None,
            year_start=year_start,
            year_end=year_end
        )
        
        # 3. Comprehensive Row Count
        rows = 0
        if result.get("series_results"):
            for sr in result["series_results"]:
                rows += sr.get("results_imported", 0)
                rows += sr.get("stats_computed", 0)
        
        status = "COMPLETED" if result.get("status") == "success" else "FAILED"
        import_status["nascar_rda"]["status"] = status.lower()
        import_status["nascar_rda"]["completed_at"] = datetime.now().isoformat()
        import_status["nascar_rda"]["result"] = {**result, "rows": rows}
        
        # Add summary to progress
        if result.get("series_results"):
            for sr in result["series_results"]:
                import_status["nascar_rda"]["progress"].append(
                    f"✅ {sr['series']}: {sr['results_imported']} results, {sr['stats_computed']} stats"
                )
        import_status["nascar_rda"]["progress"].append(f"Import {status.lower()}!")
        
        # 4. Update DB Log
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = result.get("error") if not result.get("success") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
    except Exception as e:
        logger.error(f"RDA import failed: {e}")
        import_status["nascar_rda"]["status"] = "failed"
        import_status["nascar_rda"]["completed_at"] = datetime.now().isoformat()
        import_status["nascar_rda"]["error"] = str(e)
        import_status["nascar_rda"]["progress"].append(f"❌ Error: {e}")
        
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        if conn:
            await conn.close()
        
@router.post("/import/ncaab")
async def import_ncaab(background_tasks: BackgroundTasks, start_year: int = Query(2018), end_year: int = Query(2025)):
    """Start NCAAB data import in the background."""
    import_status["ncaab"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": [f"Import started for {start_year}-{end_year}"],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_ncaab_import, start_year, end_year)
    
    return {
        "status": "started",
        "message": f"NCAAB import started for {start_year}-{end_year}",
        "years": f"{start_year}-{end_year}"
    }


@router.get("/import/ncaab/status")
async def get_ncaab_import_status():
    """Get the current status of NCAAB import."""
    return import_status["ncaab"]


async def run_ncaab_import(start_year: int, end_year: int):
    """Background task to run NCAAB import via R script with DB logging."""
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        from scripts.ncaab_importer import import_ncaab_data
        
        # 1. Create IN_PROGRESS log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('ncaab', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        import_status["ncaab"]["progress"].append("Calling hybrid NCAAB importer (hoopR)...")
        result = await import_ncaab_data(start_year, end_year)
        
        # 2. Comprehensive Row Count (NCAAB often returns generic success)
        # Using games_processed or similar if available, else placeholder 1
        rows = result.get("games_processed", 1) if result.get("success") else 0
        
        status = "COMPLETED" if result.get("success") else "FAILED"
        import_status["ncaab"]["status"] = status.lower()
        import_status["ncaab"]["result"] = {**result, "rows": rows}
        import_status["ncaab"]["progress"].append(f"✅ Import {status.lower()}!")
        
        # 3. Update DB Log
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = result.get("error") if not result.get("success") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
    except Exception as e:
        logger.error(f"NCAAB import failed: {e}")
        import_status["ncaab"]["status"] = "failed"
        import_status["ncaab"]["error"] = str(e)
        import_status["ncaab"]["progress"].append(f"❌ Critical Error: {e}")
        
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        import_status["ncaab"]["completed_at"] = datetime.now().isoformat()
        if conn:
            await conn.close()



@router.post("/import/college-baseball")
async def import_college_baseball(
    background_tasks: BackgroundTasks, 
    start_year: int = Query(0), 
    end_year: int = Query(0),
    division: int = Query(0, description="NCAA Division (1, 2, or 3). Use 0 for ALL/Bulk."),
    source: str = Query("auto") # auto, python, r, both
):
    """Start College Baseball data import in the background."""
    div_label = f"D{division}" if division > 0 else "ALL Divisions"
    import_status["baseball"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": [f"Import started for {div_label} {start_year}-{end_year}"],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_college_baseball_import_task, start_year, end_year, division, source)
    
    return {
        "status": "started",
        "message": f"College Baseball import started for {div_label} {start_year}-{end_year} ({source})",
        "years": f"{start_year}-{end_year}",
        "division": division
    }


@router.get("/import/college-baseball/status")
async def get_college_baseball_import_status():
    """Get the current status of College Baseball import."""
    return import_status["baseball"]


async def run_college_baseball_import_task(start_year: int, end_year: int, division: int, source: str):
    """Background task to run College Baseball import."""
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        from scripts.college_baseball_importer import run_college_baseball_import
        
        # 1. Create IN_PROGRESS log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('college_baseball', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        # Reset transient status for this run
        if "baseball" not in import_status:
            import_status["baseball"] = {"progress": []}
        else:
            import_status["baseball"]["progress"] = []
            
        import_status["baseball"]["status"] = "running"
        import_status["baseball"]["progress"].append(f"Starting import using source={source}")
        
        total_rows = 0
        final_result = {}
        
        # Smart Year Range: Priority 2024 (full baseline) and 2025 (transition)
        if start_year == 0 or end_year == 0:
            years_to_import = [2024, 2025]
            import_status["baseball"]["progress"].append(f"Auto-detected stable year range: {years_to_import}")
        else:
            years_to_import = range(start_year, end_year + 1)
            
        for year in years_to_import:
            import_status["baseball"]["progress"].append(f"Importing {year}...")
            
            # Call the unified importer (supports division=0)
            result = await run_college_baseball_import(division=division, year=year, source=source)
            
            if result.get("success"):
                rows = result.get("total_teams", 0)
                total_rows += rows
                import_status["baseball"]["progress"].append(f"✅ {year}: Imported {rows} teams from divisions {result.get('divisions')}")
            else:
                err = result.get("message", "Unknown error")
                import_status["baseball"]["progress"].append(f"⚠️ {year}: {err}")
                
            final_result[year] = result
        
        # Determine final status
        if total_rows == 0 and any("⚠️" in msg for msg in import_status["baseball"]["progress"]):
            status = "FAILED"
            import_status["baseball"]["status"] = "failed"
            import_status["baseball"]["progress"].append("❌ Import failed: No data was collected for any year.")
        else:
            status = "COMPLETED"
            import_status["baseball"]["status"] = "completed"
            import_status["baseball"]["progress"].append(f"✅ Import Complete! Total teams: {total_rows}")
        
        # 3. Update DB Log
        duration = (datetime.now() - start_time).total_seconds()
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4
            WHERE id = $1
        """, log_id, status, duration, total_rows)
        
    except Exception as e:
        logger.error(f"College Baseball import failed: {e}")
        import_status["baseball"]["status"] = "failed"
        import_status["baseball"]["error"] = str(e)
        import_status["baseball"]["progress"].append(f"❌ Critical Error: {e}")
        
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        import_status["baseball"]["completed_at"] = datetime.now().isoformat()
        if conn:
            await conn.close()


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
# GAME SCHEDULE ENDPOINTS (NFL/NBA)
# =============================================================================

@router.get("/games/{sport}/schedule")
async def get_game_schedule(
    sport: str,
    season: int = None,
    week: int = None,
    team: str = None,
    limit: int = 50,
    offset: int = 0
):
    """
    Get game schedule/results for NFL or NBA.
    Returns actual game matchups with scores.
    
    Args:
        sport: 'nfl' or 'nba'
        season: Filter by season year
        week: Filter by week (NFL only)
        team: Filter by team abbreviation
        limit: Max results
        offset: Pagination offset
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Query for schedule data (stored as series='nfl_schedule' or 'nba_schedule')
        schedule_series = f"{sport}_schedule"
        
        query = """
            SELECT r.id, r.season, r.metadata
            FROM results r
            WHERE r.sport_id = $1 AND r.series = $2
        """
        params = [sport_id, schedule_series]
        param_count = 2
        
        if season:
            param_count += 1
            query += f" AND r.season = ${param_count}"
            params.append(season)
        
        if week:
            param_count += 1
            query += f" AND (r.metadata->>'week')::int = ${param_count}"
            params.append(week)
        
        if team:
            param_count += 1
            query += f" AND (LOWER(r.metadata->>'home_team') = LOWER(${param_count}) OR LOWER(r.metadata->>'away_team') = LOWER(${param_count}))"
            params.append(team)
        
        # Order by date/week
        query += " ORDER BY r.season DESC, (r.metadata->>'week')::int DESC NULLS LAST"
        param_count += 1
        query += f" LIMIT ${param_count}"
        params.append(limit)
        param_count += 1
        query += f" OFFSET ${param_count}"
        params.append(offset)
        
        results = await conn.fetch(query, *params)
        
        # Format results
        games = []
        for row in results:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            games.append({
                "game_id": meta.get("game_id"),
                "season": row["season"],
                "week": meta.get("week"),
                "game_date": meta.get("gameday"),
                "game_type": meta.get("game_type"),
                "home_team": meta.get("home_team"),
                "away_team": meta.get("away_team"),
                "home_score": meta.get("home_score"),
                "away_score": meta.get("away_score"),
                "result": meta.get("result"),
                "total": meta.get("total"),
                "overtime": meta.get("overtime"),
                "spread_line": meta.get("spread_line"),
                "total_line": meta.get("total_line"),
                "stadium": meta.get("stadium"),
                "is_completed": meta.get("home_score") is not None and meta.get("away_score") is not None
            })
        
        return {
            "games": games,
            "count": len(games),
            "limit": limit,
            "offset": offset
        }
    finally:
        await conn.close()


@router.get("/games/{sport}/list")
async def get_game_list(
    sport: str,
    season: int = None,
    player: str = None,
    team: str = None,
    limit: int = 500,
    offset: int = 0
):
    """
    Get game-by-game player stats for hit rate calculations.
    Returns weekly/game-level stats with player performance in each game.
    
    Args:
        sport: 'nfl' or 'nba'
        season: Filter by season year
        player: Filter by player name (partial match)
        team: Filter by team abbreviation
        limit: Max results
        offset: Pagination offset
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Determine series based on sport
        series_name = "nfl_weekly" if sport == "nfl" else "nba_game_log"
        
        query = """
            SELECT r.id, r.season, r.metadata
            FROM results r
            WHERE r.sport_id = $1 AND r.series = $2
        """
        params = [sport_id, series_name]
        param_count = 2
        
        if season:
            param_count += 1
            query += f" AND r.season = ${param_count}"
            params.append(season)
        
        if player:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'player_name') LIKE LOWER(${param_count})"
            params.append(f"%{player}%")
        
        if team:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'team') = LOWER(${param_count})"
            params.append(team)
        
        # Order by season, then week/game_date
        if sport == "nfl":
            query += " ORDER BY r.season DESC, (r.metadata->>'week')::int DESC NULLS LAST"
        else:
            query += " ORDER BY r.season DESC, r.metadata->>'game_date' DESC NULLS LAST"
        
        param_count += 1
        query += f" LIMIT ${param_count}"
        params.append(limit)
        param_count += 1
        query += f" OFFSET ${param_count}"
        params.append(offset)
        
        results = await conn.fetch(query, *params)
        
        # Format results
        game_results = []
        for row in results:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            game_results.append({
                "id": row["id"],
                "season": row["season"],
                "week": meta.get("week"),
                "game_date": meta.get("game_date"),
                "player_name": meta.get("player_name"),
                "team": meta.get("team"),
                "position": meta.get("position"),
                # NFL stats
                "pass_yds": meta.get("pass_yds"),
                "pass_td": meta.get("pass_td"),
                "pass_int": meta.get("pass_int"),
                "rush_yds": meta.get("rush_yds"),
                "rush_td": meta.get("rush_td"),
                "rec": meta.get("rec"),
                "rec_yds": meta.get("rec_yds"),
                "rec_td": meta.get("rec_td"),
                # NBA stats
                "pts": meta.get("pts"),
                "reb": meta.get("reb"),
                "ast": meta.get("ast"),
                "stl": meta.get("stl"),
                "blk": meta.get("blk"),
                "fg3": meta.get("fg3m"),  # 3-pointers made
            })
        
        return {
            "results": game_results,
            "count": len(game_results),
            "limit": limit,
            "offset": offset
        }
    finally:
        await conn.close()


@router.get("/stats/{sport}/list")
async def get_stats_list(
    sport: str,
    season: int = None,
    player: str = None,
    team: str = None,
    position: str = None,
    limit: int = 500,
    offset: int = 0
):
    """
    Get season totals/aggregated player stats.
    For NFL: series='nfl', For NBA: series='nba' (season totals, not game-by-game)
    """
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Season stats are stored with series = sport name (e.g., 'nfl', 'nba')
        series_name = sport
        
        query = """
            SELECT r.id, r.season, r.metadata
            FROM results r
            WHERE r.sport_id = $1 AND r.series = $2
        """
        params = [sport_id, series_name]
        param_count = 2
        
        if season:
            param_count += 1
            query += f" AND r.season = ${param_count}"
            params.append(season)
        
        if player:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'player_name') LIKE LOWER(${param_count})"
            params.append(f"%{player}%")
        
        if team:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'team') = LOWER(${param_count})"
            params.append(team)
        
        if position:
            param_count += 1
            query += f" AND LOWER(r.metadata->>'position') = LOWER(${param_count})"
            params.append(position)
        
        query += " ORDER BY r.season DESC, (r.metadata->>'player_name') ASC"
        param_count += 1
        query += f" LIMIT ${param_count}"
        params.append(limit)
        param_count += 1
        query += f" OFFSET ${param_count}"
        params.append(offset)
        
        results = await conn.fetch(query, *params)
        
        # Format results
        stat_results = []
        for row in results:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            stat_results.append({
                "id": row["id"],
                "season": row["season"],
                "player_name": meta.get("player_name"),
                "team": meta.get("team"),
                "position": meta.get("position"),
                "games": meta.get("games"),
                # NFL stats
                "pass_yds": meta.get("pass_yds"),
                "pass_td": meta.get("pass_td"),
                "pass_int": meta.get("pass_int"),
                "rush_yds": meta.get("rush_yds"),
                "rush_td": meta.get("rush_td"),
                "rec": meta.get("rec"),
                "rec_yds": meta.get("rec_yds"),
                "rec_td": meta.get("rec_td"),
                # NBA stats
                "pts": meta.get("pts"),
                "reb": meta.get("reb"),
                "ast": meta.get("ast"),
                "stl": meta.get("stl"),
                "blk": meta.get("blk"),
                "fg3m": meta.get("fg3m"),
            })
        
        return {
            "results": stat_results,
            "count": len(stat_results),
            "limit": limit,
            "offset": offset
        }
    finally:
        await conn.close()


@router.get("/stats/{sport}/seasons")
async def get_stats_seasons(sport: str):
    """Get available seasons for season stats."""
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            return {"seasons": [2025, 2024, 2023, 2022, 2021, 2020]}
        
        # Query stats data for seasons
        rows = await conn.fetch(
            """SELECT DISTINCT season FROM results 
               WHERE sport_id = $1 AND series = $2 AND season IS NOT NULL 
               ORDER BY season DESC""",
            sport_id, sport  # series = sport name for season totals
        )
        
        if rows:
            return {"seasons": [row["season"] for row in rows]}
        
        return {"seasons": [2025, 2024, 2023, 2022, 2021, 2020]}
    finally:
        await conn.close()


@router.get("/games/{sport}/seasons")
async def get_game_seasons(sport: str, series: str = None):
    """Get available seasons for game data. Optionally filter by series."""
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # If series is specified, query that directly
        if series:
            rows = await conn.fetch(
                """SELECT DISTINCT season FROM results 
                   WHERE sport_id = $1 AND series = $2 AND season IS NOT NULL 
                   ORDER BY season DESC""",
                sport_id, series
            )
            if rows:
                return {"seasons": [row["season"] for row in rows]}
            return {"seasons": [2025, 2024, 2023]}
        
        # Check schedule table first
        schedule_series = f"{sport}_schedule"
        rows = await conn.fetch(
            """SELECT DISTINCT season FROM results 
               WHERE sport_id = $1 AND series = $2 AND season IS NOT NULL 
               ORDER BY season DESC""",
            sport_id, schedule_series
        )
        
        if rows:
            return {"seasons": [row["season"] for row in rows]}
        
        # Fallback to stats table
        rows = await conn.fetch(
            """SELECT DISTINCT season FROM stats 
               WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1) AND season IS NOT NULL 
               ORDER BY season DESC""",
            sport_id
        )
        return {"seasons": [row["season"] for row in rows]}
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
        "message": "NFL data import started (nflverse)",
        "clear_existing": clear_existing
    }


@router.get("/import/nfl/status")
async def get_nfl_import_status():
    """Get the current status of NFL import."""
    return import_status["nfl"]


async def run_nfl_import(clear_existing: bool):
    """Background task for NFL import with DB logging."""
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        from scripts.nfl_importer import import_all_nfl
        
        # 1. Create IN_PROGRESS log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('nfl', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        def progress_callback(msg):
            import_status["nfl"]["progress"].append(msg)
            logger.info(f"NFL Import: {msg}")
        
        result = await import_all_nfl(
            clear_existing=clear_existing,
            progress_callback=progress_callback
        )
        
        # 2. Comprehensive Row Count
        rows = (result.get("games_imported", 0) + 
                result.get("players_imported", 0) + 
                result.get("stats_computed", 0) +
                result.get("schedules_imported", 0) +
                result.get("weekly_stats_imported", 0) +
                result.get("season_stats_imported", 0))
        
        status = "COMPLETED" if result.get("status") == "success" else "FAILED"
        import_status["nfl"]["status"] = status.lower()
        import_status["nfl"]["completed_at"] = datetime.now().isoformat()
        import_status["nfl"]["result"] = {**result, "rows": rows}
        
        # 3. Update DB Log
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = "; ".join(result.get("errors", [])) if result.get("errors") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
        if result.get("errors"):
            import_status["nfl"]["error"] = error_msg
        
    except Exception as e:
        logger.error(f"NFL import failed: {e}")
        import_status["nfl"]["status"] = "failed"
        import_status["nfl"]["completed_at"] = datetime.now().isoformat()
        import_status["nfl"]["error"] = str(e)
        import_status["nfl"]["progress"].append(f"❌ Error: {e}")
        
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        if conn:
            await conn.close()


# =============================================================================
# NBA Import Endpoints
# =============================================================================

@router.post("/import/nba")
async def import_nba_data(
    background_tasks: BackgroundTasks,
    clear_existing: bool = False
):
    """
    Start NBA data import from hoopR and stats.nba.com.
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
        "message": "NBA data import started (hoopR + stats.nba.com)",
        "clear_existing": clear_existing
    }


@router.get("/import/nba/status")
async def get_nba_import_status():
    """Get the current status of NBA import."""
    return import_status["nba"]


async def run_nba_import(clear_existing: bool):
    """Background task for NBA import with DB logging."""
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        from scripts.nba_importer import import_all_nba
        
        # 1. Create IN_PROGRESS log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('nba', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        def progress_callback(msg):
            import_status["nba"]["progress"].append(msg)
            logger.info(f"NBA Import: {msg}")
        
        result = await import_all_nba(
            clear_existing=clear_existing,
            progress_callback=progress_callback
        )
        
        # 2. Comprehensive Row Count
        rows = (result.get("games_imported", 0) + 
                result.get("players_imported", 0) + 
                result.get("box_scores_imported", 0) +
                result.get("br_stats_imported", 0) +
                result.get("br_stats_computed", 0) +
                result.get("season_stats_imported", 0))
        
        status = "COMPLETED" if result.get("status") == "success" else "FAILED"
        import_status["nba"]["status"] = status.lower()
        import_status["nba"]["completed_at"] = datetime.now().isoformat()
        import_status["nba"]["result"] = {**result, "rows": rows}
        
        # 3. Update DB Log
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = "; ".join(result.get("errors", [])) if result.get("errors") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
        if result.get("errors"):
            import_status["nba"]["error"] = error_msg
        
    except Exception as e:
        logger.error(f"NBA import failed: {e}")
        import_status["nba"]["status"] = "failed"
        import_status["nba"]["completed_at"] = datetime.now().isoformat()
        import_status["nba"]["error"] = str(e)
        import_status["nba"]["progress"].append(f"❌ Error: {e}")
        
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        if conn:
            await conn.close()


# =============================================================================
# NFL/NBA Profile Endpoints
# =============================================================================

@router.get("/profiles/{sport}/list")
async def get_sport_profiles(
    sport: str,
    entity_type: str = "player",
    search: str = None,
    limit: int = 1000  # Increased default to support NFL player lists
):
    """Get list of players/teams for a sport."""
    if sport not in ["nfl", "nba", "nascar", "college_baseball"]:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    # Special handling for file-based College Baseball
    if sport == "college_baseball":
        try:
            from scripts.college_baseball_importer import get_teams
            # division could be a param, default to 1
            teams = get_teams(division=1) 
            
            entities = []
            for t in teams:
                entities.append({
                    "id": t.get("team_id"), # safe_id string
                    "name": t.get("ncaa_name"),
                    "type": t.get("type", "team"),
                    "series": f"D{t.get('division', 1)}" if t.get('type') == 'team' else t.get('team_name'),
                    "metadata": {
                        "league": t.get("league"),
                        "team": t.get("team_name") if t.get("type") == "player" else None
                    }
                })
            
            # Filter by entity_type if requested
            if entity_type:
                entities = [e for e in entities if e["type"] == entity_type]
            
            # Filter if search
            if search:
                entities = [e for e in entities if search.lower() in e["name"].lower()]
                
            return {
                "entities": entities[:limit],
                "count": len(entities)
            }
        except Exception as e:
            logger.error(f"Error fetching baseball profiles: {e}")
            return {"entities": [], "count": 0, "error": str(e)}

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
async def get_player_profile(sport: str, name: str, season: Optional[int] = Query(None)):
    """Get detailed player profile with stats.
    
    Uses 3-tier lookup:
    1. Exact name match in entities
    2. Fuzzy ILIKE match in entities  
    3. Fallback to results metadata if no entity found
    """
    if sport not in ["nfl", "nba", "nascar", "college_baseball"]:
        raise HTTPException(status_code=400, detail=f"Invalid sport: {sport}")
    
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Tier 1: Exact name match in entities
        entity = await conn.fetchrow(
            """SELECT id, name, type, series, metadata
               FROM entities
               WHERE sport_id = $1 AND LOWER(name) = LOWER($2)
               LIMIT 1""",
            sport_id, name
        )
        
        # Tier 2: Fuzzy ILIKE match in entities
        if not entity:
            entity = await conn.fetchrow(
                """SELECT id, name, type, series, metadata
                   FROM entities
                   WHERE sport_id = $1 AND name ILIKE $2
                   LIMIT 1""",
                sport_id, f"%{name}%"
            )
        
        # Tier 3: Fallback to results metadata if no entity found
        if not entity:
            result_row = await conn.fetchrow(
                """SELECT metadata, season
                   FROM results
                   WHERE sport_id = $1 
                     AND (metadata->>'player_name' ILIKE $2 OR metadata->>'player_name' ILIKE $3 OR metadata->>'driver' ILIKE $2)
                   ORDER BY season DESC
                   LIMIT 1""",
                sport_id, name, f"%{name}%"
            )
            
            if result_row and result_row["metadata"]:
                meta = json.loads(result_row["metadata"]) if isinstance(result_row["metadata"], str) else result_row["metadata"]
                # Construct synthetic entity
                return {
                    "entity": {
                        "id": 0,
                        "name": meta.get("player_name") or meta.get("driver") or name,
                        "type": "player",
                        "series": meta.get("team_name") or meta.get("team") or "",
                        "metadata": meta
                    },
                    "sport": sport,
                    "available_seasons": [result_row["season"]],
                    "stats": {},
                    "recent_results": []
                }
            
            # No data found anywhere - return empty profile instead of crashing
            return {
                "id": 0,
                "name": name,
                "type": "player",
                "series": sport,
                "metadata": {},
                "stats": {},
                "recent_games": [],
                "not_found": True
            }
        
        # Entity found - get stats
        entity_id = entity["id"]
        entity_meta = json.loads(entity["metadata"]) if isinstance(entity["metadata"], str) else (entity["metadata"] or {})
        
        query = "SELECT season, stat_type, stats FROM stats WHERE entity_id = $1"
        params = [entity_id]
        if season:
            query += " AND season = $2"
            params.append(season)
        query += " ORDER BY season DESC"
        
        stats_rows = await conn.fetch(query, *params)
        
        stats_dict = {}
        available_seasons = set()
        for row in stats_rows:
            curr_season = row["season"]
            available_seasons.add(curr_season)
            s_str = str(curr_season)
            if s_str not in stats_dict:
                stats_dict[s_str] = {}
            
            val = row["stats"]
            if isinstance(val, str):
                try: val = json.loads(val)
                except: pass
            
            if isinstance(val, dict):
                stats_dict[s_str].update(val)
            else:
                stats_dict[s_str][row["stat_type"]] = val

        # Get Recent Results
        gsis_id = entity_meta.get("gsis_id")
        p_id = entity_meta.get("player_id")
        
        recent_games_rows = await conn.fetch(
            """SELECT season, metadata
               FROM results
               WHERE sport_id = $1 
                 AND (
                     metadata->>'player_name' ILIKE $2
                     OR metadata->>'player_display_name' ILIKE $2
                     OR metadata->>'player_id' = $3
                     OR metadata->>'gsis_id' = $3
                     OR metadata->>'driver' ILIKE $2
                 )
               ORDER BY season DESC, (metadata->>'week')::int DESC NULLS LAST
               LIMIT 10""",
            sport_id, f"%{entity['name']}%", str(gsis_id or p_id or "")
        )
        
        recent_results = []
        for row in recent_games_rows:
            res_meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
            recent_results.append({
                "season": row["season"],
                **res_meta
            })
            available_seasons.add(row["season"])

        # Fallback: Populate stats from results if stats table is empty
        if not stats_dict and recent_results:
            for res in recent_results:
                s_str = str(res["season"])
                if s_str not in stats_dict:
                    stats_dict[s_str] = {}
                for k, v in res.items():
                    if k not in ["player_id", "player_name", "player_display_name", "gsis_id", "season"]:
                        stats_dict[s_str][k] = v

        return {
            "entity": {
                "id": entity["id"],
                "name": entity["name"],
                "type": entity["type"],
                "series": entity["series"],
                "metadata": entity_meta
            },
            "sport": sport,
            "available_seasons": sorted(list(available_seasons), reverse=True),
            "stats": stats_dict,
            "recent_results": recent_results
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
