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
        elif sport == 'nhl':
            from scripts.nhl_importer import import_all_nhl
            result = await import_all_nhl(clear_existing=False, progress_callback=update_progress)
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
        
        import_status["nascar_rda"]["progress"].append("Starting Parquet file import directly from R2...")
        
        # 2. Run Parquet import
        from scripts.nascar_parquet_importer import run_import as import_nascar_parquet
        
        def progress_cb(msg):
            import_status["nascar_rda"]["progress"].append(msg)
            if len(import_status["nascar_rda"]["progress"]) > 100:
                 import_status["nascar_rda"]["progress"] = import_status["nascar_rda"]["progress"][-100:]

        rows = await import_nascar_parquet()
        
        status = "COMPLETED"
        import_status["nascar_rda"]["status"] = status.lower()
        import_status["nascar_rda"]["completed_at"] = datetime.now().isoformat()
        import_status["nascar_rda"]["result"] = {"status": "success", "rows": rows}
        
        import_status["nascar_rda"]["progress"].append(f"✅ Imported {rows} results from Parquet sources")
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
        if sport == 'college_baseball':
            from pathlib import Path
            import json
            
            # Use relative path that works locally, fallback to Docker path
            _local_data_dir = Path(__file__).parent.parent / "data" / "baseball"
            _docker_data_dir = Path("/app/data/baseball")
            data_dir = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
            
            inventory_file = data_dir / "players_inventory.json"
            if inventory_file.exists():
                with open(inventory_file, 'r') as f:
                    inventory = json.load(f)
                
                entities = []
                for idx, (p_name, teams) in enumerate(inventory.items()):
                    if search and search.lower() not in p_name.lower():
                        continue
                    
                    # Get the first team for metadata
                    first_team_id = next(iter(teams))
                    team_info = teams[first_team_id]
                    
                    entities.append({
                        "id": idx + 10000,
                        "name": p_name,
                        "type": "player",
                        "series": team_info.get("team_name", ""),
                        "metadata": {"team": team_info.get("team_name", ""), "team_id": first_team_id}
                    })
                
                return {
                    "sport": sport,
                    "entity_type": "player",
                    "count": len(entities),
                    "entities": entities[:limit]
                }
            return {"sport": sport, "entity_type": "player", "count": 0, "entities": []}

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
        if sport == 'college_baseball':
            from pathlib import Path
            import json
            import pandas as pd
            
            # Use relative path that works locally, fallback to Docker path
            _local_data_dir = Path(__file__).parent.parent / "data" / "baseball"
            _docker_data_dir = Path("/app/data/baseball")
            data_dir = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
            
            inventory_file = data_dir / "players_inventory.json"
            if inventory_file.exists():
                with open(inventory_file, 'r') as f:
                    inventory = json.load(f)
                
                player_key = None
                if name in inventory:
                    player_key = name
                else:
                    # Case insensitive search
                    for k in inventory.keys():
                        if k.lower() == name.lower():
                            player_key = k
                            break
                
                if player_key:
                    teams = inventory[player_key]
                    first_team_id = next(iter(teams))
                    team_info = teams[first_team_id]
                    
                    profile = {
                        "entity": {
                            "id": 10000,
                            "name": player_key,
                            "type": "player",
                            "series": team_info.get("team_name", ""),
                            "metadata": {"team": team_info.get("team_name", ""), "team_id": first_team_id}
                        },
                        "sport": sport,
                        "available_seasons": [2025],
                        "stats": {}
                    }
                    
                    # Load stats from CSVs
                    for t_id, t_details in teams.items():
                        year = t_details.get("year", 2025)
                        season_key = str(year)
                        if season_key not in profile["stats"]:
                            profile["stats"][season_key] = {}
                        
                        for s_type in t_details.get("stat_types", []):
                            csv_path = data_dir / "stats" / f"{t_id}_{s_type}.csv"
                            if csv_path.exists():
                                try:
                                    df = pd.read_csv(csv_path)
                                    df.columns = [c.lower() for c in df.columns]
                                    
                                    mask = (df['name'].astype(str).str.lower() == player_key.lower())
                                    if 'player_name' in df.columns:
                                        mask |= (df['player_name'].astype(str).str.lower() == player_key.lower())
                                    
                                    player_row = df[mask]
                                    if not player_row.empty:
                                        row_dict = player_row.iloc[0].to_dict()
                                        for k, v in row_dict.items():
                                            if k not in ["name", "player_name", "team", "team_name", "year"]:
                                                profile["stats"][season_key][k] = v
                                except Exception as e:
                                    logger.error(f"Error reading CSV for profile: {e}")
                    
                    return profile
            
            return {"not_found": True, "message": f"Player '{name}' not found in college baseball data."}

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
        
        # Helpers to safely cast
        def safe_int(val):
            if val is None or val == "" or str(val).lower() == 'nan' or str(val).lower() == 'none':
                 return None
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None
                
        def safe_float(val):
            if val is None or val == "" or str(val).lower() == 'nan' or str(val).lower() == 'none':
                 return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Format results
        race_results = []
        for row in results:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            
            # Case-insensitive/Standardized fallbacks for metadata keys
            # Explicitly cast to int where expected to avoid .0 in JSON
            v_start = safe_int(meta.get("start") or meta.get("Start"))
            v_finish = safe_int(meta.get("finish") or meta.get("Finish"))
            v_race = safe_int(meta.get("race_num") or meta.get("Race"))
            v_led = safe_int(meta.get("led") or meta.get("Led"))
            v_laps = safe_int(meta.get("laps") or meta.get("Laps"))
            v_pts = safe_int(meta.get("pts") or meta.get("Pts"))
            v_rating = safe_float(meta.get("rating") or meta.get("Rating"))

            race_results.append({
                "id": row["id"],
                "season": int(row["season"]),
                "series": row["series"],
                "track": row["track"],
                "race_num": v_race,
                "race_name": meta.get("race_name") or meta.get("Race_Name"),
                "driver": meta.get("driver_name") or meta.get("Driver"),
                "finish": v_finish,
                "start": v_start,
                "led": v_led,
                "laps": v_laps,
                "pts": v_pts,
                "status": meta.get("status") or meta.get("Status"),
                "team": meta.get("team") or meta.get("Team"),
                "make": meta.get("make") or meta.get("Manufacturer") or meta.get("Make"),
                "rating": v_rating,
            })
        
        from fastapi.responses import JSONResponse
        return JSONResponse(content={
            "results": [
                {
                    "id": r["id"],
                    "season": int(r["season"]),
                    "series": r["series"],
                    "track": r["track"],
                    "race_num": int(r["race_num"]) if r["race_num"] is not None else None,
                    "race_name": r["race_name"],
                    "driver": r["driver"],
                    "finish": int(r["finish"]) if r["finish"] is not None else None,
                    "start": int(r["start"]) if r["start"] is not None else None,
                    "led": int(r["led"]) if r["led"] is not None else None,
                    "laps": int(r["laps"]) if r["laps"] is not None else None,
                    "pts": int(r["pts"]) if r["pts"] is not None else None,
                    "status": r["status"],
                    "team": r["team"],
                    "make": r["make"],
                    "rating": float(r["rating"]) if r["rating"] is not None else None,
                } for r in race_results
            ],
            "total": total_count,
            "limit": limit,
            "offset": offset,
        })
    finally:
        await conn.close()

