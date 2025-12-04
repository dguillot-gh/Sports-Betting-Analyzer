import yaml
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from fastapi import HTTPException

from sports import NASCARSport, NFLSport, NBASport, BaseSport

# Define the root for configs relative to this file
# src/sport_factory.py -> parent is src -> parent is root
REPO_ROOT = Path(__file__).resolve().parents[1]
CFG_DIR = REPO_ROOT / 'configs'

class SportFactory:
    """
    Factory to create and configure sport instances.
    """
    
    @staticmethod
    def load_yaml(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return yaml.safe_load(open(path, 'r', encoding='utf-8'))

    @staticmethod
    def get_sport(sport_name: str, series: Optional[str] = None) -> Tuple[BaseSport, str]:
        """
        Get a configured sport instance and its model label.
        
        Args:
            sport_name: 'nascar', 'nfl', etc.
            series: Optional series/league specifier (e.g. 'cup' for NASCAR)
            
        Returns:
            (sport_instance, model_label)
        """
        sport_name = sport_name.lower()
        
        if sport_name == 'nfl':
            return SportFactory._create_nfl()
        elif sport_name == 'nascar':
            return SportFactory._create_nascar(series)
        elif sport_name == 'nba':
            return SportFactory._create_nba()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown sport '{sport_name}'")

    @staticmethod
    def _create_nfl() -> Tuple[BaseSport, str]:
        cfg = SportFactory.load_yaml(CFG_DIR / 'nfl_config.yaml')
        return NFLSport(cfg), 'default'

    @staticmethod
    def _create_nascar(series: Optional[str]) -> Tuple[BaseSport, str]:
        cfg = SportFactory.load_yaml(CFG_DIR / 'nascar_config.yaml')
        
        # Map a series keyword to a NASCAR config override
        series_to_rda = {
            'cup': 'cup_enhanced.csv',
            'xfinity': 'xfinity_enhanced.csv',
            'truck': 'truck_enhanced.csv',
        }

        label = 'csv'  # default label
        if series:
            s = series.lower().strip()
            if s == 'all':
                # Force the loader to scan all RDA files by clearing data block
                cfg['data'] = {}
                label = 'all'
            elif s in series_to_rda:
                # Point directly to a specific RDA file
                cfg.setdefault('data', {})
                cfg['data']['results_file'] = series_to_rda[s]
                label = s
            else:
                raise HTTPException(status_code=400, detail=f"Unknown series '{series}'. Use cup|xfinity|truck|all|csv.")
        
        # Inject series into config for the sport instance to use
        if series:
            cfg['series'] = series.lower()
            
        return NASCARSport(cfg), label

    @staticmethod
    def _create_nba() -> Tuple[BaseSport, str]:
        cfg = SportFactory.load_yaml(CFG_DIR / 'nba_config.yaml')
        return NBASport(cfg), 'default'
