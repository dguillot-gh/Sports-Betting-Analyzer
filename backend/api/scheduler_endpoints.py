
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
