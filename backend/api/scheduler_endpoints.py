
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from services.scheduler import SchedulerService
from services.freshness_mapping import pick_best_import
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Scheduler"])
from api.db_endpoints import get_db_connection

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
async def trigger_manual_import(request: Request, background_tasks: BackgroundTasks):
    """
    Manually trigger the full import pipeline.
    Runs in background to avoid timeout.
    """
    # We use BackgroundTasks to allow immediate response, 
    # but SchedulerService internal lock prevents parallel execution anyway.
    background_tasks.add_task(SchedulerService.run_all_imports, trigger_source="manual")
    return {"status": "accepted", "message": "Import job queued (check logs for progress)"}

@router.get("/import-logs", response_model=List[ImportLogResponse])
async def get_import_logs(request: Request, limit: int = 50):
    """
    Get historical import logs.
    """
    conn = None
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT * FROM import_logs 
            ORDER BY start_time DESC 
            LIMIT $1
        """, limit)
        
        return [ImportLogResponse(**dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching import logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()


@router.get("/import-summary")
async def get_import_summary(request: Request):
    """
    Most recent completed import run per sport.
    Shows new vs updated at a glance for dashboards and mobile app.
    """
    conn = None
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT DISTINCT ON (sport)
                sport, status, start_time, end_time, duration_seconds,
                rows_imported, new_rows_imported, updated_rows_imported, error_message
            FROM import_logs
            WHERE status IN ('SUCCESS', 'FAILED')
            ORDER BY sport, start_time DESC
        """)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching import summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()


@router.get("/data-freshness")
async def get_data_freshness(request: Request):
    """
    Freshness check per sport. Returns:
    - total_records, latest_season, last_import_time, days_since_import
    - freshness_status: fresh (<2d) | stale (2-7d) | very_stale (>7d) | never
    Accessible by web and mobile clients.
    """
    from datetime import timezone

    conn = None
    try:
        conn = await get_db_connection()
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
        all_success_logs = list(import_map.values())

        now = datetime.now(timezone.utc)
        result = []
        for row in counts:
            sport = row["sport"]
            imp = pick_best_import(sport, all_success_logs)

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
                # Source-level staleness: ran successfully but got 0 new records
                "is_source_stale": (
                    imp is not None
                    and imp.get("new_rows_imported", 0) == 0
                    and imp.get("rows_imported", 0) > 0
                ) if imp else False,
            })

        return result
    except Exception as e:
        logger.error(f"Error fetching data freshness: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()

@router.get("/scheduler/status")
async def get_scheduler_status(request: Request):
    """
    Per-sport scheduler health for the ops dashboard.

    Returns, for every sport seen in import_logs:
      - last status / run time / duration / rows imported / error
      - consecutive_failures: how many latest runs have failed in a row
      - age_minutes: minutes since the last run (None if never)
    plus a rollup (healthy / degraded / down / never_run counts).

    Sports are flagged `down` on 3+ consecutive failures or staleness > 24h,
    `degraded` on 1-2 consecutive failures or staleness > 12h.
    """
    conn = None
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT sport, status, start_time, end_time, duration_seconds,
                   rows_imported, new_rows_imported, updated_rows_imported,
                   error_message
            FROM import_logs
            ORDER BY sport, start_time DESC
        """)
    except Exception as e:
        logger.warning(f"scheduler/status: database unavailable: {e}")
        raise HTTPException(status_code=503, detail="Scheduler database unavailable")
    finally:
        if conn:
            await conn.close()

    from datetime import datetime as _dt
    now = _dt.utcnow()

    # Group keeping newest-first order per sport
    per_sport: "dict[str, list]" = {}
    for r in rows:
        d = dict(r)
        per_sport.setdefault(d["sport"], []).append(d)

    sports = []
    counts = {"healthy": 0, "degraded": 0, "down": 0, "never_run": 0}

    for sport, runs in sorted(per_sport.items()):
        latest = runs[0]
        streak = 0
        for r in runs:
            if str(r["status"]).upper() == "FAILED":
                streak += 1
            else:
                break

        start = latest["start_time"]
        age_minutes = int((now - start).total_seconds() // 60) if start is not None else None

        if not runs:
            health = "never_run"
        elif streak >= 3 or (age_minutes is not None and age_minutes > 1440):
            health = "down"
        elif streak >= 1 or (age_minutes is not None and age_minutes > 720):
            health = "degraded"
        else:
            health = "healthy"

        counts[health] = counts.get(health, 0) + 1

        sports.append({
            "sport": sport,
            "health": health,
            "lastStatus": latest["status"],
            "lastRunAt": start.isoformat() if start else None,
            "lastRunEnd": latest["end_time"].isoformat() if latest["end_time"] else None,
            "ageMinutes": age_minutes,
            "durationSeconds": latest["duration_seconds"],
            "rowsImported": latest["rows_imported"],
            "newRows": latest["new_rows_imported"],
            "updatedRows": latest["updated_rows_imported"],
            "error": latest["error_message"],
            "consecutiveFailures": streak,
            "totalRuns": len(runs),
        })

    return {
        "generatedAt": now.isoformat() + "Z",
        "summary": counts,
        "sports": sports,
        "recentRuns": [
            {"sport": r["sport"], "status": r["status"], "start_time": r["start_time"],
             "rows_imported": r["rows_imported"], "error": r["error_message"]}
            for r in rows[:20]
        ],
    }

@router.post("/run-cbb-backfill")
async def trigger_cbb_backfill(request: Request, background_tasks: BackgroundTasks, years: str = "2024,2025"):
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

