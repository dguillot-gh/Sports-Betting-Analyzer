
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
from scripts.nascar_parquet_importer import run_import as import_nascar_parquet
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
        
        # Schedule Daily Import at 3:00 AM CST (9:00 AM UTC)
        cls._scheduler.add_job(
            cls.run_all_imports,
            CronTrigger(hour=9, minute=0),
            id="daily_import",
            replace_existing=True
        )

        # Schedule Bet Grading every 6 hours
        cls._scheduler.add_job(
            cls._grade_bets_task,
            'interval',
            hours=6,
            id="bet_grading",
            replace_existing=True
        )

        # Schedule Closing Line Capture every 30 minutes
        cls._scheduler.add_job(
            cls._capture_closing_lines_task,
            'interval',
            minutes=30,
            id="capture_closing_lines",
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

            # --- 6. NHL ---
            res_nhl = await cls._run_job_wrapper("nhl", cls._import_nhl_task)
            results.append(res_nhl)

            # --- 7. College Baseball Game Results (ESPN) ---
            res_bb_results = await cls._run_job_wrapper("baseball_results", cls._scrape_baseball_results_task)
            results.append(res_bb_results)

            # --- 8. College Baseball Model Retraining ---
            res_bb_train = await cls._run_job_wrapper("baseball_training", cls._retrain_baseball_models_task)
            results.append(res_bb_train)
            
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
        from scripts.nba_importer import import_all_nba
        res = await import_all_nba(clear_existing=False) # Don't clear history on auto-run
        
        # Sum up imported items
        rows = (res.get("games_imported", 0) + 
                res.get("players_imported", 0) + 
                res.get("box_scores_imported", 0) +
                res.get("br_stats_imported", 0) +
                res.get("br_stats_computed", 0) +
                res.get("season_stats_imported", 0))
        
        if res.get("status") == "failed":
             raise Exception(f"NBA import failed: {res.get('errors')}")
             
        return {"rows": rows}

    @staticmethod
    async def _import_nfl_task():
        """Worker for NFL."""
        from scripts.nfl_importer import import_all_nfl
        res = await import_all_nfl(clear_existing=False)
        
        rows = (res.get("games_imported", 0) + 
                res.get("players_imported", 0) + 
                res.get("stats_computed", 0) +
                res.get("schedules_imported", 0) +
                res.get("weekly_stats_imported", 0) +
                res.get("season_stats_imported", 0))

        if res.get("status") == "failed":
             raise Exception(f"NFL import failed: {res.get('errors')}")

        return {"rows": rows}

    @staticmethod
    async def _import_nascar_task():
        """Worker for NASCAR (Parquet 2026+).
        
        Fetches latest race results directly from Cloudflare R2 Parquet sources.
        Replacing the outdated .rda sync.
        """
        rows = await import_nascar_parquet()
        return {"rows": rows or 0}

    @staticmethod
    async def _import_baseball_task():
        """Worker for College Baseball."""
        from scripts.college_baseball_importer import run_college_baseball_import
        res = await run_college_baseball_import(division=1, year=datetime.now().year)
        
        # Capture from flat 'rows' key or 'imported_teams'
        rows = res.get("rows", res.get("imported_teams", 0))
        
        if not res.get("success") and res.get("message") == "All import sources failed":
             raise Exception("College Baseball import failed: All sources failed")
             
        return {"rows": rows}

    @staticmethod
    async def _scrape_baseball_results_task():
        """Worker for College Baseball game results scraping (ESPN)."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores, store_game_results
        games = await fetch_college_baseball_scores(days_back=2)
        inserted = await store_game_results(games)
        return {
            "rows": inserted,
            "games_fetched": len(games),
            "games_inserted": inserted,
            "game_details": games[:20],  # Include up to 20 games for email report
        }

    @staticmethod
    async def _retrain_baseball_models_task():
        """Worker for retraining College Baseball XGBoost models."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer
        trainer = CollegeBaseballXGBTrainer()
        trainer.train_from_csvs()
        return {"rows": 0, "detail": "Stat-based models retrained"}

    @staticmethod
    async def _import_nhl_task():
        """Worker for NHL (MoneyPuck + NHL API)."""
        from scripts.nhl_importer import import_all_nhl
        res = await import_all_nhl(clear_existing=False)
        
        rows = res.get("games_imported", 0) + res.get("players_imported", 0)
        
        if res.get("status") == "failed":
            raise Exception(f"NHL import failed: {res.get('errors')}")
        
        return {"rows": rows}

    @staticmethod
    async def _grade_bets_task():
        """Worker for automated bet grading."""
        try:
            from services.bet_grader import BetGrader
            grader = BetGrader()
            count = await grader.grade_all_pending()
            logger.info(f"Auto-grader job finished. Graded {count} bets.")
            return {"rows": count}
        except Exception as e:
            logger.error(f"Bet grading task failed: {e}")
            return {"rows": 0, "error": str(e)}

    @staticmethod
    async def _capture_closing_lines_task():
        """Worker for capturing closing lines at game start."""
        try:
            from services.clv_calculator import CLVCalculator
            calc = CLVCalculator()
            count = await calc.snapshot_closing_lines()
            logger.info(f"Closing line capture finished. Updated {count} bets.")
            return {"rows": count}
        except Exception as e:
            logger.error(f"Closing line capture failed: {e}")
            return {"rows": 0, "error": str(e)}
