
import logging
import uuid
import threading
import asyncio
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
            sport = job.sport.lower()

            if sport == "nba":
                if job.model_type == "neural_network":
                    from scripts.nba_ai_integration import train_nba_nn_wrapper
                    train_nba_nn_wrapper(job)
                else:
                    from scripts.nba_xgb_trainer import train_nba_model_wrapper
                    train_nba_model_wrapper(job)
            elif sport == "college_baseball":
                from scripts.college_baseball_xgb_trainer import train_cbb_model_wrapper
                train_cbb_model_wrapper(job)
            elif sport == "nfl":
                from scripts.nfl_xgb_trainer import train_nfl_model
                epochs = int(job.config.get("epochs", 500))
                job.log(f"Training NFL XGBoost model for {epochs} epochs...")
                result = asyncio.run(train_nfl_model(epochs=epochs))
                job.log(f"NFL training metrics: {result}")
                job.output_model_path = "models/nfl"
            elif sport == "nascar":
                from scripts.train_nascar_model import train_nascar_models
                job.log("Training NASCAR models...")
                train_nascar_models()
                job.log("NASCAR training completed.")
                job.output_model_path = "models/nascar"
            elif sport == "ncaab":
                from scripts.train_ncaab_model import train_v2
                job.log("Training NCAAB V2 models...")
                train_v2()
                job.log("NCAAB training completed.")
                job.output_model_path = "models/ncaab"
            elif sport == "nhl":
                from scripts.nhl_xgb_trainer import train_nhl_model
                epochs = int(job.config.get("epochs", 300))
                job.log(f"Training NHL XGBoost model for {epochs} epochs...")
                result = asyncio.run(train_nhl_model(epochs=epochs))
                job.log(f"NHL training metrics: {result}")
                job.output_model_path = "models/nhl"
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
