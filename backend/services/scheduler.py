
"""
Scheduler Service
Handles automated data imports, job locking, retries, and database logging.
"""

import logging
import asyncio
import json
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Optional, Dict, Any, List

CST = ZoneInfo("America/Chicago")

from src.config import DATABASE_URL
from src.ops_alerts import OpsAlertService
from services.notifications import NotificationService

#Script imports
from scripts.ncaab_importer import import_ncaab_data
from scripts.migrate_data import run_migration
from scripts.nascar_parquet_importer import run_import as import_nascar_parquet
from scripts.nascar_supplemental_importer import run_import as import_nascar_supplemental
from scripts.college_baseball_importer import run_college_baseball_import
from scripts.college_football_importer import run_college_football_import

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
    new_rows_imported INTEGER DEFAULT 0,
    updated_rows_imported INTEGER DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migrate existing tables that were created before these columns were added
ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS new_rows_imported INTEGER DEFAULT 0;
ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS updated_rows_imported INTEGER DEFAULT 0;
ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS files_processed INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_import_logs_status ON import_logs(status);
CREATE INDEX IF NOT EXISTS idx_import_logs_start_time ON import_logs(start_time);
"""

RESULTS_UPDATED_AT_SQL = """
ALTER TABLE results ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE OR REPLACE FUNCTION update_results_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    -- On INSERT always set updated_at
    IF TG_OP = 'INSERT' THEN
        NEW.updated_at = NOW();
    -- On UPDATE only bump updated_at when metadata actually changed;
    -- prevents no-op re-upserts from inflating "updated" counts.
    ELSIF OLD.metadata IS DISTINCT FROM NEW.metadata THEN
        NEW.updated_at = NOW();
    ELSE
        NEW.updated_at = OLD.updated_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_results_updated_at ON results;
CREATE TRIGGER trg_results_updated_at
    BEFORE INSERT OR UPDATE ON results
    FOR EACH ROW
    EXECUTE FUNCTION update_results_updated_at();

