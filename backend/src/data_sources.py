"""
Data source handlers for fetching data from external sources.
"""
import os
import json
import subprocess
import urllib.request
import ssl
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging
import time

logger = logging.getLogger(__name__)


class GitHubDataSource:
    """Fetches data files from GitHub repositories."""
    
    def __init__(self, repo: str, branch: str = "main"):
        self.repo = repo
        self.branch = branch
        self.base_url = f"https://raw.githubusercontent.com/{repo}/{branch}"
    
    def get_file(self, file_path: str, output_path: Path) -> bool:
        """Download a file from the repository."""
        url = f"{self.base_url}/{file_path}"
        try:
            # Create SSL context to handle HTTPS
            ctx = ssl.create_default_context()
            
            with urllib.request.urlopen(url, context=ctx) as response:
                if response.status == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(response.read())
                    logger.info(f"Downloaded {file_path} to {output_path}")
                    return True
                else:
                    logger.error(f"Failed to download {file_path}: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error downloading {file_path}: {e}")
            return False
    
    def get_repo_info(self) -> Dict[str, Any]:
        """Get repository metadata including last commit date."""
        api_url = f"https://api.github.com/repos/{self.repo}/commits/{self.branch}"
        try:
            ctx = ssl.create_default_context()
            request = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            
            with urllib.request.urlopen(request, context=ctx) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return {
                        "last_commit": data["commit"]["committer"]["date"],
                        "message": data["commit"]["message"][:100],
                        "sha": data["sha"][:7]
                    }
        except Exception as e:
            logger.error(f"Error getting repo info: {e}")
        return {}


class BaseDataUpdater:
    """Base class providing changelog functionality."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.changelog_path = data_dir / "changelog.json"

    def _append_changelog(self, topic: str, details: Dict[str, Any]):
        """Append an entry to the changelog."""
        try:
            log = []
            if self.changelog_path.exists():
                try:
                    with open(self.changelog_path, 'r') as f:
                        log = json.load(f)
                except:
                    pass
            
            entry = {
                "date": datetime.utcnow().isoformat(),
                "topic": topic,
                "details": details
            }
            log.insert(0, entry) # Prepend newest
            
            # Keep last 50
            log = log[:50]
            
            with open(self.changelog_path, 'w') as f:
                json.dump(log, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing changelog: {e}")

    def get_history(self) -> List[Dict[str, Any]]:
        """Get update history."""
        if self.changelog_path.exists():
            try:
                with open(self.changelog_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return []


class NASCARDataUpdater(BaseDataUpdater):
    """Handles NASCAR data updates from nascaR.data GitHub repo."""
    
    REPO = "kyleGrealis/nascaR.data"
    FILES = [
        "data/cup_series.parquet",
        "data/xfinity_series.parquet", 
        "data/truck_series.parquet"
    ]
    
    def __init__(self, data_dir: Path):
        super().__init__(data_dir)
        self.source = GitHubDataSource(self.REPO)
    
    def update(self) -> Dict[str, Any]:
        """Update all NASCAR data files from GitHub."""
        results = {"success": True, "files": [], "errors": []}
        
        for file_path in self.FILES:
            output_path = self.data_dir / Path(file_path).name
            success = self.source.get_file(file_path, output_path)
            
            if success:
                results["files"].append(file_path)
            else:
                results["errors"].append(file_path)
                results["success"] = False
        
        # Get repo info for metadata & changelog
        repo_info = self.source.get_repo_info()
        results["repo_info"] = repo_info
        results["updated_at"] = datetime.utcnow().isoformat()
        
        if results["success"]:
             self._append_changelog("GitHub Data Sync", {
                 "commit": repo_info.get("sha"),
                 "message": repo_info.get("message"),
                 "files": results["files"]
             })
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current data status."""
        status = {"files": {}}
        for file_path in self.FILES:
            local_path = self.data_dir / Path(file_path).name
            if local_path.exists():
                stat = local_path.stat()
                status["files"][file_path] = {
                    "exists": True,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
            else:
                status["files"][file_path] = {"exists": False}
        return status


class NFLDataUpdater(BaseDataUpdater):
    """NFL data updates - now using nflverse, not Kaggle."""
    
    def __init__(self, data_dir: Path, username=None, key=None):
        super().__init__(data_dir)
    
    def get_status(self):
        """Get file list from data directory."""
        status = {"files": []}
        for f in self.data_dir.glob("*.csv"):
            stat = f.stat()
            status["files"].append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        # Also include parquet files
        for f in self.data_dir.glob("*.parquet"):
            stat = f.stat()
            status["files"].append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return status

