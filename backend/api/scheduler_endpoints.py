
from fastapi import APIRouter, HTTPException, BackgroundTasks
from services.scheduler import SchedulerService
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["Scheduler"])

class ImportLogResponse(BaseModel):
    id: int
    sport: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    rows_imported: int
    new_rows_imported: int = 0
    updated_rows_imported: int = 0
    files_processed: int = 0
    error_message: Optional[str] = None

@router.post("/run-imports")
async def trigger_manual_import(background_tasks: BackgroundTasks):
    """
    Manually trigger the full import pipeline.
    Runs in background to avoid timeout.
    """
    # We use BackgroundTasks to allow immediate response, 
    # but SchedulerService internal lock prevents parallel execution anyway.
    background_tasks.add_task(SchedulerService.run_all_imports, trigger_source="manual")
    return {"status": "accepted", "message": "Import job queued (check logs for progress)"}

@router.get("/import-logs", response_model=List[ImportLogResponse])
async def get_import_logs(limit: int = 50):
    """
    Get historical import logs.
    """
    import asyncpg
    from src.config import DATABASE_URL
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT * FROM import_logs 
            ORDER BY start_time DESC 
            LIMIT $1
        """, limit)
        
        return [dict(row) for row in rows]
    finally:
        await conn.close()


@router.get("/import-summary")
async def get_import_summary():
    """
    Most recent completed import run per sport.
    Shows new vs updated at a glance for dashboards and mobile app.
    """
    import asyncpg
    from src.config import DATABASE_URL
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (sport)
                sport, status, start_time, end_time, duration_seconds,
                rows_imported, new_rows_imported, updated_rows_imported, error_message
            FROM import_logs
            WHERE status IN ('SUCCESS', 'FAILED')
            ORDER BY sport, start_time DESC
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@router.get("/data-freshness")
async def get_data_freshness():
    """
    Freshness check per sport. Returns:
    - total_records, latest_season, last_import_time, days_since_import
    - freshness_status: fresh (<2d) | stale (2-7d) | very_stale (>7d) | never
    Accessible by web and mobile clients.
    """
    import asyncpg
    from src.config import DATABASE_URL
    from datetime import timezone

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        counts = await conn.fetch("""
            SELECT s.name AS sport,
                   COUNT(r.id) AS total_records,
                   MAX(r.season) AS latest_season
            FROM sports s
            LEFT JOIN results r ON r.sport_id = s.id
            GROUP BY s.name
            ORDER BY s.name
        """)

        last_imports = await conn.fetch("""
            SELECT DISTINCT ON (sport)
                sport, status, start_time, new_rows_imported, rows_imported
            FROM import_logs
            WHERE status = 'SUCCESS'
            ORDER BY sport, start_time DESC
        """)
        import_map = {r["sport"]: dict(r) for r in last_imports}

        now = datetime.now(timezone.utc)
        result = []
        for row in counts:
            sport = row["sport"]
            imp = import_map.get(sport)

            last_import_time = None
            days_since_import = None
            freshness_status = "never"

            if imp and imp["start_time"]:
                last_import_time = imp["start_time"]
                if last_import_time.tzinfo is None:
                    last_import_time = last_import_time.replace(tzinfo=timezone.utc)
                days_since_import = (now - last_import_time).days
                if days_since_import <= 1:
                    freshness_status = "fresh"
                elif days_since_import <= 7:
                    freshness_status = "stale"
                else:
                    freshness_status = "very_stale"

            result.append({
                "sport": sport,
                "total_records": row["total_records"],
                "latest_season": row["latest_season"],
                "last_import_time": last_import_time.isoformat() if last_import_time else None,
                "days_since_import": days_since_import,
                "last_import_new_rows": imp["new_rows_imported"] if imp else 0,
                "last_import_total_rows": imp["rows_imported"] if imp else 0,
                "freshness_status": freshness_status,
            })

        return result
    finally:
        await conn.close()

@router.post("/run-cbb-backfill")
async def trigger_cbb_backfill(background_tasks: BackgroundTasks, years: str = "2024,2025"):
    """
    Trigger backfill of College Baseball game results.
    """
    import subprocess
    import sys
    import os
    
    # Run in background to avoid blocking
    def run_script(year_list: List[str]):
        script_path = os.path.join("scripts", "backfill_college_baseball.py")
        if not os.path.exists(script_path):
             # Try absolute path from backend root
             script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_college_baseball.py"))
             
        cmd = [sys.executable, script_path] + year_list
        try:
            # We don't want to capture output here, just let it log to file/stdout
            subprocess.run(cmd, check=True)
            print("CBB Backfill completed successfully")
        except Exception as e:
            print(f"CBB Backfill failed: {e}")
            
    year_list = [y.strip() for y in years.split(",")]
    background_tasks.add_task(run_script, year_list)
    return {"status": "started", "message": f"Backfill queued for years {years}"}
