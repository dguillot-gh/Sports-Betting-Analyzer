"""
NHL sport implementation.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
from .base import BaseSport

logger = logging.getLogger(__name__)

class NHLSport(BaseSport):
    """NHL-specific sport implementation accessing PostgreSQL results."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.df = None

    def load_data(self) -> pd.DataFrame:
        """
        Load NHL data from the database.
        In this implementation, we pull from the 'results' table where series='nhl'.
        """
        if self.df is not None:
            return self.df

        # This would typically be called via a database connection passed to the sport
        # For now, we'll assume a pattern similar to others if available, 
        # but since we're in a factory, we might need to handle the connection.
        # However, the BaseSport pattern usually expects load_data to return a DataFrame.
        
        logger.warning("NHLSport.load_data() called without active DB connection. "
                       "Use specialized methods or ensure DB is synced.")
        return pd.DataFrame()

    async def load_from_db(self, conn) -> pd.DataFrame:
        """Asynchronously load data from PostgreSQL."""
        rows = await conn.fetch("""
            SELECT season, metadata 
            FROM results 
            WHERE series = 'nhl'
            ORDER BY season DESC
        """)
        
        data = []
        for row in rows:
            meta = json.loads(row['metadata'])
            meta['season'] = row['season']
            data.append(meta)
            
        self.df = pd.DataFrame(data)
        return self.df

    def get_feature_columns(self) -> Dict[str, List[str]]:
        return self.config.get('features', {
            'categorical': ['team', 'location'],
            'boolean': [],
            'numeric': ['season', 'xGoalsFor', 'goals']
        })

    def get_target_columns(self) -> Dict[str, str]:
        return self.config.get('targets', {
            'classification': 'win',
            'regression': 'goals'
        })

    def get_entities(self) -> List[str]:
        # This usually pulls from the entities table
        return []

    def get_teams(self) -> List[str]:
        return ["Anaheim Ducks", "Arizona Coyotes", "Boston Bruins", "Buffalo Sabres", "Calgary Flames", 
                "Carolina Hurricanes", "Chicago Blackhawks", "Colorado Avalanche", "Columbus Blue Jackets", 
                "Dallas Stars", "Detroit Red Wings", "Edmonton Oilers", "Florida Panthers", "Los Angeles Kings", 
                "Minnesota Wild", "Montreal Canadiens", "Nashville Predators", "New Jersey Devils", 
                "New York Islanders", "New York Rangers", "Ottawa Senators", "Philadelphia Flyers", 
                "Pittsburgh Penguins", "San Jose Sharks", "Seattle Kraken", "St. Louis Blues", 
                "Tampa Bay Lightning", "Toronto Maple Leafs", "Vancouver Canucks", "Vegas Golden Knights", 
                "Washington Capitals", "Winnipeg Jets"]

    def get_entity_stats(self, entity_id: str, year: Optional[int] = None) -> Dict[str, Any]:
        return {"stats": {}, "history": [], "years": []}
