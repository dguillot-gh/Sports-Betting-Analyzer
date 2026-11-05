"""
Model Governance — operator controls over deployed prediction models.

Provides the backend for:
- **Kill-switch**: temporarily disable predictions for a sport without
  touching model files (state persisted in configs/model_overrides.json).
- **Auto-backup**: before retraining overwrites a model file, the previous
  file is preserved as `*.previous` so operators can roll back.
- **Rollback**: restore the most recent backup of a sport's models.
- **Inventory**: list deployed models (path, mtime, size, backup, enabled).

Everything is filesystem-based: no DB required, safe in CI and containers.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = REPO_ROOT / "configs" / "model_overrides.json"
MODELS_DIR = REPO_ROOT / "models"


def load_overrides() -> dict:
    try:
        if OVERRIDES_PATH.exists():
            return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_overrides(data: dict) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_disabled(sport: str) -> bool:
    return bool(load_overrides().get(str(sport).lower(), {}).get("enabled") is False)


def set_enabled(sport: str, enabled: bool) -> None:
    overrides = load_overrides()
    key = str(sport).lower()
    entry = overrides.get(key) or {}
    entry["enabled"] = bool(enabled)
    entry["changed_at"] = datetime.utcnow().isoformat() + "Z"
    overrides[key] = entry
    save_overrides(overrides)

    # Drop any cached model so the next request reflects the new state
    try:
        from api.app import MODEL_CACHE, CACHE_LOCK  # type: ignore
        with CACHE_LOCK:
            for k in [k for k in MODEL_CACHE if k[0] == key]:
                del MODEL_CACHE[k]
    except Exception:
        pass


def _iter_model_files(sport: str):
    root = (MODELS_DIR / str(sport).lower())
    if not root.exists():
        return
    for f in sorted(root.rglob("*.joblib")):
        if f.name.endswith(".previous"):
            continue
        yield f


def list_models() -> dict:
    """Inventory of deployed models per sport."""
    out: dict = {}
    if not MODELS_DIR.exists():
        return out
    for sport_dir in sorted(p for p in MODELS_DIR.iterdir() if p.is_dir()):
        models = []
        for f in _iter_model_files(sport_dir.name):
            mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            backup = f.with_suffix(f.suffix + ".previous")
            models.append({
                "path": str(f.relative_to(MODELS_DIR)),
                "sizeBytes": f.stat().st_size,
                "modifiedAt": mtime,
                "hasBackup": backup.exists(),
            })
        if not models and not sport_dir.name in load_overrides():
            # still include sports that exist but have no .joblib (e.g. parquet-only)
            pass
        overrides = load_overrides().get(sport_dir.name, {})
        out[sport_dir.name] = {
            "enabled": overrides.get("enabled") is not False,
            "modelCount": len(models),
            "models": models,
        }
    return out


def back_up_models(sport: str, series_label: Optional[str] = None) -> int:
    """Copy each existing model file for the sport to `*.previous` in place."""
    count = 0
    base = MODELS_DIR / str(sport).lower()
    if series_label:
        candidates = [base / series_label]
    else:
        candidates = [p for p in base.rglob("*") if p.is_dir()] or [base]
    for c in candidates:
        if not c.is_dir():
            continue
        for f in c.glob("*.joblib"):
            if f.name.endswith(".previous"):
                continue
            backup = f.with_suffix(f.suffix + ".previous")
            try:
                shutil.copy2(f, backup)
                count += 1
            except Exception:
                pass
    return count


def rollback(sport: str) -> dict:
    """
    Restore `*.previous` backups over the current model files.
    The currently-served file is kept as `*.rollback`.
    """
    key = str(sport).lower()
    base = MODELS_DIR / key
    restored = []
    if not base.exists():
        return {"success": False, "restored": [], "error": f"No models directory for '{key}'"}
    for f in sorted(base.rglob("*.joblib")):
        if f.name.endswith(".previous"):
            continue
        backup = f.with_suffix(f.suffix + ".previous")
        if not backup.exists():
            continue
        # keep current file (in case this was a mistake)
        current_keep = f.with_suffix(f.suffix + ".rollback")
        shutil.copy2(f, current_keep)
        shutil.copy2(backup, f)
        try:
            os_bak = f.with_suffix(f.suffix + ".previous")
            # remove the backup so repeated rollbacks don't loop
            if os_bak.exists():
                os_bak.unlink()
        except Exception:
            pass
        restored.append(str(f.relative_to(MODELS_DIR)))
    if restored:
        # clear cached copies
        try:
            from api.app import MODEL_CACHE, CACHE_LOCK  # type: ignore
            with CACHE_LOCK:
                for k in [k for k in MODEL_CACHE if k[0] == key]:
                    del MODEL_CACHE[k]
        except Exception:
            pass
    return {"success": len(restored) > 0, "restored": restored,
            "error": None if restored else "No .previous backups found for sport"}
