"""
Simple Version Management for Sports Betting Analyzer
Just returns environment variables or a simple fallback
"""

import os
from datetime import datetime

def get_version():
    """Get current version - simple approach"""
    return os.getenv("APP_VERSION", "1.0.0")

def get_version_info():
    """Get version info - simple approach"""
    return {
        "version": get_version(),
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "git_branch": os.getenv("GIT_BRANCH", "unknown"),
        "build_time": os.getenv("BUILD_TIME", datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")),
        "environment": os.getenv("ENVIRONMENT", "development")
    }
