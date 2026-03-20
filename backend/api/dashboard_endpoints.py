
from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any, List, Optional
import json
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

REPO_ROOT = Path(__file__).parent.parent

@router.get("/model-summary")
async def get_model_summary(request: Request):
    """
    Scans the models/ directory and returns an aggregated summary of all 
    trained models and their metrics.
    """
    try:
        models_base = REPO_ROOT / "models"
        if not models_base.exists():
            return []

        summary = []
        
        # We want to find all *_metrics.json files
        # They are usually at models/{sport}/{task}/... or models/{sport}/{series}/{task}/...
        for metrics_path in models_base.rglob("*_metrics.json"):
            try:
                # Relative path to models/
                rel_path = metrics_path.relative_to(models_base)
                parts = rel_path.parts
                
                # Part structure varies: 
                # e.g. nba/default/classification_metrics.json -> parts = (nba, default, classification_metrics.json)
                # e.g. nascar/cup/race_win/classification_metrics.json -> (nascar, cup, race_win, classification_metrics.json)
                
                if len(parts) < 2: continue
                
                sport = parts[0]
                task = parts[-2] # The directory containing the metrics file is usually the task name
                series = "/".join(parts[1:-2]) if len(parts) > 3 else parts[1]
                
                with open(metrics_path, "r") as f:
                    metrics = json.load(f)
                
                # Extract interesting metrics
                accuracy = metrics.get("accuracy", metrics.get("val_accuracy", 0))
                precision = metrics.get("precision", 0)
                roi = metrics.get("roi", 0) # Non-standard but good to have
                
                # Use mean if it's a list (some metrics are recorded per epoch)
                if isinstance(accuracy, list) and accuracy: accuracy = accuracy[-1]
                
                summary.append({
                    "sport": sport,
                    "series": series,
                    "task": task,
                    "accuracy": round(accuracy, 3) if accuracy else 0,
                    "precision": round(precision, 3) if precision else 0,
                    "roi": round(roi, 1) if roi else 0,
                    "last_updated": os.path.getmtime(metrics_path)
                })
            except Exception as e:
                logger.warning(f"Error parsing metrics at {metrics_path}: {e}")

        # Sort by accuracy descending
        summary.sort(key=lambda x: x["accuracy"], reverse=True)
        
        return summary
    except Exception as e:
        logger.error(f"Dashboard summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
