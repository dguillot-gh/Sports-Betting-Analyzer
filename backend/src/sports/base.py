"""
Base sport class defining the interface for all sports implementations.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd


class BaseSport(ABC):
    """Abstract base class for sports implementations."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config['name']
        # Resolve data directory relative to the project root, not the current working directory
        # base.py is located at <project_root>/src/sports/base.py
        project_root = Path(__file__).resolve().parents[2]
        self.data_dir = project_root / 'data' / self.name

    @abstractmethod
    def load_data(self) -> pd.DataFrame:
        """Load and preprocess raw data for this sport."""
        pass

    @abstractmethod
    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return feature column groupings (categorical, boolean, numeric)."""
        pass

    @abstractmethod
    def get_target_columns(self) -> Dict[str, str]:
        """Return target column names for classification and regression."""
        pass

    @abstractmethod
    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply sport-specific preprocessing to the dataframe."""
        pass

    @abstractmethod
    def get_entities(self) -> List[str]:
        """Return a list of all available entities (drivers/teams)."""
        pass

    @abstractmethod
    def get_teams(self) -> List[str]:
        """Return a list of all available teams."""
        pass

    @abstractmethod
    def get_drivers(self, team_id: Optional[str] = None) -> List[str]:
        """Return a list of drivers, optionally filtered by team."""
        pass

    @abstractmethod
    def get_entity_stats(self, entity_id: str) -> Dict[str, Any]:
        """
        Return a dictionary of stats for a specific entity.
        Should return keys: 'stats' (dict), 'splits' (dict), 'history' (list).
        """
        pass

    def get_data_paths(self) -> Dict[str, Path]:
        """Get paths to data files based on config."""
        paths = {}
        if 'data' in self.config:
            for key, filename in self.config['data'].items():
                if key.endswith('_file'):
                    # Check root data dir first (for enhanced files)
                    p = self.data_dir / filename
                    if p.exists():
                        paths[key] = p
                    else:
                        # Fallback to raw dir (for original files)
                        paths[key] = self.data_dir / 'raw' / filename
        return paths

    def validate_data_files(self) -> None:
        """Validate that required data files exist."""
        paths = self.get_data_paths()
        missing = []
        for name, path in paths.items():
            if not path.exists():
                missing.append(str(path))

        if missing:
            raise FileNotFoundError(f"Missing data files for {self.name}: {', '.join(missing)}")
