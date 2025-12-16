
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
        # Default datasets per sport - multiple per sport for comprehensive data
        defaults = {
            "nfl": [
                "tobycrabtree/nfl-scores-and-betting-data",
                "philiphyde1/nfl-stats-1999-2022"  # Player-level stats
            ],
            "nba": [
                "sumitrodatta/nba-aba-baa-stats",
                "eoinamoore/historical-nba-data-and-player-box-scores"  # Player box scores (daily updates)
            ]
        }
        
        updated = False
        for sport, dataset_ids in defaults.items():
            if sport not in self.config:
                self.config[sport] = []
            
            # Add any missing default datasets
            existing_ids = [ds['id'] for ds in self.config[sport]]
            for dataset_id in dataset_ids:
                if dataset_id not in existing_ids:
                    entry = {
                        "id": dataset_id,
                        "type": "kaggle",
                        "added_at": datetime.utcnow().isoformat(),
                        "last_updated": None
                    }
                    self.config[sport].append(entry)
                    updated = True
                    logger.info(f"Added default dataset {dataset_id} for {sport}")
                
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
        """Check if Kaggle dataset exists and is accessible."""
        try:
            # First try using the Kaggle Python API directly
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            
            # Parse the owner/dataset format
            parts = dataset.split('/')
            if len(parts) != 2:
                logger.error(f"Invalid dataset format: {dataset}. Expected 'owner/dataset-name'")
                return False
            
            owner, dataset_name = parts
            
            # Try to find the dataset
            datasets_found = api.dataset_list(search=dataset_name, user=owner)
            for ds in datasets_found:
                if ds.ref.lower() == dataset.lower():
                    logger.info(f"Validated Kaggle dataset: {dataset}")
                    return True
            
            # Fallback: try listing files (some datasets may not show in search)
            try:
                files = api.dataset_list_files(dataset)
                if files and len(files.files) > 0:
                    logger.info(f"Validated Kaggle dataset via file list: {dataset}")
                    return True
            except Exception:
                pass
            
            logger.warning(f"Could not validate Kaggle dataset: {dataset}")
            return False
            
        except ImportError:
            logger.warning("Kaggle API not installed, skipping validation")
            return True  # Allow if we can't validate
        except Exception as e:
            logger.error(f"Validation error for {dataset}: {e}")
            # If validation fails due to API issues, allow the add anyway
            # The download will fail later if invalid
            return True

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
