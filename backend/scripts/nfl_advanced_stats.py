"""
NFL Advanced Stats Aggregation Module
Extracts and aggregates comprehensive statistics from nflverse data for predictions.

Features:
- Team-level EPA metrics
- Player-level aggregates (snap-weighted)
- Next Gen Stats summaries
- Advanced PFR stats
"""

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# Data directories
NFLVERSE_DIR = Path("/app/data/nflverse")
NGS_DIR = NFLVERSE_DIR / "nextgen_stats"
ADVANCED_DIR = NFLVERSE_DIR / "advanced_stats"


class NFLAdvancedStats:
    """
    Aggregates NFL advanced statistics from nflverse data.
    Provides team-level and player-level feature extraction for ML models.
    """
    
    def __init__(self):
        self.cache = {}
        self._ngs_passing = None
        self._ngs_rushing = None
        self._ngs_receiving = None
        self._snap_counts = None
        self._combine = None
    
    def load_nextgen_stats(self) -> bool:
        """Load all Next Gen Stats data into memory."""
        try:
            import pyarrow.parquet as pq
            
            # Passing
            passing_path = NGS_DIR / "ngs_passing.parquet"
            if passing_path.exists():
                self._ngs_passing = pq.read_table(passing_path).to_pandas()
                logger.info(f"Loaded NGS passing: {len(self._ngs_passing):,} rows")
            
            # Rushing
            rushing_path = NGS_DIR / "ngs_rushing.parquet"
            if rushing_path.exists():
                self._ngs_rushing = pq.read_table(rushing_path).to_pandas()
                logger.info(f"Loaded NGS rushing: {len(self._ngs_rushing):,} rows")
            
            # Receiving
            receiving_path = NGS_DIR / "ngs_receiving.parquet"
            if receiving_path.exists():
                self._ngs_receiving = pq.read_table(receiving_path).to_pandas()
                logger.info(f"Loaded NGS receiving: {len(self._ngs_receiving):,} rows")
            
            return True
        except Exception as e:
            logger.error(f"Error loading Next Gen Stats: {e}")
            return False
    
    def load_snap_counts(self) -> bool:
        """Load snap count data."""
        try:
            import pyarrow.parquet as pq
            snap_path = NFLVERSE_DIR / "snap_counts.parquet"
            if snap_path.exists():
                self._snap_counts = pq.read_table(snap_path).to_pandas()
                logger.info(f"Loaded snap counts: {len(self._snap_counts):,} rows")
                return True
        except Exception as e:
            logger.error(f"Error loading snap counts: {e}")
        return False
    
    def get_team_ngs_passing_summary(self, team: str, season: int) -> Dict[str, float]:
        """
        Get team-level Next Gen passing statistics.
        Aggregates QB stats for the team's starters.
        """
        if self._ngs_passing is None:
            self.load_nextgen_stats()
        
        if self._ngs_passing is None:
            return {}
        
        # Filter to team and season
        df = self._ngs_passing[
            (self._ngs_passing['season'] == season) & 
            (self._ngs_passing['team_abbr'] == team)
        ]
        
        if df.empty:
            return {}
        
        # Aggregate (weighted average by attempts if available)
        summary = {}
        
        numeric_cols = [
            'avg_time_to_throw', 'avg_completed_air_yards', 
            'avg_intended_air_yards', 'avg_air_distance',
            'aggressiveness', 'max_completed_air_distance',
            'avg_air_yards_differential', 'completion_percentage',
            'attempts', 'completions', 'passing_yards', 'passing_tds'
        ]
        
        for col in numeric_cols:
            if col in df.columns:
                summary[col] = df[col].mean()
        
        return summary
    
    def get_team_ngs_rushing_summary(self, team: str, season: int) -> Dict[str, float]:
        """Get team-level Next Gen rushing statistics."""
        if self._ngs_rushing is None:
            self.load_nextgen_stats()
        
        if self._ngs_rushing is None:
            return {}
        
        df = self._ngs_rushing[
            (self._ngs_rushing['season'] == season) & 
            (self._ngs_rushing['team_abbr'] == team)
        ]
        
        if df.empty:
            return {}
        
        summary = {}
        numeric_cols = [
            'efficiency', 'avg_rush_yards', 'rush_attempts',
            'rush_yards', 'rush_touchdowns', 'avg_time_to_los',
            'rush_yards_over_expected', 'rush_yards_over_expected_per_att'
        ]
        
        for col in numeric_cols:
            if col in df.columns:
                summary[col] = df[col].mean()
        
        return summary
    
    def get_team_snap_distribution(self, team: str, season: int, week: int = None) -> Dict[str, Any]:
        """
        Get team snap count distribution.
        Shows workload distribution across offensive positions.
        """
        if self._snap_counts is None:
            self.load_snap_counts()
        
        if self._snap_counts is None:
            return {}
        
        df = self._snap_counts[
            (self._snap_counts['season'] == season) & 
            (self._snap_counts['team'] == team)
        ]
        
        if week:
            df = df[df['week'] == week]
        
        if df.empty:
            return {}
        
        # Aggregate by position
        position_snaps = df.groupby('position').agg({
            'offense_snaps': 'sum',
            'defense_snaps': 'sum',
            'st_snaps': 'sum'
        }).to_dict('index')
        
        return {
            'position_breakdown': position_snaps,
            'total_offense_snaps': df['offense_snaps'].sum(),
            'total_defense_snaps': df['defense_snaps'].sum(),
            'total_st_snaps': df['st_snaps'].sum()
        }
    
    def get_qb_features(self, player_name: str, season: int) -> Dict[str, float]:
        """Extract QB-specific features for a player."""
        if self._ngs_passing is None:
            self.load_nextgen_stats()
        
        if self._ngs_passing is None:
            return {}
        
        # Find player
        df = self._ngs_passing[
            (self._ngs_passing['season'] == season) & 
            (self._ngs_passing['player_display_name'].str.contains(player_name, case=False, na=False))
        ]
        
        if df.empty:
            return {}
        
        # Get latest/best stats
        features = {}
        important_cols = [
            'avg_time_to_throw', 'avg_completed_air_yards',
            'avg_intended_air_yards', 'aggressiveness',
            'completion_percentage', 'passer_rating',
            'expected_completion_percentage', 'completion_percentage_above_expectation'
        ]
        
        for col in important_cols:
            if col in df.columns:
                features[f'qb_{col}'] = df[col].mean()
        
        return features
    
    def get_rb_features(self, player_name: str, season: int) -> Dict[str, float]:
        """Extract RB-specific features for a player."""
        if self._ngs_rushing is None:
            self.load_nextgen_stats()
        
        if self._ngs_rushing is None:
            return {}
        
        df = self._ngs_rushing[
            (self._ngs_rushing['season'] == season) & 
            (self._ngs_rushing['player_display_name'].str.contains(player_name, case=False, na=False))
        ]
        
        if df.empty:
            return {}
        
        features = {}
        important_cols = [
            'efficiency', 'rush_yards_over_expected',
            'rush_yards_over_expected_per_att', 'avg_rush_yards',
            'rush_attempts', 'rush_yards', 'rush_touchdowns'
        ]
        
        for col in important_cols:
            if col in df.columns:
                features[f'rb_{col}'] = df[col].mean()
        
        return features
    
    def get_wr_features(self, player_name: str, season: int) -> Dict[str, float]:
        """Extract WR/TE-specific features for a player."""
        if self._ngs_receiving is None:
            self.load_nextgen_stats()
        
        if self._ngs_receiving is None:
            return {}
        
        df = self._ngs_receiving[
            (self._ngs_receiving['season'] == season) & 
            (self._ngs_receiving['player_display_name'].str.contains(player_name, case=False, na=False))
        ]
        
        if df.empty:
            return {}
        
        features = {}
        important_cols = [
            'avg_cushion', 'avg_separation', 'avg_intended_air_yards',
            'percent_share_of_intended_air_yards', 'receptions',
            'targets', 'receiving_yards', 'receiving_touchdowns',
            'avg_yac', 'avg_yac_above_expectation'
        ]
        
        for col in important_cols:
            if col in df.columns:
                features[f'wr_{col}'] = df[col].mean()
        
        return features
    
    def get_team_comprehensive_features(self, team: str, season: int) -> Dict[str, float]:
        """
        Get comprehensive team-level features for ML model.
        Combines all advanced stats into a feature vector.
        """
        features = {}
        
        # Next Gen Passing features
        ngs_passing = self.get_team_ngs_passing_summary(team, season)
        for k, v in ngs_passing.items():
            features[f'ngs_pass_{k}'] = v
        
        # Next Gen Rushing features
        ngs_rushing = self.get_team_ngs_rushing_summary(team, season)
        for k, v in ngs_rushing.items():
            features[f'ngs_rush_{k}'] = v
        
        # Snap distribution
        snaps = self.get_team_snap_distribution(team, season)
        if 'total_offense_snaps' in snaps:
            features['total_offense_snaps'] = snaps['total_offense_snaps']
            features['total_defense_snaps'] = snaps['total_defense_snaps']
        
        return features


# Module-level functions for easy access
_stats_instance = None

def get_stats_instance() -> NFLAdvancedStats:
    """Get singleton instance of NFLAdvancedStats."""
    global _stats_instance
    if _stats_instance is None:
        _stats_instance = NFLAdvancedStats()
    return _stats_instance


async def get_team_features(team: str, season: int = None) -> Dict[str, float]:
    """Get comprehensive team features for prediction."""
    if season is None:
        season = datetime.now().year
    
    stats = get_stats_instance()
    return stats.get_team_comprehensive_features(team, season)


async def get_player_features(player_name: str, position: str, season: int = None) -> Dict[str, float]:
    """Get player-specific features based on position."""
    if season is None:
        season = datetime.now().year
    
    stats = get_stats_instance()
    
    position = position.upper()
    if position == 'QB':
        return stats.get_qb_features(player_name, season)
    elif position == 'RB':
        return stats.get_rb_features(player_name, season)
    elif position in ('WR', 'TE'):
        return stats.get_wr_features(player_name, season)
    else:
        return {}
