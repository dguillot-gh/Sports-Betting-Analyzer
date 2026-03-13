"""
Version Management Endpoints
Auto-incrementing version via DB counter + git SHA dedup.
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Query
from src.version import GIT_SHA, ENVIRONMENT
from src.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Startup registration (called from app.py startup_event)
# ---------------------------------------------------------------------------

async def register_current_version() -> Dict[str, Any]:
    """
    Register the current build on startup.
    - Same git SHA as last deploy → reuse that version (restart-safe).
    - New git SHA → bump the patch number from whatever the latest version is.
    """
    try:
        async with get_connection() as conn:
            # Already registered this exact build?
            existing = await conn.fetchrow(
                "SELECT id, version FROM system_versions WHERE git_sha = $1 LIMIT 1",
                GIT_SHA
            )
            if existing:
                version = existing["version"]
                logger.info(f"Version already registered: {version}")
                return {"success": True, "version": version, "git_sha": GIT_SHA, "environment": ENVIRONMENT}

            # Get the latest version to determine major.minor prefix
            latest = await conn.fetchrow(
                "SELECT version FROM system_versions ORDER BY id DESC LIMIT 1"
            )
            major, minor, patch = 1, 0, 0
            if latest and latest["version"]:
                parts = latest["version"].split(".")
                try:
                    major = int(parts[0])
                    minor = int(parts[1]) if len(parts) > 1 else 0
                    patch = int(parts[2]) if len(parts) > 2 else 0
                except ValueError:
                    pass

            # Increment patch
            version = f"{major}.{minor}.{patch + 1}"

            await conn.execute(
                "INSERT INTO system_versions (version, git_sha, environment) VALUES ($1, $2, $3)",
                version, GIT_SHA, ENVIRONMENT
            )
            logger.info(f"Registered new version: {version}")
            return {"success": True, "version": version, "git_sha": GIT_SHA, "environment": ENVIRONMENT}

    except Exception as e:
        logger.error(f"Failed to register version: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/deployments/release")
async def create_release(major: int = Query(..., description="Major version number"),
                         minor: int = Query(default=0, description="Minor version number")):
    """
    Mark a milestone release.  e.g.  POST /deployments/release?major=2
    Next auto-deploy will be 2.0.1, then 2.0.2, ...
    """
    version = f"{major}.{minor}.0"
    try:
        async with get_connection() as conn:
            await conn.execute(
                "INSERT INTO system_versions (version, git_sha, environment) VALUES ($1, $2, $3)",
                version, GIT_SHA, ENVIRONMENT
            )
        return {"success": True, "version": version, "message": f"Release {version} created. Next deploy will be {major}.{minor}.1"}
    except Exception as e:
        logger.error(f"Failed to create release: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deployments")
async def get_deployments(limit: int = Query(default=50, le=100)):
    """Get version history (newest first)."""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                "SELECT id, version, git_sha, environment, deployed_at FROM system_versions ORDER BY id DESC LIMIT $1",
                limit
            )
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get deployments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deployments/current")
async def get_current_deployment():
    """Get the latest deployed version."""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id, version, git_sha, environment, deployed_at FROM system_versions ORDER BY id DESC LIMIT 1"
            )
            if row:
                return dict(row)
            return {"version": "1.0.0", "git_sha": GIT_SHA, "environment": ENVIRONMENT}
    except Exception as e:
        logger.error(f"Failed to get current deployment: {e}")
        return {"version": "unknown", "git_sha": GIT_SHA, "environment": ENVIRONMENT}
