
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
