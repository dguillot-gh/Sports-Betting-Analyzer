"""
Version Management — Simple, read-only, env-var driven
=======================================================
Reads version info from environment variables (set by docker-compose)
and falls back to git for local development. Never writes files.
"""

import os
import subprocess
import logging
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cmd: list[str]) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        return subprocess.check_output(
            ["git"] + cmd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _resolve_version() -> str:
    """Determine the version string once at import time."""
    # 1. Explicit env var (set in docker-compose.yml or CI)
    v = os.getenv("APP_VERSION", "").strip()
    if v and v != "unknown":
        return v

    # 2. git describe (produces e.g. v1.2.3 or v1.2.3-5-gabc1234)
    desc = _git(["describe", "--tags", "--always"])
    if desc:
        return desc

    # 3. Short SHA fallback
    sha = _git(["rev-parse", "--short", "HEAD"])
    if sha:
        return f"dev-{sha}"

    return "dev"


def _resolve_sha() -> str:
    return os.getenv("GIT_SHA", "").strip() or _git(["rev-parse", "--short", "HEAD"]) or "unknown"


def _resolve_branch() -> str:
    return os.getenv("GIT_BRANCH", "").strip() or _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"


# ---------------------------------------------------------------------------
# Module-level constants (computed once at import)
# ---------------------------------------------------------------------------
VERSION: str = _resolve_version()
GIT_SHA: str = _resolve_sha()
GIT_BRANCH: str = _resolve_branch()
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
_raw_build_time = os.getenv("BUILD_TIME", "").strip()
BUILD_TIME: str = _raw_build_time if _raw_build_time and _raw_build_time != "unknown" else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_version() -> str:
    """Return the version string (e.g. '1.0.0', 'dev-abc1234')."""
    return VERSION


def get_version_info() -> Dict:
    """Return a dict with all version metadata."""
    return {
        "version": VERSION,
        "git_sha": GIT_SHA,
        "git_branch": GIT_BRANCH,
        "environment": ENVIRONMENT,
        "build_time": BUILD_TIME,
    }