@router.get("/races/nascar/standings/{season}")
async def get_nascar_standings(season: int, series: str = "cup"):
    """
    Get NASCAR season standings by series.
    Aggregates points, wins, top 5s, and top 10s from race results.
    """
    conn = await get_db_connection()
    try:
        # Get sport_id for nascar
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        if not sport_id:
            return {"standings": []}

        # Query to aggregate standings from JSON metadata
        query = """
            SELECT 
                row_to_json(r)->'metadata'->>'driver_name' as driver,
                row_to_json(r)->'metadata'->>'team' as team,
                COUNT(*) as races,
                SUM(CAST(NULLIF(row_to_json(r)->'metadata'->>'pts', '') AS numeric))::int as points,
                COUNT(*) FILTER (WHERE CAST(NULLIF(row_to_json(r)->'metadata'->>'finish', '') AS numeric)::int = 1) as wins,
                COUNT(*) FILTER (WHERE CAST(NULLIF(row_to_json(r)->'metadata'->>'finish', '') AS numeric)::int <= 5) as top5,
                COUNT(*) FILTER (WHERE CAST(NULLIF(row_to_json(r)->'metadata'->>'finish', '') AS numeric)::int <= 10) as top10
            FROM results r
            WHERE sport_id = $1 AND season = $2 AND series = $3
            GROUP BY 1, 2
            ORDER BY points DESC
        """
        rows = await conn.fetch(query, sport_id, season, series)
        
        standings = []
        max_points = 0
        for i, row in enumerate(rows):
            pts = row["points"] or 0
            if i == 0:
                max_points = pts
            
            standings.append({
                "rank": i + 1,
                "driver": row["driver"],
                "team": row["team"],
                "races": row["races"],
                "points": int(pts),
                "wins": int(row["wins"] or 0),
                "top5": int(row["top5"] or 0),
                "top10": int(row["top10"] or 0),
                "behind": int(max_points - pts)
            })
            
        return {
            "season": season,
            "series": series,
            "standings": standings
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


@router.get("/standings/{sport}")
async def get_league_standings(
    sport: str,
    season: int = None
):
    """
    Get professional league standings (NBA, NFL, NHL).
    Aggregates W/L, Points, and ATS records from the results table.
    """
    if sport not in ["nfl", "nba", "nhl"]:
        raise HTTPException(status_code=400, detail=f"Standings not supported for: {sport}")
    
    conn = await get_db_connection()
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport)
        if not sport_id:
            raise HTTPException(status_code=404, detail=f"Sport '{sport}' not found")
        
        # Default to latest season with standings-compatible data
        if not season:
            if sport == "nfl":
                season = await conn.fetchval(
                    "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = 'nfl_schedule'",
                    sport_id
                )
            elif sport == "nba":
                # Prefer nba_schedule, fallback to nba_game_log
                season = await conn.fetchval(
                    "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = 'nba_schedule'",
                    sport_id
                )
                if not season:
                    season = await conn.fetchval(
                        "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = 'nba_game_log'",
                        sport_id
                    )
            elif sport == "nhl":
                season = await conn.fetchval(
                    "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = 'nhl'",
                    sport_id
                )
            
            if not season:
                # Final fallback
                season = await conn.fetchval(
                    "SELECT MAX(season) FROM results WHERE sport_id = $1",
                    sport_id
                ) or 2024

        query = ""
        if sport == "nfl":
            # NFL Standings from nfl_schedule
            query = """
                WITH games AS (
                    SELECT 
                        metadata->>'home_team' as home,
                        metadata->>'away_team' as away,
                        (metadata->>'home_score')::int as h_score,
                        (metadata->>'away_score')::int as a_score,
                        (metadata->>'spread_line')::float as spread
                    FROM results 
                    WHERE sport_id = $1 AND series = 'nfl_schedule' AND season = $2
                      AND metadata->>'home_score' IS NOT NULL
                ),
                team_stats AS (
                    SELECT home as team, 
                           CASE WHEN h_score > a_score THEN 1 ELSE 0 END as win,
                           CASE WHEN h_score < a_score THEN 1 ELSE 0 END as loss,
                           CASE WHEN h_score = a_score THEN 1 ELSE 0 END as tie,
                           h_score as pf, a_score as pa,
                           CASE WHEN h_score + COALESCE(spread, 0) > a_score THEN 1 ELSE 0 END as ats_win,
                           CASE WHEN h_score + COALESCE(spread, 0) < a_score THEN 1 ELSE 0 END as ats_loss,
                           CASE WHEN h_score + COALESCE(spread, 0) = a_score THEN 1 ELSE 0 END as ats_push
                    FROM games
                    UNION ALL
                    SELECT away as team,
                           CASE WHEN a_score > h_score THEN 1 ELSE 0 END as win,
                           CASE WHEN a_score < h_score THEN 1 ELSE 0 END as loss,
                           CASE WHEN a_score = h_score THEN 1 ELSE 0 END as tie,
                           a_score as pf, h_score as pa,
                           CASE WHEN a_score - COALESCE(spread, 0) > h_score THEN 1 ELSE 0 END as ats_win,
                           CASE WHEN a_score - COALESCE(spread, 0) < h_score THEN 1 ELSE 0 END as ats_loss,
                           CASE WHEN a_score - COALESCE(spread, 0) = h_score THEN 1 ELSE 0 END as ats_push
                    FROM games
                )
                SELECT team, 
                       COALESCE(SUM(win), 0) as wins, COALESCE(SUM(loss), 0) as losses, COALESCE(SUM(tie), 0) as ties,
                       COALESCE(SUM(pf), 0) as points_for, COALESCE(SUM(pa), 0) as points_against,
                       COALESCE(SUM(ats_win), 0) as ats_wins, COALESCE(SUM(ats_loss), 0) as ats_losses, COALESCE(SUM(ats_push), 0) as ats_pushes
                FROM team_stats
                GROUP BY team
                ORDER BY wins DESC, (SUM(pf) - SUM(pa)) DESC
            """
        elif sport == "nba":
            # Try nba_schedule first (game-level data with home/away scores)
            schedule_count = await conn.fetchval(
                "SELECT COUNT(*) FROM results WHERE sport_id = $1 AND series = 'nba_schedule' AND season = $2",
                sport_id, int(season)
            )
            
            if schedule_count and schedule_count > 0:
                # NBA Standings from nba_schedule
                query = """
                    WITH games AS (
                        SELECT 
                            metadata->>'home_team' as home,
                            metadata->>'away_team' as away,
                            (metadata->>'home_score')::int as h_score,
                            (metadata->>'away_score')::int as a_score
                        FROM results 
                        WHERE sport_id = $1 AND series = 'nba_schedule' AND season = $2
                          AND metadata->>'home_score' IS NOT NULL
                    ),
                    team_stats AS (
                        SELECT home as team, 
                               CASE WHEN h_score > a_score THEN 1 ELSE 0 END as win,
                               CASE WHEN h_score < a_score THEN 1 ELSE 0 END as loss,
                               h_score as pf, a_score as pa
                        FROM games
                        UNION ALL
                        SELECT away as team,
                               CASE WHEN a_score > h_score THEN 1 ELSE 0 END as win,
                               CASE WHEN a_score < h_score THEN 1 ELSE 0 END as loss,
                               a_score as pf, h_score as pa
                        FROM games
                    )
                    SELECT team, 
                           COALESCE(SUM(win), 0) as wins, COALESCE(SUM(loss), 0) as losses, 
                           COALESCE(SUM(pf), 0) as points_for, COALESCE(SUM(pa), 0) as points_against
                    FROM team_stats
                    GROUP BY team
                    ORDER BY wins DESC, (SUM(pf) - SUM(pa)) DESC
                """
            else:
                # Fallback: derive standings from nba_game_log (player game logs)
                # Deduplicate by game_id + team to get one row per team per game
                query = """
                    WITH unique_games AS (
                        SELECT DISTINCT ON (metadata->>'game_id', metadata->>'team')
                            metadata->>'team' as team,
                            metadata->>'wl' as wl,
                            (metadata->>'pts')::int as pts
                        FROM results
                        WHERE sport_id = $1 AND series = 'nba_game_log' AND season = $2
                          AND metadata->>'wl' IS NOT NULL
                          AND metadata->>'team' IS NOT NULL
                        ORDER BY metadata->>'game_id', metadata->>'team', (metadata->>'min')::float DESC NULLS LAST
                    )
                    SELECT team,
                           COALESCE(SUM(CASE WHEN wl = 'W' THEN 1 ELSE 0 END), 0) as wins,
                           COALESCE(SUM(CASE WHEN wl = 'L' THEN 1 ELSE 0 END), 0) as losses,
                           COALESCE(SUM(pts), 0) as points_for,
                           0 as points_against
                    FROM unique_games
                    GROUP BY team
                    ORDER BY wins DESC
                """
        elif sport == "nhl":
            # NHL: Fetch live standings from NHL API directly (MoneyPuck data is situation-level, not game-level)
            import httpx
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"https://api-web.nhle.com/v1/standings/{today}")
                    if resp.status_code == 200:
                        nhl_data = resp.json()
                        standings = []
                        for team in nhl_data.get("standings", []):
                            abbrev = team.get("teamAbbrev", {}).get("default", "")
                            name = team.get("teamName", {}).get("default", "") or team.get("teamCommonName", {}).get("default", abbrev)
                            wins = team.get("wins", 0)
                            losses = team.get("losses", 0)
                            ot_losses = team.get("otLosses", 0)
                            pts = team.get("points", 0)
                            gf = team.get("goalFor", 0)
                            ga = team.get("goalAgainst", 0)
                            total_games = wins + losses + ot_losses
                            standings.append({
                                "team": f"{abbrev} {name}" if name else abbrev,
                                "wins": wins,
                                "losses": losses,
                                "ot_losses": ot_losses,
                                "points": pts,
                                "points_for": gf,
                                "points_against": ga,
                                "win_pct": round(wins / total_games, 3) if total_games > 0 else 0,
                                "record": f"{wins}-{losses}-{ot_losses}",
                                "ats_record": "N/A",
                            })
                        standings.sort(key=lambda x: (-x["points"], -x["wins"]))
                        return {
                            "sport": "nhl",
                            "season": season or datetime.now().year,
                            "standings": standings,
                            "source": "NHL API"
                        }
            except Exception as e:
                logger.error(f"NHL API standings fetch failed: {e}")
            # Fallback: return empty
            return {
                "sport": "nhl",
                "season": season or datetime.now().year,
                "standings": [],
                "error": "Could not fetch NHL standings from API"
            }

        rows = await conn.fetch(query, sport_id, int(season))
        
        standings = []
        for row in rows:
            d = dict(row)
            # Add win percentage
            total_games = d['wins'] + d['losses'] + d.get('ties', 0) + d.get('ot_losses', 0)
            d['win_pct'] = round(d['wins'] / total_games, 3) if total_games > 0 else 0
            
            # Format record string
            if sport == "nhl":
                d['record'] = f"{d['wins']}-{d['losses']}-{d.get('ot_losses', 0)}"
            elif d.get('ties', 0) > 0:
                d['record'] = f"{d['wins']}-{d['losses']}-{d['ties']}"
            else:
                d['record'] = f"{d['wins']}-{d['losses']}"
                
            # Format ATS record if available, otherwise default
            if 'ats_wins' in d:
                d['ats_record'] = f"{d['ats_wins']}-{d['ats_losses']}-{d['ats_pushes']}"
            else:
                d['ats_record'] = "N/A"
                
            standings.append(d)

        return {
            "sport": sport,
            "season": season,
            "standings": standings
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
# NHL Import Endpoints
# =============================================================================

@router.post("/import/nhl")
async def import_nhl_data(
    background_tasks: BackgroundTasks,
    clear_existing: bool = False,
    start_year: int = Query(2023, description="Earliest season to import (default: 2023)")
):
    """
    Start NHL data import from MoneyPuck.
    Downloads game-by-game team data and player bios.
    Filters to seasons >= start_year to avoid importing decades of history.
    """
    if import_status.get("nhl", {}).get("status") == "running":
        return {
            "status": "already_running",
            "message": "NHL import is already in progress",
            "started_at": import_status["nhl"]["started_at"]
        }
    
    import_status["nhl"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": ["NHL import started..."],
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(run_nhl_import, clear_existing, start_year)
    
    return {
        "status": "started",
        "message": f"NHL data import started (MoneyPuck, seasons >= {start_year})",
        "clear_existing": clear_existing,
        "start_year": start_year
    }


@router.get("/import/nhl/status")
async def get_nhl_import_status():
    """Get the current status of NHL import."""
    return import_status.get("nhl", {"status": "not_started"})


async def run_nhl_import(clear_existing: bool, start_year: int = 2023):
    """Background task for NHL import with DB logging."""
    import asyncpg
    conn = None
    log_id = None
    start_time = datetime.now()
    
    try:
        from scripts.nhl_importer import import_all_nhl
        
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('nhl', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        def progress_callback(msg):
            import_status["nhl"]["progress"].append(msg)
            logger.info(f"NHL Import: {msg}")
        
        result = await import_all_nhl(
            clear_existing=clear_existing,
            start_year=start_year,
            progress_callback=progress_callback
        )
        
        rows = (result.get("games_imported", 0) + 
                result.get("players_imported", 0))
        
        status = "COMPLETED" if result.get("status") == "success" else "FAILED"
        import_status["nhl"]["status"] = status.lower()
        import_status["nhl"]["completed_at"] = datetime.now().isoformat()
        import_status["nhl"]["result"] = {**result, "rows": rows}
        
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = "; ".join(result.get("errors", [])) if result.get("errors") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
        if result.get("errors"):
            import_status["nhl"]["error"] = error_msg
        
    except Exception as e:
        logger.error(f"NHL import failed: {e}")
        import_status["nhl"]["status"] = "failed"
        import_status["nhl"]["completed_at"] = datetime.now().isoformat()
        import_status["nhl"]["error"] = str(e)
        import_status["nhl"]["progress"].append(f"❌ Error: {e}")
        
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


# ========================================================
# NFL Power Rankings
# ========================================================

@router.get("/nfl/power-rankings")
async def get_nfl_power_rankings(
    season: Optional[int] = Query(None, description="NFL season year (default: latest)"),
):
    """
    Compute NFL Power Rankings from game results.
    
    Composite score based on:
    - Win percentage (30%)
    - Point differential per game (25%)  
    - Strength of schedule (20%)
    - ATS record (15%)
    - Recent form - last 5 games (10%)
    """
    import asyncpg
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nfl'")
        if not sport_id:
            raise HTTPException(status_code=404, detail="NFL sport not found")
        
        if not season:
            season = await conn.fetchval(
                "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = 'nfl_schedule'",
                sport_id
            )
        if not season:
            return {"rankings": [], "season": 0}
        
        # Fetch all completed games for the season
        rows = await conn.fetch(
            """SELECT metadata FROM results 
               WHERE sport_id = $1 AND series = 'nfl_schedule' AND season = $2
               AND metadata->>'home_score' IS NOT NULL
               AND metadata->>'game_type' = 'REG'
            """,
            sport_id, int(season)
        )
        
        if not rows:
            return {"rankings": [], "season": season}
        
        # Build team stats
        teams = {}
        games_list = []
        
        for row in rows:
            m = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"])
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            h_score = int(m.get("home_score", 0))
            a_score = int(m.get("away_score", 0))
            spread = float(m.get("spread_line", 0) or 0)
            week = int(m.get("week", 0) or 0)
            
            if not home or not away:
                continue
            
            games_list.append({
                "home": home, "away": away,
                "h_score": h_score, "a_score": a_score,
                "spread": spread, "week": week
            })
            
            for team in [home, away]:
                if team not in teams:
                    teams[team] = {
                        "wins": 0, "losses": 0, "ties": 0,
                        "pf": 0, "pa": 0,
                        "ats_wins": 0, "ats_losses": 0, "ats_pushes": 0,
                        "opponents": [], "recent_results": []
                    }
            
            # Home team stats
            if h_score > a_score:
                teams[home]["wins"] += 1
                teams[away]["losses"] += 1
            elif a_score > h_score:
                teams[away]["wins"] += 1
                teams[home]["losses"] += 1
            else:
                teams[home]["ties"] += 1
                teams[away]["ties"] += 1
            
            teams[home]["pf"] += h_score
            teams[home]["pa"] += a_score
            teams[away]["pf"] += a_score
            teams[away]["pa"] += h_score
            
            teams[home]["opponents"].append(away)
            teams[away]["opponents"].append(home)
            
            # ATS: home team favored if spread < 0 (e.g. KC -3 means spread_line = -3 for away perspective typically)
            # nfl_data_py spread_line is from home perspective: positive = home is underdog
            home_margin = h_score - a_score
            if spread != 0:
                ats_margin = home_margin + spread  # spread is typically the line the home team gets
                if ats_margin > 0:
                    teams[home]["ats_wins"] += 1
                    teams[away]["ats_losses"] += 1
                elif ats_margin < 0:
                    teams[home]["ats_losses"] += 1
                    teams[away]["ats_wins"] += 1
                else:
                    teams[home]["ats_pushes"] += 1
                    teams[away]["ats_pushes"] += 1
            
            # Recent results (track by week for sorting)
            teams[home]["recent_results"].append((week, 1 if h_score > a_score else 0))
            teams[away]["recent_results"].append((week, 1 if a_score > h_score else 0))
        
        # Calculate composite rankings
        rankings = []
        max_games = max((t["wins"] + t["losses"] + t["ties"]) for t in teams.values()) if teams else 1
        
        for name, t in teams.items():
            total = t["wins"] + t["losses"] + t["ties"]
            if total == 0:
                continue
            
            # 1. Win % (0-1)
            win_pct = (t["wins"] + 0.5 * t["ties"]) / total
            
            # 2. Point differential per game (-inf to +inf, normalize later)
            pt_diff_pg = (t["pf"] - t["pa"]) / total
            
            # 3. Strength of schedule (avg opponent win%)
            opp_win_pcts = []
            for opp in t["opponents"]:
                if opp in teams:
                    ot = teams[opp]
                    og = ot["wins"] + ot["losses"] + ot["ties"]
                    if og > 0:
                        opp_win_pcts.append((ot["wins"] + 0.5 * ot["ties"]) / og)
            sos = sum(opp_win_pcts) / len(opp_win_pcts) if opp_win_pcts else 0.5
            
            # 4. ATS performance
            ats_total = t["ats_wins"] + t["ats_losses"] + t["ats_pushes"]
            ats_pct = t["ats_wins"] / ats_total if ats_total > 0 else 0.5
            
            # 5. Recent form (last 5 games)
            recent = sorted(t["recent_results"], key=lambda x: -x[0])[:5]
            recent_pct = sum(r[1] for r in recent) / len(recent) if recent else 0.5
            
            rankings.append({
                "team": name,
                "wins": t["wins"],
                "losses": t["losses"],
                "ties": t["ties"],
                "record": f"{t['wins']}-{t['losses']}" + (f"-{t['ties']}" if t["ties"] > 0 else ""),
                "pf": t["pf"],
                "pa": t["pa"],
                "pt_diff": t["pf"] - t["pa"],
                "pt_diff_pg": round(pt_diff_pg, 1),
                "win_pct": round(win_pct, 3),
                "sos": round(sos, 3),
                "ats_record": f"{t['ats_wins']}-{t['ats_losses']}-{t['ats_pushes']}",
                "ats_pct": round(ats_pct, 3),
                "recent_pct": round(recent_pct, 3),
                # Raw components for composite calc
                "_win_pct": win_pct,
                "_pt_diff_pg": pt_diff_pg,
                "_sos": sos,
                "_ats_pct": ats_pct,
                "_recent_pct": recent_pct,
            })
        
        # Normalize point differential to 0-1 range
        if rankings:
            pd_vals = [r["_pt_diff_pg"] for r in rankings]
            pd_min, pd_max = min(pd_vals), max(pd_vals)
            pd_range = pd_max - pd_min if pd_max != pd_min else 1
            
            for r in rankings:
                pd_norm = (r["_pt_diff_pg"] - pd_min) / pd_range
                
                # Composite: Win%(30) + PtDiff(25) + SOS(20) + ATS(15) + Recent(10)
                composite = (
                    0.30 * r["_win_pct"] +
                    0.25 * pd_norm +
                    0.20 * r["_sos"] +
                    0.15 * r["_ats_pct"] +
                    0.10 * r["_recent_pct"]
                )
                r["power_score"] = round(composite * 100, 1)
                
                # Clean up internal fields
                del r["_win_pct"]
                del r["_pt_diff_pg"]
                del r["_sos"]
                del r["_ats_pct"]
                del r["_recent_pct"]
            
            rankings.sort(key=lambda x: -x["power_score"])
            
            # Add rank
            for i, r in enumerate(rankings):
                r["rank"] = i + 1
        
        latest_week = max(g["week"] for g in games_list) if games_list else 0
        
        return {
            "season": season,
            "through_week": latest_week,
            "total_teams": len(rankings),
            "rankings": rankings,
            "weights": {
                "win_pct": 0.30,
                "point_differential": 0.25,
                "strength_of_schedule": 0.20,
                "ats_performance": 0.15,
                "recent_form": 0.10
            }
        }
    finally:
        await conn.close()


# ========================================================
# NASCAR Power Rankings (per series)
# ========================================================

def _to_float(val, default=0.0):
    """Safely convert value to float, handling string representations."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return default

def _to_int(val, default=0):
    """Safely convert value to int, handling string representations."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    try:
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return default

@router.get("/nascar/power-rankings")
async def get_nascar_power_rankings(
    series: str = Query("cup", description="NASCAR series: cup, trucks, xfinity"),
    season: Optional[int] = Query(None, description="Season year (default: latest)"),
):
    """
    Compute NASCAR Power Rankings for a specific series.
    
    Composite score based on:
    - Average finish (30%)
    - Recent form - last 5 races (25%)
    - Top-5/Top-10 rate (20%)
    - Laps led rate (15%)
    - Track-type performance (10%)
    """
    import asyncpg
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        if not sport_id:
            raise HTTPException(status_code=404, detail="NASCAR sport not found")
        
        if series not in {"cup", "trucks", "xfinity"}:
            raise HTTPException(status_code=400, detail="Series must be one of: cup, trucks, xfinity")
        
        if not season:
            season = await conn.fetchval(
                "SELECT MAX(season) FROM results WHERE sport_id = $1 AND series = $2",
                sport_id, series
            )
        if not season:
            return {"rankings": [], "season": 0, "series": series}
        
        # Fetch all race results for the season/series
        rows = await conn.fetch(
            """SELECT metadata FROM results 
               WHERE sport_id = $1 AND series = $2 AND season = $3
               AND metadata->>'Finish' IS NOT NULL
            """,
            sport_id, series, int(season)
        )
        
        if not rows:
            return {"rankings": [], "season": season, "series": series}
        
        # Build driver stats
        drivers = {}
        race_count = 0
        
        for row in rows:
            m = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"])
            driver = m.get("driver_name", "") or m.get("Driver", "")
            finish = (m.get("Finish") or m.get("finish")) or 0
            start = (m.get("Start") or m.get("start")) or 0
            laps = (m.get("Laps") or m.get("laps")) or 0
            led = (m.get("Led") or m.get("led")) or 0.0
            pts = (m.get("Pts") or m.get("pts")) or 0.0
            win = (m.get("Win") or m.get("win")) or 0
            track = m.get("Track", "") or m.get("track", "")
            surface = m.get("Surface", "") or m.get("surface", "")
            length = (m.get("Length") or m.get("length")) or 0.0
            race_num = (m.get("Race") or m.get("race_num")) or 0
            
            if not driver or finish == 0:
                continue
            
            race_count = max(race_count, race_num)
            
            if driver not in drivers:
                drivers[driver] = {
                    "finishes": [], "starts": [], "top5": 0, "top10": 0, "wins": 0,
                    "laps": 0, "led": 0, "pts": 0, "track_perf": {}, "race_nums": []
                }
            
            d = drivers[driver]
            d["finishes"].append(finish)
            d["starts"].append(start)
            d["laps"] += laps
            d["led"] += led
            d["pts"] += pts
            d["wins"] += win
            d["race_nums"].append(race_num)
            
            if finish <= 5:
                d["top5"] += 1
            if finish <= 10:
                d["top10"] += 1
            
            # Track type performance
            track_type = "unknown"
            if surface:
                track_type = surface.lower()
            elif length:
                if length >= 2.0:
                    track_type = "superspeedway"
                elif length >= 1.0:
                    track_type = "intermediate"
                else:
                    track_type = "short"
            
            if track_type not in d["track_perf"]:
                d["track_perf"][track_type] = {"finishes": [], "count": 0}
            d["track_perf"][track_type]["finishes"].append(finish)
            d["track_perf"][track_type]["count"] += 1
        
        # Calculate rankings
        rankings = []
        for name, d in drivers.items():
            total_races = len(d["finishes"])
            if total_races == 0:
                continue
            
            # 1. Average finish (lower is better, invert for scoring)
            avg_finish = sum(d["finishes"]) / total_races
            avg_finish_score = 1.0 - (avg_finish - 1) / 39  # Normalize 1-40 to 0-1, invert
            
            # 2. Recent form (last 5 races)
            recent_races = sorted(zip(d["race_nums"], d["finishes"]), key=lambda x: -x[0])[:5]
            recent_finishes = [f for _, f in recent_races]
            recent_avg = sum(recent_finishes) / len(recent_finishes) if recent_finishes else 20
            recent_score = 1.0 - (recent_avg - 1) / 39
            
            # 3. Top-5/Top-10 rate
            top5_rate = d["top5"] / total_races
            top10_rate = d["top10"] / total_races
            
            # 4. Laps led rate
            laps_led_rate = d["led"] / d["laps"] if d["laps"] > 0 else 0
            
            # 5. Track-type consistency (average finish variance across track types)
            track_scores = []
            for perf in d["track_perf"].values():
                if perf["count"] >= 2:
                    avg = sum(perf["finishes"]) / perf["count"]
                    track_scores.append(1.0 - (avg - 1) / 39)
            track_consistency = sum(track_scores) / len(track_scores) if track_scores else 0.5
            
            rankings.append({
                "driver": name,
                "races": total_races,
                "wins": d["wins"],
                "top5": d["top5"],
                "top10": d["top10"],
                "avg_finish": round(avg_finish, 1),
                "recent_avg": round(recent_avg, 1),
                "top5_rate": round(top5_rate, 3),
                "top10_rate": round(top10_rate, 3),
                "laps_led_rate": round(laps_led_rate, 3),
                "track_consistency": round(track_consistency, 3),
                "pts": d["pts"],
                # Raw components for composite calc
                "_avg_finish_score": avg_finish_score,
                "_recent_score": recent_score,
                "_top5_rate": top5_rate,
                "_laps_led_rate": laps_led_rate,
                "_track_consistency": track_consistency,
            })
        
        # Composite: AvgFinish(30) + Recent(25) + Top5(20) + LapsLed(15) + Track(10)
        for r in rankings:
            composite = (
                0.30 * r["_avg_finish_score"] +
                0.25 * r["_recent_score"] +
                0.20 * r["_top5_rate"] +
                0.15 * r["_laps_led_rate"] +
                0.10 * r["_track_consistency"]
            )
            r["power_score"] = round(composite * 100, 1)
            
            # Clean up internal fields
            for key in list(r.keys()):
                if key.startswith("_"):
                    del r[key]
        
        rankings.sort(key=lambda x: -x["power_score"])
        
        # Add rank
        for i, r in enumerate(rankings):
            r["rank"] = i + 1
        
        return {
            "season": season,
            "series": series,
            "through_race": race_count,
            "total_drivers": len(rankings),
            "rankings": rankings,
            "weights": {
                "avg_finish": 0.30,
                "recent_form": 0.25,
                "top5_rate": 0.20,
                "laps_led_rate": 0.15,
                "track_consistency": 0.10
            }
        }
    finally:
        await conn.close()


# NBA Power Rankings
# ========================================================

@router.get("/nba/power-rankings")
async def get_nba_power_rankings(
    season: Optional[int] = Query(None, description="NBA season year (default: latest)"),
):
    """Calculate NBA power rankings based on team performance."""
    try:
        import asyncpg
        from src.config import DATABASE_URL
        
        # Default to current season if not specified
        if season is None:
            from datetime import datetime
            season = datetime.now().year
        
        conn = await get_db_connection()
        
        # Get NBA sport ID
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        if not sport_id:
            raise HTTPException(status_code=404, detail="NBA sport not found")
        
        # Get games for the season
        games_query = """
            SELECT home_entity_id, away_entity_id, home_score, away_score, game_date
            FROM results r
            JOIN sports s ON r.sport_id = s.id
            WHERE s.name = 'nba' AND r.season = $1
            AND r.home_score IS NOT NULL AND r.away_score IS NOT NULL
            ORDER BY r.game_date
        """
        games = await conn.fetch(games_query, season)
        
        if not games:
            return {
                "season": season,
                "through_games": 0,
                "total_teams": 0,
                "rankings": []
            }
        
        # Calculate team stats
        team_stats = {}
        
        for game in games:
            home_team_id = game['home_entity_id']
            away_team_id = game['away_entity_id']
            home_score = game['home_score']
            away_score = game['away_score']
            
            # Skip games without entity IDs
            if home_team_id is None or away_team_id is None:
                continue
            
            # Use entity IDs as team identifiers
            home_team = f"Team_{home_team_id}"
            away_team = f"Team_{away_team_id}"
            
            # Initialize teams if not exists
            if home_team not in team_stats:
                team_stats[home_team] = {'games': 0, 'wins': 0, 'losses': 0, 'points_for': 0, 'points_against': 0, 'recent': []}
            if away_team not in team_stats:
                team_stats[away_team] = {'games': 0, 'wins': 0, 'losses': 0, 'points_for': 0, 'points_against': 0, 'recent': []}
            
            # Update stats
            team_stats[home_team]['games'] += 1
            team_stats[away_team]['games'] += 1
            team_stats[home_team]['points_for'] += home_score
            team_stats[home_team]['points_against'] += away_score
            team_stats[away_team]['points_for'] += away_score
            team_stats[away_team]['points_against'] += home_score
            
            # Update wins/losses
            if home_score > away_score:
                team_stats[home_team]['wins'] += 1
                team_stats[away_team]['losses'] += 1
                team_stats[home_team]['recent'].append(1)  # Win
                team_stats[away_team]['recent'].append(0)  # Loss
            else:
                team_stats[away_team]['wins'] += 1
                team_stats[home_team]['losses'] += 1
                team_stats[away_team]['recent'].append(1)  # Win
                team_stats[home_team]['recent'].append(0)  # Loss
            
            # Keep only last 10 games for recent form
            team_stats[home_team]['recent'] = team_stats[home_team]['recent'][-10:]
            team_stats[away_team]['recent'] = team_stats[away_team]['recent'][-10:]
        
        # Calculate power rankings
        rankings = []
        
        for team, stats in team_stats.items():
            if stats['games'] < 5:  # Skip teams with few games
                continue
            
            win_pct = stats['wins'] / stats['games']
            point_diff = (stats['points_for'] - stats['points_against']) / stats['games']
            
            # Recent form (last 10 games)
            recent_win_pct = sum(stats['recent']) / len(stats['recent']) if stats['recent'] else 0
            
            # Power score calculation
            # Win percentage: 40% weight
            # Point differential: 30% weight  
            # Recent form: 20% weight
            # Games played (minimum threshold): 10% weight
            power_score = (
                (win_pct * 40) +
                (min(max(point_diff * 2, -20), 20) * 30) +  # Scale point diff, cap at ±20
                (recent_win_pct * 20) +
                (min(stats['games'] / 82, 1) * 10)  # Scale games played, max at 82
            )
            
            rankings.append({
                "team": team,
                "games": stats['games'],
                "wins": stats['wins'],
                "losses": stats['losses'],
                "record": f"{stats['wins']}-{stats['losses']}",
                "win_pct": round(win_pct * 100, 1),
                "points_for": stats['points_for'],
                "points_against": stats['points_against'],
                "point_diff": round(point_diff, 1),
                "point_diff_pg": round(point_diff, 1),
                "recent_win_pct": round(recent_win_pct * 100, 1),
                "power_score": round(power_score, 1)
            })
        
        # Sort by power score
        rankings.sort(key=lambda x: x['power_score'], reverse=True)
        
        # Add rank
        for i, team in enumerate(rankings):
            team['rank'] = i + 1
        
        return {
            "season": season,
            "through_games": len(games),
            "total_teams": len(rankings),
            "rankings": rankings
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating NBA power rankings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            await conn.close()


# Endpoint Aliases for Consistency
# ========================================================

@router.get("/nfl/teams")
async def get_nfl_teams():
    """Get list of NFL teams (alias for profiles endpoint)."""
    return await get_profile_list("nfl", entity_type="team")


@router.get("/nascar/drivers")
async def get_nascar_drivers():
    """Get list of NASCAR drivers (alias for profiles endpoint)."""
    return await get_profile_list("nascar", entity_type="driver")


@router.get("/nba/teams")
async def get_nba_teams():
    """Get list of NBA teams (alias for profiles endpoint)."""
    return await get_profile_list("nba", entity_type="team")


@router.get("/nfl/standings")
async def get_nfl_standings_alias():
    """Get NFL standings (alias for standings endpoint)."""
    from datetime import datetime
    current_year = datetime.now().year
    return await get_league_standings("nfl", current_year)


@router.get("/nba/standings")
async def get_nba_standings_alias():
    """Get NBA standings (alias for standings endpoint)."""
    from datetime import datetime
    current_year = datetime.now().year
    return await get_league_standings("nba", current_year)