CREATE INDEX IF NOT EXISTS idx_results_updated_at ON results(updated_at);
"""

# Maps scheduler sport keys to the sports table name
_SPORT_DB_NAME = {
    "ncaab": "ncaab",
    "nba": "nba",
    "nfl": "nfl",
    "nascar": "nascar",
    "baseball": "college_baseball",
    "nhl": "nhl",
    "cfb": "cfb",
    "baseball_results": "college_baseball",
    "nascar_supplemental": "nascar",
    "mlb_results": "mlb",
    "mlb_stats": "mlb",
}

def _compact_detail(meta: dict, max_len: int = 120) -> str:
    """Build a short human-readable summary from result metadata for CSV."""
    parts = []
    for key in ("finish", "start", "pts", "status", "home_score", "away_score",
                "race_name", "week", "game_date"):
        val = meta.get(key)
        if val is not None and str(val).strip():
            parts.append(f"{key}={val}")
    detail = ", ".join(parts)
    return detail[:max_len] if len(detail) > max_len else detail


class SchedulerService:
    _scheduler: Optional[AsyncIOScheduler] = None
    _is_running_job = False  # In-memory lock for safety
    
    @classmethod
    async def init_db(cls):
        """Initialize the import_logs table and results updated_at column."""
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.execute(CREATE_LOGS_TABLE_SQL)
            await conn.execute(RESULTS_UPDATED_AT_SQL)
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
        all_import_records: List[Dict[str, Any]] = []  # detailed row-level records
        
        try:
            # --- 1. NCAAB ---
            res_ncaab = await cls._run_job_wrapper("ncaab", cls._import_ncaab_task)
            results.append(res_ncaab)
            
            # --- 2. NBA ---
            res_nba = await cls._run_job_wrapper("nba", cls._import_nba_task)
            results.append(res_nba)
            
            # --- 2b. NBA Backtest ---
            res_nba_bt = await cls._run_job_wrapper("nba_backtest", cls._backtest_nba_task)
            results.append(res_nba_bt)
            
            # --- 3. NFL ---
            res_nfl = await cls._run_job_wrapper("nfl", cls._import_nfl_task)
            results.append(res_nfl)

            # --- 4. NASCAR (Parquet) ---
            res_nascar = await cls._run_job_wrapper("nascar", cls._import_nascar_task)
            results.append(res_nascar)

            # --- 4b. NASCAR (Supplemental — DriverAverages + Live Feed) ---
            res_nascar_supp = await cls._run_job_wrapper("nascar_supplemental", cls._import_nascar_supplemental_task)
            results.append(res_nascar_supp)

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

            # --- 9. College Football ---
            res_cfb = await cls._run_job_wrapper("cfb", cls._import_cfb_task)
            results.append(res_cfb)

            # --- 10. MLB Game Results ---
            res_mlb_results = await cls._run_job_wrapper("mlb_results", cls._import_mlb_results_task)
            results.append(res_mlb_results)

            # --- 10b. MLB Stats Collection ---
            res_mlb = await cls._run_job_wrapper("mlb_stats", cls._mlb_stats_collection_task)
            results.append(res_mlb)

            # --- 11. MLB Model Training ---
            res_mlb_train = await cls._run_job_wrapper("mlb_training", cls._mlb_model_training_task)
            results.append(res_mlb_train)
            
            # --- 12. Collect all import records for the email CSV ---
            for res in results:
                all_import_records.extend(res.get("_records", []))
            
            # --- 13. Fetch Performance Summary ---
            perf_summary = await cls._get_performance_summary()

            # Alert on any failed import jobs in the run.
            OpsAlertService.report_import_failures(results, trigger_source)
            
            # --- Send Notification (with CSV of import records) ---
            await NotificationService.send_summary_report(results, perf_summary, all_import_records)
            
            # --- Check Database Health ---
            await OpsAlertService.check_database_health(DATABASE_URL)

            # Explicitly log completion
            logger.info(f"Pipeline Execution Finished. {len(all_import_records)} records collected for email.")
            
            return {"status": "completed", "results": results, "performance": perf_summary}
            
        except Exception as e:
            logger.critical(f"Critical error in scheduler pipeline: {e}")
            return {"status": "failed", "error": str(e)}
        finally:
            # RELEASE LOCK
            cls._is_running_job = False

    @staticmethod
    async def _collect_import_records(conn, sport_key: str, since: datetime, limit: int = 10000) -> List[Dict[str, Any]]:
        """
        Query the results table for records inserted or updated since `since`
        for the given sport. Returns a list of dicts suitable for the CSV report.
        """
        db_sport = _SPORT_DB_NAME.get(sport_key)
        if not db_sport:
            return []
        
        try:
            sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", db_sport)
            if not sport_id:
                return []
            
            # Get actual count first for logging
            actual_count = await conn.fetchval("""
                SELECT COUNT(*) FROM results r
                WHERE r.sport_id = $1 AND r.updated_at >= $2
            """, sport_id, since)
            
            if actual_count and actual_count > limit:
                logger.warning(f"[{sport_key}] {actual_count:,} records touched but CSV capped at {limit:,}")
            
            rows = await conn.fetch("""
                SELECT r.id, r.season, r.series, r.track, r.metadata, r.created_at, r.updated_at
                FROM results r
                WHERE r.sport_id = $1 AND r.updated_at >= $2
                ORDER BY r.id
                LIMIT $3
            """, sport_id, since, limit)
            
            records = []
            for row in rows:
                meta = {}
                if row["metadata"]:
                    try:
                        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                    except Exception:
                        pass
                
                # Determine if record is new or updated (handle tz-naive vs tz-aware)
                is_new = True
                try:
                    created = row["created_at"]
                    if created:
                        if created.tzinfo is None and since.tzinfo is not None:
                            created = created.replace(tzinfo=timezone.utc)
                        is_new = created >= since
                except Exception:
                    pass
                action = "inserted" if is_new else "updated"
                
                # Build a flat record for CSV
                entity = (
                    meta.get("driver_name") or meta.get("Driver")
                    or meta.get("home_team") or meta.get("home")
                    or meta.get("name") or meta.get("team")
                    or row.get("track") or "—"
                )
                records.append({
                    "sport": sport_key,
                    "action": action,
                    "season": row["season"],
                    "series": row["series"] or "",
                    "entity": str(entity),
                    "track": row["track"] or "",
                    "detail": _compact_detail(meta),
                })
            return records
        except Exception as e:
            logger.warning(f"Failed to collect import records for {sport_key}: {e}")
            return []

    @staticmethod
    async def _run_job_wrapper(sport: str, func) -> Dict[str, Any]:
        """
        Wrapper to handle DB logging, timing, and retries.
        """
        import asyncpg
        conn = None
        log_id = None
        start_time = datetime.now(CST)
        
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
            end_time = datetime.now(CST)
            duration = (end_time - start_time).total_seconds()
            
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'SUCCESS', end_time = NOW(), duration_seconds = $2,
                    rows_imported = $3, new_rows_imported = $4, updated_rows_imported = $5,
                    files_processed = $6, error_message = NULL
                WHERE id = $1
            """, log_id, duration, result_data.get("rows", 0), result_data.get("new", 0), result_data.get("updated", 0), result_data.get("files", 0))
            
            # Collect detailed records that were inserted/updated during this task
            import_records = await SchedulerService._collect_import_records(conn, sport, start_time)
            
            logger.info(f"Task {sport} finished successfully. {len(import_records)} records collected.")
            
            return {
                "sport": sport,
                "success": True,
                "duration": duration,
                "rows": result_data.get("rows", 0),
                "new": result_data.get("new", 0),
                "updated": result_data.get("updated", 0),
                "_records": import_records,
            }
            
        except Exception as e:
            # Failure logic
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"Task {sport} failed: {e}\n{error_traceback}")
            
            end_time = datetime.now(CST)
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
                "error": error_msg,
                "traceback": error_traceback,
                "_records": [],
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
        return {
            "rows": res.get("rows", 0),
            "new": res.get("new", 0),
            "updated": res.get("updated", 0)
        }

    @staticmethod
    async def _import_nba_task():
        """Worker for NBA (BR + Kaggle)."""
        from scripts.nba_importer import import_all_nba
        def log_progress(msg):
            logger.info(f"[NBA Import] {msg}")
            
        res = await import_all_nba(clear_existing=False, progress_callback=log_progress)
        
        if res.get("status") == "failed":
             raise Exception(f"NBA import failed: {res.get('errors')}")
             
        return {
            "rows": res.get("games_imported", 0) + res.get("players_imported", 0),
            "new": res.get("games_new", 0) + res.get("players_new", 0),
            "updated": res.get("games_updated", 0) + res.get("players_updated", 0),
            "files": len(res.get("downloaded", []))
        }

    @staticmethod
    async def _backtest_nba_task():
        """Worker for Nightly NBA Backtest."""
        from scripts.nba_backtesting import run_nba_backtest
        res = await run_nba_backtest(min_edge=0.04, stake=100.0, use_kelly=False)
        return {
            "rows": res.get("total_bets", 0),
            "new": res.get("wins", 0),  # Tracking wins just to populate the DB fields somewhat relevantly
            "updated": 0,
            "detail": f"ROI: {res.get('roi', 0):.1f}%"
        }

    @staticmethod
    async def _import_nfl_task():
        """Worker for NFL (nflverse)."""
        from scripts.nfl_importer import import_all_nfl
        def log_progress(msg):
            logger.info(f"[NFL Import] {msg}")
            
        res = await import_all_nfl(progress_callback=log_progress)
        
        if res.get("status") == "failed":
             raise Exception(f"NFL import failed: {res.get('errors')}")
             
        total = (res.get("players_imported", 0) + 
                 res.get("weekly_stats_imported", 0) + 
                 res.get("season_stats_imported", 0) + 
                 res.get("schedules_imported", 0))
                 
        new = (res.get("players_new", 0) + 
               res.get("weekly_stats_new", 0) + 
               res.get("season_stats_new", 0) + 
               res.get("schedules_new", 0))
               
        updated = (res.get("players_updated", 0) + 
                   res.get("weekly_stats_updated", 0) + 
                   res.get("season_stats_updated", 0) + 
                   res.get("schedules_updated", 0))
        
        return {
            "rows": total,
            "new": new,
            "updated": updated,
            "files": len(res.get("downloaded", []))
        }

    @staticmethod
    async def _import_nascar_task():
        """Worker for NASCAR (Parquet 2026+).
        
        Fetches latest race results directly from Cloudflare R2 Parquet sources.
        Replacing the outdated .rda sync.
        """
        res = await import_nascar_parquet()
        return {
            "rows": res.get("rows", 0),
            "new": res.get("new", 0),
            "updated": res.get("updated", 0)
        }

    @staticmethod
    async def _import_nascar_supplemental_task():
        """Worker for NASCAR supplemental data (DriverAverages + NASCAR.com live feed).
        
        Fills gaps when the parquet source is stale and adds live-feed
        extras (speed, pit stops, passing stats) for the latest race.
        Covers Cup, Xfinity, and Trucks.
        """
        def log_progress(msg):
            logger.info(f"[NASCAR Supplemental] {msg}")

        res = await import_nascar_supplemental(
            year=datetime.now().year,
            progress_callback=log_progress,
        )
        return {
            "rows": res.get("rows", 0),
            "new": res.get("new", 0),
            "updated": res.get("updated", 0),
        }

    @staticmethod
    async def _import_baseball_task():
        """Worker for College Baseball."""
        from scripts.college_baseball_importer import run_college_baseball_import
        res = await run_college_baseball_import(division=1, year=datetime.now().year)
        
        if not res.get("success") and res.get("message") == "All import sources failed":
             raise Exception("College Baseball import failed: All sources failed")
             
        return {
            "rows": res.get("rows", 0),
            "new": res.get("new", 0),
            "updated": res.get("updated", 0)
        }

    @staticmethod
    async def _scrape_baseball_results_task():
        """Worker for College Baseball game results scraping (ESPN)."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores, store_game_results
        games = await fetch_college_baseball_scores(days_back=2)
        summary = await store_game_results(games)
        return {
            "rows": summary.get("rows", 0),
            "new": summary.get("new", 0),
            "updated": summary.get("updated", 0),
            "games_fetched": len(games),
            "games_inserted": summary.get("new", 0),
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
    async def _import_cfb_task():
        """Worker for College Football (sportsdataverse)."""
        res = await run_college_football_import(import_type="all")
        if not res.get("success"):
            raise Exception(f"CFB import failed: {res.get('message')}")
        return {
            "rows": res.get("rows", 0),
            "new": res.get("new", 0),
            "updated": res.get("updated", 0)
        }

    @staticmethod
    async def _import_nhl_task():
        """Worker for NHL (MoneyPuck + NHL API)."""
        from scripts.nhl_importer import import_all_nhl
        res = await import_all_nhl(clear_existing=False)
        
        total = res.get("games_imported", 0) + res.get("players_imported", 0)
        new_cnt = res.get("games_new", 0) + res.get("players_new", 0)
        updated_cnt = res.get("games_updated", 0) + res.get("players_updated", 0)
        
        if res.get("status") == "failed":
            raise Exception(f"NHL import failed: {res.get('errors')}")
        
        return {
            "rows": total,
            "new": new_cnt,
            "updated": updated_cnt
        }

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

    @staticmethod
    async def _import_mlb_results_task():
        """Import completed MLB game results from MLB Stats API."""
        try:
            from scripts.mlb_results_importer import run_import
            result = await run_import()
            total = result.get('total_imported', 0)
            logger.info(f"MLB results import finished: {total} games")
            return {
                "rows": total,
                "new": total,
                "updated": 0,
            }
        except Exception as e:
            logger.error(f"MLB results import failed: {e}")
            raise

    @staticmethod
    async def _mlb_stats_collection_task():
        """Nightly MLB data collection — team stats, pitcher stats."""
        try:
            from scripts.mlb_stats_collector import run_full_collection
            result = await run_full_collection()
            teams = result.get('team_rows_saved', 0)
            pitchers = result.get('pitcher_rows_saved', 0)
            logger.info(f"MLB stats collection finished: {teams} teams, {pitchers} pitchers")
            return {
                "rows": teams + pitchers,
                "new": result.get('new', 0),
                "updated": result.get('updated', 0),
            }
        except Exception as e:
            logger.error(f"MLB stats collection failed: {e}")
            raise

    @staticmethod
    async def _mlb_model_training_task():
        """Scheduled MLB model retraining."""
        try:
            from scripts.mlb_train_models import train_all_models
            from scripts.mlb_predictor import reload_models
            result = await train_all_models()
            if result.get("success"):
                reload_models()
                logger.info(f"MLB model training completed successfully")
            else:
                logger.warning(f"MLB model training completed with issues: {result}")
            return result
        except Exception as e:
            logger.error(f"MLB model training failed: {e}")
            return {"error": str(e)}

    @staticmethod
    async def _get_performance_summary() -> Dict[str, Any]:
        """
        Fetch summary of betting results from last 24 hours.
        Also calculates total DB record count.
        """
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # 1. Graded bets in last 24h
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE outcome = 'win') as wins,
                    COUNT(*) FILTER (WHERE outcome = 'loss') as losses,
                    COALESCE(SUM(profit), 0) as net_profit,
                    COALESCE(SUM(stake), 0) as total_staked
                FROM bets 
                WHERE (outcome = 'win' OR outcome = 'loss') 
                AND created_at > NOW() - INTERVAL '24 hours'
            """)
            
            # 2. Total record count for analyzer health
            total_records = await conn.fetchval("SELECT COUNT(*) FROM results")
            
            roi = 0
            if stats['total_staked'] > 0:
                roi = (stats['net_profit'] / stats['total_staked']) * 100
                
            return {
                "total": stats['total'],
                "wins": stats['wins'],
                "losses": stats['losses'],
                "profit": float(stats['net_profit']),
                "roi": round(float(roi), 2),
                "db_total_rows": total_records
            }
        except Exception as e:
            logger.error(f"Failed to fetch performance summary: {e}")
            return {"error": str(e)}
        finally:
            await conn.close()
