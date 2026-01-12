
import logging
import uuid
import threading
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

class TrainingJob:
    """Represents a single model training session."""
    def __init__(self, sport: str, model_type: str, config: Dict[str, Any]):
        self.id = str(uuid.uuid4())
        self.sport = sport
        self.model_type = model_type  # 'neural_network', 'xgboost', 'linear'
        self.config = config
        self.status = "created"  # created, running, completed, failed, stopped
        self.progress = 0.0
        self.current_epoch = 0
        self.total_epochs = config.get("epochs", 10)
        self.logs: List[str] = []
        self.metrics: Dict[str, List[float]] = {"loss": [], "accuracy": [], "val_loss": [], "val_accuracy": []}
        self.start_time = None
        self.end_time = None
        self.output_model_path = None
        self.error = None
        
        # Thread control
        self._stop_event = threading.Event()
        self._thread = None

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        # Keep logs manageable
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]

    def stop(self):
        self._stop_event.set()
        self.log("Stopping job requested...")

class TrainingOrchestrator:
    """Manages training jobs across different sports."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TrainingOrchestrator, cls).__new__(cls)
            cls._instance.jobs: Dict[str, TrainingJob] = {}
        return cls._instance

    def start_job(self, sport: str, model_type: str, config: Dict[str, Any]) -> str:
        """Start a new training job."""
        job = TrainingJob(sport, model_type, config)
        self.jobs[job.id] = job
        
        # Start in separate thread
        job._thread = threading.Thread(target=self._run_job, args=(job,))
        job._thread.daemon = True
        job._thread.start()
        
        logger.info(f"Started training job {job.id} for {sport} ({model_type})")
        return job.id

    def get_job(self, job_id: str) -> Optional[TrainingJob]:
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": j.id, 
                "sport": j.sport, 
                "status": j.status, 
                "progress": j.progress,
                "start_time": j.start_time
            }
            for j in self.jobs.values()
        ]

    def _run_job(self, job: TrainingJob):
        """Worker function that executes the actual training logic."""
        job.status = "running"
        job.start_time = datetime.now().isoformat()
        job.log(f"Starting training for {job.sport} - {job.model_type}")
        
        try:
            # Route to specific sport trainer
            if job.sport.lower() == "nba":
                if job.model_type == "neural_network":
                    from scripts.nba_ai_integration import train_nba_nn_wrapper
                    train_nba_nn_wrapper(job)
                else:
                    from scripts.nba_xgb_trainer import train_nba_model_wrapper
                    train_nba_model_wrapper(job)
            else:
                raise NotImplementedError(f"Training for {job.sport} not implemented yet")
                
            if not job._stop_event.is_set():
                job.status = "completed"
                job.progress = 100.0
                job.log("Training completed successfully.")
            else:
                job.status = "stopped"
                job.log("Training stopped by user.")
                
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.log(f"CRITICAL ERROR: {str(e)}")
            logger.error(f"Job {job.id} failed: {e}", exc_info=True)
            
        finally:
            job.end_time = datetime.now().isoformat()

# Singleton accessor
def get_orchestrator() -> TrainingOrchestrator:
    return TrainingOrchestrator()
