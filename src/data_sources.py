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


class KaggleDataSource:
    """Fetches datasets from Kaggle using the Kaggle API."""
    
    # Default credentials (fallback)
    DEFAULT_USERNAME = "danman2901"
    DEFAULT_KEY = "KGAT_e42c6b3e06534822adac671631ede3f7"
    
    def __init__(self, username: str = None, key: str = None):
        self.username = username or os.environ.get("KAGGLE_USERNAME") or self.DEFAULT_USERNAME
        self.key = key or os.environ.get("KAGGLE_KEY") or self.DEFAULT_KEY
        self._setup_credentials()
    
    def _setup_credentials(self):
        """Set up Kaggle credentials file if not present."""
        kaggle_dir = Path.home() / ".kaggle"
        kaggle_json = kaggle_dir / "kaggle.json"
        
        if self.username and self.key and not kaggle_json.exists():
            kaggle_dir.mkdir(exist_ok=True)
            kaggle_json.write_text(json.dumps({
                "username": self.username,
                "key": self.key
            }))
            # Set permissions (important on Unix systems)
            try:
                os.chmod(kaggle_json, 0o600)
            except:
                pass  # Windows doesn't need this
            logger.info("Created Kaggle credentials file")
    
    def download_dataset(self, dataset: str, output_dir: Path) -> bool:
        """
        Download a Kaggle dataset using the Kaggle Python API.
        
        Args:
            dataset: Dataset identifier (e.g., 'tobycrabtree/nfl-scores-and-betting-data')
            output_dir: Directory to extract files to
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Use Kaggle Python API directly instead of CLI
            import kaggle
            from kaggle.api.kaggle_api_extended import KaggleApi
            
            api = KaggleApi()
            api.authenticate()
            
            # Download and unzip the dataset
            api.dataset_download_files(dataset, path=str(output_dir), unzip=True)
            
            logger.info(f"Downloaded dataset {dataset} to {output_dir}")
            return True
            
        except ImportError:
            logger.error("Kaggle package not installed. Install with: pip install kaggle")
            return False
        except Exception as e:
            logger.error(f"Error downloading dataset: {e}")
            return False
    
    def get_dataset_info(self, dataset: str) -> Dict[str, Any]:
        """Get dataset metadata from Kaggle."""
        try:
            result = subprocess.run(
                ["python", "-m", "kaggle", "datasets", "metadata", "-d", dataset],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {"status": "available", "output": result.stdout}
        except Exception as e:
            logger.error(f"Error getting dataset info: {e}")
        
        return {"status": "unknown"}


class NASCARDataUpdater:
    """Handles NASCAR data updates from nascaR.data GitHub repo."""
    
    REPO = "kyleGrealis/nascaR.data"
    FILES = [
        "data/cup_series.rda",
        "data/xfinity_series.rda", 
        "data/truck_series.rda"
    ]
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
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
        
        # Get repo info for metadata
        repo_info = self.source.get_repo_info()
        results["repo_info"] = repo_info
        results["updated_at"] = datetime.utcnow().isoformat()
        
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


class NFLDataUpdater:
    """Handles NFL data updates from Kaggle."""
    
    DATASET = "tobycrabtree/nfl-scores-and-betting-data"
    
    def __init__(self, data_dir: Path, kaggle_username: str = None, kaggle_key: str = None):
        self.data_dir = data_dir
        self.source = KaggleDataSource(kaggle_username, kaggle_key)
    
    def update(self) -> Dict[str, Any]:
        """Update NFL data from Kaggle."""
        results = {"success": False, "files": [], "errors": []}
        
        success = self.source.download_dataset(self.DATASET, self.data_dir)
        
        if success:
            results["success"] = True
            # List downloaded files
            for f in self.data_dir.glob("*.csv"):
                results["files"].append(f.name)
            results["updated_at"] = datetime.utcnow().isoformat()
        else:
            results["errors"].append("Failed to download dataset")
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current data status."""
        status = {"files": []}
        
        for f in self.data_dir.glob("*.csv"):
            stat = f.stat()
            status["files"].append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return status
