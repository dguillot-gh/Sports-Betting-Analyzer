
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from scripts.training_orchestrator import get_orchestrator

router = APIRouter(prefix="/lab", tags=["model_lab"])

class TrainingConfig(BaseModel):
    model_type: str = "xgboost"
    epochs: int = 500
    learning_rate: float = 0.05
    features: List[str] = []

@router.post("/train/{sport}")
async def start_training(sport: str, config: TrainingConfig):
    """Start a new isolated training job."""
    orchestrator = get_orchestrator()
    job_id = orchestrator.start_job(sport, config.model_type, config.dict())
    return {"job_id": job_id, "status": "started"}

@router.get("/jobs")
async def list_jobs():
    """List all training jobs."""
    orchestrator = get_orchestrator()
    return orchestrator.list_jobs()

@router.get("/jobs/{job_id}")
async def get_job_details(job_id: str):
    """Get detailed status, logs, and metrics for a job."""
    orchestrator = get_orchestrator()
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "id": job.id,
        "sport": job.sport,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs,
        "metrics": job.metrics,
        "output_path": job.output_model_path,
        "error": job.error,
        "start_time": job.start_time,
        "end_time": job.end_time
    }

@router.post("/promote/{job_id}")
async def promote_job(job_id: str):
    """Promote a job's trained model to the active 'Experimental' slot."""
    orchestrator = get_orchestrator()
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed jobs can be promoted")
        
    if not job.output_model_path:
        raise HTTPException(status_code=400, detail="Job has no output path")
        
    import shutil
    import os
    
    # Target directory for active experimental models
    target_dir = f"models/{job.sport}/experimental"
    os.makedirs(target_dir, exist_ok=True)
    
    source_dir = job.output_model_path
    
    try:
        # Copy all JSON models
        copied_files = []
        for filename in os.listdir(source_dir):
            if filename.endswith(".json"):
                 shutil.copy2(f"{source_dir}/{filename}", f"{target_dir}/{filename}")
                 copied_files.append(filename)
                 
        return {"status": "promoted", "files": copied_files, "target": target_dir}
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Failed to promote model: {e}")
