"""
Version Management System for Sports Betting Analyzer
Automatically generates semantic versions based on git commits and branch strategy
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Dict, Optional
import re


class VersionManager:
    """Manages semantic versioning based on git commit history and branch strategy"""
    
    def __init__(self):
        self.repo_root = Path(__file__).parent.parent.parent
        self.version_file = self.repo_root / ".version.json"
        
    def get_git_info(self) -> Dict[str, str]:
        """Get current git information"""
        # 1. ALWAYS check environment variables first (handles Docker/CI/CD)
        if os.getenv("GIT_SHA") and os.getenv("GIT_SHA") != "unknown":
            return {
                "branch": os.getenv("GIT_BRANCH", "unknown"),
                "sha": os.getenv("GIT_SHA", "unknown"),
                "commit_count": 0,  
                "commit_message": "Container build"
            }
        
        # 2. Try git commands (handles local development on host)
        try:
            # Check if git exists
            subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            # Get current branch
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_root,
                text=True
            ).strip()
            
            # Get current commit SHA
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_root,
                text=True
            ).strip()
            
            # Get commit count
            commit_count = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=self.repo_root,
                text=True
            ).strip()
            
            # Get last commit message
            commit_msg = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%B"],
                cwd=self.repo_root,
                text=True
            ).strip()
            
            return {
                "branch": branch,
                "sha": sha,
                "commit_count": int(commit_count),
                "commit_message": commit_msg
            }
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 3. Fallback for non-git environments (like inside containers without env vars)
            return {
                "branch": "unknown",
                "sha": "unknown",
                "commit_count": 0,
                "commit_message": "No git info"
            }
    
    def load_version_history(self) -> Dict:
        """Load version history from file"""
        if self.version_file.exists():
            try:
                with open(self.version_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"versions": [], "current_major": 1, "current_minor": 0, "current_patch": 0}
    
    def save_version_history(self, history: Dict):
        """Save version history to file"""
        with open(self.version_file, 'w') as f:
            json.dump(history, f, indent=2)
    
    def calculate_version(self) -> str:
        """Calculate current version based on git history and branch"""
        # Check if we're in a container (use environment variables)
        if os.getenv("APP_VERSION"):
            # Use the version that was set during build
            return os.getenv("APP_VERSION")
        
        git_info = self.get_git_info()
        history = self.load_version_history()
        
        branch = git_info["branch"]
        commit_count = git_info["commit_count"]
        
        # Check if this is a master/main branch merge
        if branch in ["master", "main"]:
            # Master merge = major version increment
            history["current_major"] += 1
            history["current_minor"] = 0
            history["current_patch"] = 0
        else:
            # Dev branch = patch version increment
            # Only increment if this is a new commit
            last_commit_count = history.get("last_commit_count", 0)
            if commit_count > last_commit_count:
                history["current_patch"] += 1
        
        # Update last commit count
        history["last_commit_count"] = commit_count
        
        # Generate version string
        version = f"{history['current_major']}.{history['current_minor']}.{history['current_patch']}"
        
        # Save version history
        self.save_version_history(history)
        
        return version
    
    def get_version_info(self) -> Dict:
        """Get comprehensive version information"""
        version = self.calculate_version()
        git_info = self.get_git_info()
        
        return {
            "version": version,
            "git_sha": git_info["sha"],
            "git_branch": git_info["branch"],
            "commit_count": git_info["commit_count"],
            "commit_message": git_info["commit_message"],
            "build_time": os.getenv("BUILD_TIME", subprocess.check_output(
                ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                text=True
            ).strip() if os.name != 'nt' else "2026-03-09T19:00:00Z"),
            "environment": os.getenv("ENVIRONMENT", "development"),
            "app_version": os.getenv("APP_VERSION", version)
        }


# Global version manager instance
_version_manager = VersionManager()

def get_version() -> str:
    """Get current version string"""
    return _version_manager.calculate_version()

def get_version_info() -> Dict:
    """Get comprehensive version information"""
    return _version_manager.get_version_info()
