"""
Model Governance endpoints — operator kill-switch + rollback for deployed models.
"""
from fastapi import APIRouter, HTTPException

from src.model_governance import (
    list_models,
    set_enabled,
    back_up_models,
    rollback,
)

router = APIRouter(prefix="/governance", tags=["model_governance"])


@router.get("/models")
def inventory():
    """List deployed models per sport (path, mtime, size, backup, enabled)."""
    return {"models": list_models()}


@router.get("/models/is-disabled/{sport}")
def is_disabled(sport: str):
    from src.model_governance import is_disabled as _is_disabled
    return {"sport": sport.lower(), "disabled": _is_disabled(sport)}


@router.post("/models/{sport}/disable")
def disable(sport: str):
    """Kill-switch: predictions for this sport return 503 until re-enabled."""
    set_enabled(sport, False)
    return {"success": True, "sport": sport.lower(), "enabled": False}


@router.post("/models/{sport}/enable")
def enable(sport: str):
    set_enabled(sport, True)
    return {"success": True, "sport": sport.lower(), "enabled": True}


@router.post("/models/{sport}/backup")
def backup(sport: str, series: str = None):
    """Snapshot current model files to `*.previous` (used before retraining)."""
    n = back_up_models(sport, series)
    return {"success": True, "backedUp": n}


@router.post("/models/{sport}/rollback")
def do_rollback(sport: str):
    """Restore the most recent `*.previous` backup(s) for this sport."""
    result = rollback(sport)
    if not result["success"] and result.get("error") and "No models directory" in result["error"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
