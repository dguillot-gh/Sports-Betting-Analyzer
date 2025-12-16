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
            try:
                os.chmod(kaggle_json, 0o600)
            except:
                pass  # Windows doesn't need this
            logger.info("Created Kaggle credentials file")
    
    def download_dataset(self, dataset: str, output_dir: Path) -> bool:
        """Download a Kaggle dataset using the Kaggle Python API."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            import kaggle
            from kaggle.api.kaggle_api_extended import KaggleApi
            
            api = KaggleApi()
            api.authenticate()
            api.dataset_download_files(dataset, path=str(output_dir), unzip=True)
            
            logger.info(f"Downloaded dataset {dataset} to {output_dir}")
            return True
            
        except ImportError:
            logger.error("Kaggle package not installed. Install with: pip install kaggle")
            return False
        except Exception as e:
            logger.error(f"Error downloading dataset: {e}")
            return False

    def get_last_updated(self, dataset: str) -> Optional[str]:
        """Get the last updated timestamp for a dataset."""
        try:
            import kaggle
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            
            # Split dataset into owner/slug
            owner, slug = dataset.split('/')
            datasets = api.dataset_list(user=owner, search=slug)
            
            for d in datasets:
                if d.ref == dataset:
                    return str(d.last_updated)
            return None
        except Exception as e:
            logger.error(f"Error checking updates for {dataset}: {e}")
            return None


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


class MultiDatasetUpdater(BaseDataUpdater):
    """Handles updating multiple datasets (Kaggle or others) for a sport."""
    
    def __init__(self, data_dir: Path, datasets_config: List[Dict[str, Any]]):
        super().__init__(data_dir)
        self.datasets = datasets_config
        self.kaggle_source = KaggleDataSource()

    def update(self, specific_dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """Update configured datasets."""
        results = {"success": True, "updated": [], "errors": []}
        
        targets = self.datasets
        if specific_dataset_id:
            targets = [d for d in self.datasets if d['id'] == specific_dataset_id]
        
        if not targets and specific_dataset_id:
            return {"success": False, "message": "Dataset not found in configuration"}

        for ds in targets:
            dataset_id = ds['id']
            # Create subfolder for cleanliness if updating multiple datasets, 
            # OR dump to root if it's the primary one. 
            # For backward compatibility, if it's the "legacy" single dataset, use root.
            # But "legacy" usually meant 1 dataset per sport.
            # We'll assume root for now unless we want to separate them. 
            # Wait, if we have multiple datasets, they might overwrite each other's files.
            # Let's use subdirectories for secondary datasets, or root for all?
            # User wants to manage them individually.
            # Let's put each in a folder named after the dataset slug to avoid conflicts.
            # BUT, existing code expects files in root of data/nba.
            # Compromise: Extract to root, user must ensure no filename clashes.
            # OR: specific logic.
            # Let's stick to root for now as that fits current pattern.
            
            if ds.get('type') == 'kaggle':
                logger.info(f"Updating {dataset_id}...")
                
                # Capture state before
                files_before = set(self.data_dir.glob("*"))
                
                success = self.kaggle_source.download_dataset(dataset_id, self.data_dir)
                
                if success:
                    # Capture state after
                    files_after = set(self.data_dir.glob("*"))
                    new_files = [f.name for f in files_after - files_before]
                    
                    results["updated"].append(dataset_id)
                    
                    # Log to changelog
                    self._append_changelog(f"Updated {dataset_id}", {
                        "files_added": new_files,
                        "dataset": dataset_id
                    })
                else:
                    results["errors"].append(f"Failed to download {dataset_id}")
                    results["success"] = False

        return results

    def check_updates(self) -> Dict[str, Any]:
        """Check for updates for all configured datasets."""
        updates = {}
        for ds in self.datasets:
            if ds.get('type') == 'kaggle':
                remote_time = self.kaggle_source.get_last_updated(ds['id'])
                updates[ds['id']] = {
                    "last_updated_remote": remote_time,
                    "update_available": True # Simple assumption: always available if we can see it, 
                    # or compare with local stored timestamp if we had it.
                    # We will rely on UI to compare dates or just show the date.
                }
        return updates


class NASCARDataUpdater(BaseDataUpdater):
    """Handles NASCAR data updates from nascaR.data GitHub repo."""
    
    REPO = "kyleGrealis/nascaR.data"
    FILES = [
        "data/cup_series.rda",
        "data/xfinity_series.rda", 
        "data/truck_series.rda"
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

# Create legacy alias for backward compatibility until refactored
class NFLDataUpdater(MultiDatasetUpdater):
    """Legacy wrapper for NFL data updates."""
    def __init__(self, data_dir: Path, username=None, key=None):
        # Config mimicking the old hardcoded style
        config = [{"id": "tobycrabtree/nfl-scores-and-betting-data", "type": "kaggle"}]
        super().__init__(data_dir, config)
    
    def get_status(self):
        # Simple file list wrapper
        status = {"files": []}
        for f in self.data_dir.glob("*.csv"):
            stat = f.stat()
            status["files"].append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return status
