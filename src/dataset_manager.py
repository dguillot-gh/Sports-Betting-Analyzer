
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DatasetManager:
    """Manages dynamic dataset configurations."""
    
    def __init__(self, data_root: Path):
        self.config_path = data_root / 'datasets.json'
        self.data_root = data_root
        self._load_config()
        
    def _load_config(self):
        """Load datasets configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    self.config = json.load(f)
            except Exception as e:
                logger.error(f"Error loading datasets.json: {e}")
                self.config = {}
        else:
            self.config = {}
            
        # Ensure defaults are populated
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Ensure default datasets are configured if missing."""
        defaults = {
            "nfl": "tobycrabtree/nfl-scores-and-betting-data",
            "nba": "sumitrodatta/nba-aba-baa-stats"
        }
        
        updated = False
        for sport, dataset_id in defaults.items():
            if sport not in self.config:
                self.config[sport] = []
                
            # If no datasets configured for this sport, add the default
            # This preserves the "original" behavior while allowing additions or removals
            if not self.config[sport]:
                entry = {
                    "id": dataset_id,
                    "type": "kaggle",
                    "added_at": datetime.utcnow().isoformat(),
                    "last_updated": None
                }
                self.config[sport].append(entry)
                updated = True
                
        if updated:
            self._save_config()

    def _save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving datasets.json: {e}")
            
    def get_datasets(self, sport: str) -> List[Dict[str, Any]]:
        """Get list of configured datasets for a sport."""
        return self.config.get(sport, [])
    
    def add_dataset(self, sport: str, dataset_id: str, type: str = "kaggle") -> Dict[str, Any]:
        """Add a new dataset configuration."""
        if sport not in self.config:
            self.config[sport] = []
            
        # Check if already exists
        for ds in self.config[sport]:
            if ds['id'] == dataset_id:
                return {"success": False, "message": "Dataset already configured"}
                
        # Validate dataset exists (if Kaggle)
        if type == "kaggle":
             if not self._validate_kaggle_dataset(dataset_id):
                 return {"success": False, "message": "Invalid Kaggle dataset ID or not accessible"}
        
        entry = {
            "id": dataset_id,
            "type": type,
            "added_at": datetime.utcnow().isoformat(),
            "last_updated": None
        }
        
        self.config[sport].append(entry)
        self._save_config()
        return {"success": True, "entry": entry}

    def remove_dataset(self, sport: str, dataset_id: str) -> bool:
        """Remove a dataset configuration."""
        if sport not in self.config:
            return False
            
        original_len = len(self.config[sport])
        self.config[sport] = [ds for ds in self.config[sport] if ds['id'] != dataset_id]
        
        if len(self.config[sport]) < original_len:
            self._save_config()
            return True
        return False

    def update_timestamp(self, sport: str, dataset_id: str):
        """Update the last_updated timestamp for a dataset."""
        if sport in self.config:
            for ds in self.config[sport]:
                if ds['id'] == dataset_id:
                    ds['last_updated'] = datetime.utcnow().isoformat()
                    self._save_config()
                    return

    def _validate_kaggle_dataset(self, dataset: str) -> bool:
        """Check if Kaggle dataset exists using generic shell command or python API."""
        try:
            # We can reuse similar logic to KaggleDataSource
            # Assuming Kaggle API credentials are set in env
            import subprocess
            result = subprocess.run(
                ["python", "-m", "kaggle", "datasets", "status", dataset],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False

    def get_kaggle_metadata(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata from Kaggle API including last update date."""
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            
            # Parse owner/dataset format
            parts = dataset_id.split('/')
            if len(parts) != 2:
                return None
                
            owner, dataset_name = parts
            
            # Get dataset metadata
            datasets = api.dataset_list(search=dataset_name, user=owner)
            for ds in datasets:
                if ds.ref == dataset_id:
                    return {
                        "title": ds.title,
                        "last_updated": ds.lastUpdated.isoformat() if ds.lastUpdated else None,
                        "size": ds.totalBytes,
                        "downloads": ds.downloadCount,
                        "usability": ds.usabilityRating
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching Kaggle metadata for {dataset_id}: {e}")
            return None

    def check_for_updates(self, sport: str, dataset_id: str) -> Dict[str, Any]:
        """Check if a Kaggle dataset has been updated since last download."""
        # Find the dataset entry
        entry = None
        for ds in self.config.get(sport, []):
            if ds['id'] == dataset_id:
                entry = ds
                break
        
        if not entry:
            return {"has_update": False, "error": "Dataset not found in config"}
        
        # Fetch latest metadata from Kaggle
        metadata = self.get_kaggle_metadata(dataset_id)
        if not metadata:
            return {"has_update": False, "error": "Could not fetch Kaggle metadata"}
        
        kaggle_updated = metadata.get("last_updated")
        local_updated = entry.get("last_updated")
        
        if not local_updated:
            # Never downloaded, so yes there's an update
            return {
                "has_update": True,
                "kaggle_updated": kaggle_updated,
                "local_updated": None,
                "message": "Never downloaded"
            }
        
        # Compare dates
        from datetime import datetime
        kaggle_dt = datetime.fromisoformat(kaggle_updated.replace('Z', '+00:00')) if kaggle_updated else None
        local_dt = datetime.fromisoformat(local_updated) if local_updated else None
        
        if kaggle_dt and local_dt and kaggle_dt > local_dt:
            return {
                "has_update": True,
                "kaggle_updated": kaggle_updated,
                "local_updated": local_updated,
                "message": "New version available"
            }
        
        return {
            "has_update": False,
            "kaggle_updated": kaggle_updated,
            "local_updated": local_updated,
            "message": "Up to date"
        }
