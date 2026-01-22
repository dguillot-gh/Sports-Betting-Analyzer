
"""
Scheduler Service
Handles automated data imports, job locking, retries, and database logging.
"""

import logging
import asyncio
import traceback
from datetime import datetime
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Optional, Dict, Any, List

from src.config import DATABASE_URL
from services.notifications import NotificationService

#Script imports
from scripts.ncaab_importer import import_ncaab_data
from scripts.migrate_data import run_migration
from scripts.rda_importer import import_nascar_rda
from scripts.college_baseball_importer import run_college_baseball_import

logger = logging.getLogger(__name__)

CREATE_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS import_logs (
    id SERIAL PRIMARY KEY,
    sport VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    start_time TIMESTAMPTZ DEFAULT NOW(),
    end_time TIMESTAMPTZ,
    duration_seconds FLOAT,
    rows_imported INTEGER DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_logs_status ON import_logs(status);
CREATE INDEX IF NOT EXISTS idx_import_logs_start_time ON import_logs(start_time);
"""

class SchedulerService:
    _scheduler: Optional[AsyncIOScheduler] = None
    _is_running_job = False  # In-memory lock for safety
    
    @classmethod
    async def init_db(cls):
        """Initialize the import_logs table."""
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.execute(CREATE_LOGS_TABLE_SQL)
            await conn.close()
            logger.info("Scheduler tables initialized.")
        except Exception as e:
            logger.error(f"Failed to init scheduler DB: {e}")

    @classmethod
    def start_scheduler(cls):
        """Start the background scheduler."""
        if cls._scheduler and cls._scheduler.running:
            return

        cls._scheduler = AsyncIOScheduler()
        
        # Schedule Daily Import at 3:00 AM
        cls._scheduler.add_job(
            cls.run_all_imports,
            CronTrigger(hour=3, minute=0),
            id="daily_import",
            replace_existing=True
        )
        
        cls._scheduler.start()
        logger.info("APScheduler started. Job 'daily_import' scheduled for 03:00.")

    @classmethod
    async def run_all_imports(cls, trigger_source: str = "auto"):
        """
        Master job to run all sport imports sequentially.
        """
        # 1. ACQUIRE LOCK
        if cls._is_running_job:
            logger.warning("Import job already running. Skipping this instruction.")
            return {"status": "skipped", "reason": "Job already locked"}
        
        cls._is_running_job = True
        logger.info(f"Starting pipeline ({trigger_source})...")
        
        results = []
        
        try:
            # --- 1. NCAAB ---
            res_ncaab = await cls._run_job_wrapper("ncaab", cls._import_ncaab_task)
            results.append(res_ncaab)
            
            # --- 2. NBA ---
            res_nba = await cls._run_job_wrapper("nba", cls._import_nba_task)
            results.append(res_nba)
            
            # --- 3. NFL ---
            res_nfl = await cls._run_job_wrapper("nfl", cls._import_nfl_task)
            results.append(res_nfl)

            # --- 4. NASCAR ---
            res_nascar = await cls._run_job_wrapper("nascar", cls._import_nascar_task)
            results.append(res_nascar)

            # --- 5. College Baseball ---
            res_baseball = await cls._run_job_wrapper("baseball", cls._import_baseball_task)
            results.append(res_baseball)
            
            # --- Send Notification ---
            await NotificationService.send_summary_report(results)
            
            # Explicitly log completion
            logger.info("Pipeline Execution Finished.")
            
            return {"status": "completed", "results": results}
            
        except Exception as e:
            logger.critical(f"Critical error in scheduler pipeline: {e}")
            return {"status": "failed", "error": str(e)}
        finally:
            # RELEASE LOCK
            cls._is_running_job = False

    @staticmethod
    async def _run_job_wrapper(sport: str, func) -> Dict[str, Any]:
        """
        Wrapper to handle DB logging, timing, and retries.
        """
        import asyncpg
        conn = None
        log_id = None
        start_time = datetime.now()
        
        try:
             # Connect to DB to create log entry
            conn = await asyncpg.connect(DATABASE_URL)
            
            # Create IN_PROGRESS log
            log_id = await conn.fetchval("""
                INSERT INTO import_logs (sport, status, start_time)
                VALUES ($1, 'IN_PROGRESS', NOW())
                RETURNING id
            """, sport)
            
            # EXECUTE FUNCTION
            logger.info(f"Running task for {sport}...")
            result_data = await func() 
            
            # Success logic
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'SUCCESS', end_time = NOW(), duration_seconds = $2,
                    rows_imported = $3, error_message = NULL
                WHERE id = $1
            """, log_id, duration, result_data.get("rows", 0))
            
            logger.info(f"Task {sport} finished successfully.")
            
            return {
                "sport": sport,
                "success": True,
                "duration": duration,
                "rows": result_data.get("rows", 0)
            }
            
        except Exception as e:
            # Failure logic
            logger.error(f"Task {sport} failed: {e}")
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            error_msg = str(e)
            
            if conn and log_id:
                try:
                    await conn.execute("""
                        UPDATE import_logs 
                        SET status = 'FAILED', end_time = NOW(), duration_seconds = $2,
                            error_message = $3
                        WHERE id = $1
                    """, log_id, duration, error_msg)
                except Exception as log_err:
                    logger.error(f"Failed to update error log: {log_err}")
            
            return {
                "sport": sport,
                "success": False,
                "duration": duration,
                "error": error_msg
            }
        finally:
            if conn:
                await conn.close()

    # --- Worker Tasks ---
    
    @staticmethod
    async def _import_ncaab_task():
        """Worker for NCAAB (2018-Current)."""
        current_year = datetime.now().year + 1 
        res = await import_ncaab_data(start_year=2018, end_year=current_year)
        if not res.get("success"):
             raise Exception(res.get("error", "Unknown error in NCAAB script"))
        rows = res.get("games_processed", 0)
        return {"rows": rows}

    @staticmethod
    async def _import_nba_task():
        """Worker for NBA."""
        # Uses migrate_data script logic
        await run_migration("nba")
        return {"rows": 1} # Row count not returned by migration yet

    @staticmethod
    async def _import_nfl_task():
        """Worker for NFL."""
        await run_migration("nfl")
        return {"rows": 1}

    @staticmethod
    async def _import_nascar_task():
        """Worker for NASCAR (RDA 2012-Current)."""
        current_year = datetime.now().year
        res = await import_nascar_rda(year_start=2012, year_end=current_year, clear_existing=False)
        
        # Calculate rows
        rows = 0
        if res.get("series_results"):
             rows = sum(r['results_imported'] for r in res['series_results'])
             
        return {"rows": rows}

    @staticmethod
    async def _import_baseball_task():
        """Worker for College Baseball (Current Year)."""
        current_year = datetime.now().year
        res = await run_college_baseball_import(division=1, year=current_year, source="auto")
        
        if not res.get("success"):
            raise Exception(res.get("message", "Unknown baseball import error"))
            
        return {"rows": res.get("imported_teams", 0)}
