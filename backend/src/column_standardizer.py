"""
Column Standardizer Module
Automatically maps and standardizes column names from diverse data sources.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ScanReport:
    """Report from scanning a DataFrame's columns."""
    sport: str
    total_columns: int = 0
    mapped: Dict[str, str] = field(default_factory=dict)  # original -> standard
    unmapped: List[str] = field(default_factory=list)
    suggestions: Dict[str, str] = field(default_factory=dict)  # unmapped -> closest match
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sport": self.sport,
            "total_columns": self.total_columns,
            "mapped_count": len(self.mapped),
            "unmapped_count": len(self.unmapped),
            "mapped": self.mapped,
            "unmapped": self.unmapped,
            "suggestions": self.suggestions
        }


class ColumnStandardizer:
    """Handles column name standardization across datasets."""
    
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            # Default to configs/column_aliases.yaml relative to this file
            config_path = Path(__file__).parent.parent / "configs" / "column_aliases.yaml"
        
        self.config_path = config_path
        self.aliases = self._load_config()
        
    def _load_config(self) -> Dict[str, Dict[str, List[str]]]:
        """Load column aliases from YAML config."""
        if not self.config_path.exists():
            logger.warning(f"Column aliases config not found at {self.config_path}")
            return {}
        
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded column aliases from {self.config_path}")
            return config or {}
        except Exception as e:
            logger.error(f"Error loading column aliases: {e}")
            return {}
    
    def reload_config(self):
        """Reload config from disk."""
        self.aliases = self._load_config()
    
    def _get_alias_map(self, sport: str) -> Dict[str, str]:
        """Build reverse lookup: alias -> standard_name for a sport."""
        alias_map = {}
        
        # Sport-specific aliases
        sport_config = self.aliases.get(sport.lower(), {})
        for standard_name, aliases in sport_config.items():
            if isinstance(aliases, list):
                for alias in aliases:
                    alias_map[alias.lower()] = standard_name
                # Also map the standard name to itself
                alias_map[standard_name.lower()] = standard_name
        
        # Common aliases
        common_config = self.aliases.get('common', {})
        for standard_name, aliases in common_config.items():
            if isinstance(aliases, list):
                for alias in aliases:
                    # Don't override sport-specific mappings
                    if alias.lower() not in alias_map:
                        alias_map[alias.lower()] = standard_name
                if standard_name.lower() not in alias_map:
                    alias_map[standard_name.lower()] = standard_name
        
        return alias_map
    
    def scan(self, df: pd.DataFrame, sport: str) -> ScanReport:
        """
        Scan DataFrame columns and report which can be mapped.
        Does NOT modify the DataFrame.
        """
        report = ScanReport(sport=sport, total_columns=len(df.columns))
        alias_map = self._get_alias_map(sport)
        
        for col in df.columns:
            col_lower = col.lower().strip()
            
            if col_lower in alias_map:
                standard_name = alias_map[col_lower]
                if col != standard_name:
                    report.mapped[col] = standard_name
                # If col == standard_name, it's already standard, no action needed
            else:
                report.unmapped.append(col)
                # Try to find a close match
                suggestion = self._find_closest_match(col_lower, alias_map)
                if suggestion:
                    report.suggestions[col] = suggestion
        
        logger.info(f"Scan report for {sport}: {len(report.mapped)} mapped, {len(report.unmapped)} unmapped")
        return report
    
    def _find_closest_match(self, col: str, alias_map: Dict[str, str]) -> Optional[str]:
        """Find the closest matching standard column name."""
        # Simple substring matching
        for alias, standard in alias_map.items():
            if alias in col or col in alias:
                return standard
        
        # Check for common patterns
        col_clean = col.replace('_', '').replace('-', '').replace(' ', '')
        for alias, standard in alias_map.items():
            alias_clean = alias.replace('_', '').replace('-', '').replace(' ', '')
            if alias_clean == col_clean:
                return standard
        
        return None
    
    def standardize(self, df: pd.DataFrame, sport: str, inplace: bool = False) -> Tuple[pd.DataFrame, ScanReport]:
        """
        Standardize column names in DataFrame.
        
        Args:
            df: DataFrame to standardize
            sport: Sport type for alias lookup
            inplace: If True, modify df in place. Otherwise return a copy.
            
        Returns:
            Tuple of (standardized DataFrame, scan report)
        """
        report = self.scan(df, sport)
        
        if not inplace:
            df = df.copy()
        
        # Rename columns
        rename_map = report.mapped
        if rename_map:
            df.rename(columns=rename_map, inplace=True)
            logger.info(f"Standardized {len(rename_map)} columns for {sport}")
        
        return df, report
    
    def get_expected_columns(self, sport: str) -> List[str]:
        """Get list of expected standard column names for a sport."""
        sport_config = self.aliases.get(sport.lower(), {})
        return list(sport_config.keys())
    
    def add_alias(self, sport: str, standard_name: str, new_alias: str) -> bool:
        """Add a new alias mapping (persisted to config)."""
        try:
            if sport not in self.aliases:
                self.aliases[sport] = {}
            
            if standard_name not in self.aliases[sport]:
                self.aliases[sport][standard_name] = []
            
            if new_alias not in self.aliases[sport][standard_name]:
                self.aliases[sport][standard_name].append(new_alias)
                self._save_config()
                return True
            return False
        except Exception as e:
            logger.error(f"Error adding alias: {e}")
            return False
    
    def _save_config(self):
        """Save current aliases to config file."""
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.aliases, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Saved column aliases to {self.config_path}")
        except Exception as e:
            logger.error(f"Error saving column aliases: {e}")


# Global instance for easy import
_standardizer: Optional[ColumnStandardizer] = None

def get_standardizer() -> ColumnStandardizer:
    """Get or create global ColumnStandardizer instance."""
    global _standardizer
    if _standardizer is None:
        _standardizer = ColumnStandardizer()
    return _standardizer
