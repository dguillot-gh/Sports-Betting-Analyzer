"""
Apex Model - Feature Engineering Pipeline
Enhanced feature extraction for NBA and NFL predictions.
Uses comprehensive data sources to create 50+ features.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Check dependencies
try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas/numpy not available")


class ApexFeatureExtractor:
    """
    Extract comprehensive features for Apex model predictions.
    Supports both NBA and NFL with sport-specific feature sets.
    """
    
    # NBA Feature definitions
    NBA_BASE_FEATURES = [
        'W_PCT', 'PTS', 'FG_PCT', 'FG3_PCT', 'FT_PCT',
        'REB', 'AST', 'STL', 'BLK', 'TOV', 'PLUS_MINUS'
    ]
    
    # NFL Feature definitions
    NFL_BASE_FEATURES = [
        'ppg', 'oppg', 'win_pct', 'yards_per_game', 'turnovers',
        'third_down_pct', 'red_zone_pct', 'epa_per_play'
    ]
    
    def __init__(self):
        self.nba_team_stats = None
        self.nfl_team_stats = None
        self._nba_data_loaded = False
        self._nfl_data_loaded = False
    
    # ==================== NBA Features ====================
    
    async def load_nba_data(self) -> bool:
        """Load current NBA team stats from NBA API."""
        if self._nba_data_loaded and self.nba_team_stats is not None:
            return True
        
        import aiohttp
        
        # Current season
        now = datetime.now()
        if now.month >= 10:
            season = f"{now.year}-{str(now.year + 1)[2:]}"
        else:
            season = f"{now.year - 1}-{str(now.year)[2:]}"
        
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # Fetch base stats
        url = (
            f"https://stats.nba.com/stats/leaguedashteamstats?"
            f"Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&"
            f"ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&"
            f"OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&"
            f"PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season={season}&"
            f"SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&"
            f"TeamID=0&TwoWay=0&VsConference=&VsDivision="
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"NBA API returned {response.status}")
                        return False
                    data = await response.json()
            
            result_sets = data.get('resultSets', [])
            if not result_sets:
                return False
            
            headers_list = result_sets[0].get('headers', [])
            rows = result_sets[0].get('rowSet', [])
            
            self.nba_team_stats = pd.DataFrame(data=rows, columns=headers_list)
            self._nba_data_loaded = True
            logger.info(f"Loaded NBA stats for {len(self.nba_team_stats)} teams")
            return True
            
        except Exception as e:
            logger.error(f"Error loading NBA data: {e}")
            return False
    
    def extract_nba_features(
        self, 
        home_team: str, 
        away_team: str,
        include_enhanced: bool = True
    ) -> Optional[Dict[str, float]]:
        """
        Extract NBA features for a matchup.
        Returns feature dict ready for model prediction.
        """
        if not self._nba_data_loaded or self.nba_team_stats is None:
            logger.error("NBA data not loaded")
            return None
        
        # Find teams in data
        home_row = self._find_nba_team(home_team)
        away_row = self._find_nba_team(away_team)
        
        if home_row is None or away_row is None:
            return None
        
        features = {}
        
        # Base features (same as kyleskom)
        for col in self.NBA_BASE_FEATURES:
            if col in home_row.index:
                features[f'home_{col}'] = float(home_row[col])
            if col in away_row.index:
                features[f'away_{col}'] = float(away_row[col])
        
        if include_enhanced:
            # Enhanced features - what kyleskom doesn't have
            
            # 1. Differential features
            for col in ['PTS', 'REB', 'AST', 'TOV']:
                if f'home_{col}' in features and f'away_{col}' in features:
                    features[f'diff_{col}'] = features[f'home_{col}'] - features[f'away_{col}']
            
            # 2. Net rating approximation
            home_net = features.get('home_PLUS_MINUS', 0)
            away_net = features.get('away_PLUS_MINUS', 0)
            features['net_rating_diff'] = home_net - away_net
            
            # 3. Efficiency metrics
            if 'home_PTS' in features and 'home_FG_PCT' in features:
                features['home_efficiency'] = features['home_PTS'] * features['home_FG_PCT']
            if 'away_PTS' in features and 'away_FG_PCT' in features:
                features['away_efficiency'] = features['away_PTS'] * features['away_FG_PCT']
            
            # 4. Home court advantage indicator
            features['home_court'] = 1.0
            
            # 5. Win percentage differential
            home_wpct = features.get('home_W_PCT', 0.5)
            away_wpct = features.get('away_W_PCT', 0.5)
            features['wpct_diff'] = home_wpct - away_wpct
        
        return features
    
    def _find_nba_team(self, team_name: str) -> Optional[pd.Series]:
        """Find NBA team in stats DataFrame."""
        # Try exact match
        match = self.nba_team_stats[self.nba_team_stats['TEAM_NAME'] == team_name]
        if len(match) > 0:
            return match.iloc[0]
        
        # Try partial match
        parts = team_name.split()
        for part in parts:
            if len(part) > 3:
                match = self.nba_team_stats[
                    self.nba_team_stats['TEAM_NAME'].str.contains(part, case=False, na=False)
                ]
                if len(match) > 0:
                    return match.iloc[0]
        
        logger.warning(f"NBA team not found: {team_name}")
        return None
    
    # ==================== NFL Features ====================
    
    async def load_nfl_data(self) -> bool:
        """Load NFL team stats from nflverse data including advanced stats."""
        if self._nfl_data_loaded and self.nfl_team_stats is not None:
            return True
        
        import os
        
        # Try to load from local parquet files
        stats_path = "/app/data/nflverse/schedules.csv"
        if not os.path.exists(stats_path):
            stats_path = "data/nflverse/schedules.csv"
        
        if not os.path.exists(stats_path):
            logger.warning(f"NFL schedules not found at {stats_path}")
            return False
        
        try:
            schedules = pd.read_csv(stats_path)
            
            # Calculate team rolling stats from schedules
            # Filter to completed games
            games = schedules[schedules['home_score'].notna()].copy()
            games = games.sort_values('gameday')
            
            # Build team stats dictionary
            team_stats = {}
            
            for team in pd.concat([games['home_team'], games['away_team']]).unique():
                team_home = games[games['home_team'] == team]
                team_away = games[games['away_team'] == team]
                
                # Calculate aggregate stats
                home_pts = team_home['home_score'].mean() if len(team_home) > 0 else 22
                away_pts = team_away['away_score'].mean() if len(team_away) > 0 else 22
                home_opp_pts = team_home['away_score'].mean() if len(team_home) > 0 else 22
                away_opp_pts = team_away['home_score'].mean() if len(team_away) > 0 else 22
                
                total_games = len(team_home) + len(team_away)
                if total_games == 0:
                    continue
                
                ppg = (home_pts * len(team_home) + away_pts * len(team_away)) / total_games
                oppg = (home_opp_pts * len(team_home) + away_opp_pts * len(team_away)) / total_games
                
                # Count wins
                home_wins = ((team_home['home_score'] > team_home['away_score']).sum() 
                             if len(team_home) > 0 else 0)
                away_wins = ((team_away['away_score'] > team_away['home_score']).sum() 
                             if len(team_away) > 0 else 0)
                wins = home_wins + away_wins
                win_pct = wins / total_games if total_games > 0 else 0.5
                
                team_stats[team] = {
                    'ppg': ppg,
                    'oppg': oppg,
                    'win_pct': win_pct,
                    'games': total_games,
                    'home_games': len(team_home),
                    'away_games': len(team_away),
                    # Advanced features - will be populated from parquet files
                    'epa_per_play': 0.0,
                    'epa_pass': 0.0,
                    'epa_rush': 0.0,
                    'turnover_margin': 0.0,
                    'turnovers_per_game': 0.0,
                    'takeaways_per_game': 0.0,
                    'third_down_pct': 0.40,  # Default
                    'red_zone_pct': 0.55,    # Default
                    'sacks_per_game': 2.0,   # Default
                    'pass_yards_per_game': 220.0,
                    'rush_yards_per_game': 110.0,
                }
            
            self.nfl_team_stats = pd.DataFrame.from_dict(team_stats, orient='index')
            
            # Load advanced stats from parquet files if available
            await self._load_nfl_advanced_stats()
            
            self._nfl_data_loaded = True
            logger.info(f"Loaded NFL stats for {len(self.nfl_team_stats)} teams with advanced metrics")
            return True
            
        except Exception as e:
            logger.error(f"Error loading NFL data: {e}")
            return False
    
    async def _load_nfl_advanced_stats(self):
        """Load advanced NFL stats from parquet files to enhance features."""
        import os
        import pyarrow.parquet as pq
        
        base_path = "/app/data/nflverse"
        if not os.path.exists(base_path):
            base_path = "data/nflverse"
        
        # Try to load team-level advanced stats
        try:
            # Load passing stats for EPA
            passing_path = os.path.join(base_path, "advstats_season_pass.parquet")
            if os.path.exists(passing_path):
                pass_df = pq.read_table(passing_path).to_pandas()
                # Get latest season
                if 'season' in pass_df.columns:
                    latest = pass_df['season'].max()
                    pass_df = pass_df[pass_df['season'] == latest]
                
                # Aggregate by team
                if 'team' in pass_df.columns and 'passing_epa' in pass_df.columns:
                    team_epa = pass_df.groupby('team')['passing_epa'].mean()
                    for team, epa in team_epa.items():
                        if team in self.nfl_team_stats.index:
                            self.nfl_team_stats.loc[team, 'epa_pass'] = epa
                logger.info("Loaded NFL passing EPA stats")
            
            # Load rushing stats
            rushing_path = os.path.join(base_path, "advstats_season_rush.parquet")
            if os.path.exists(rushing_path):
                rush_df = pq.read_table(rushing_path).to_pandas()
                if 'season' in rush_df.columns:
                    latest = rush_df['season'].max()
                    rush_df = rush_df[rush_df['season'] == latest]
                
                if 'team' in rush_df.columns and 'rushing_epa' in rush_df.columns:
                    team_epa = rush_df.groupby('team')['rushing_epa'].mean()
                    for team, epa in team_epa.items():
                        if team in self.nfl_team_stats.index:
                            self.nfl_team_stats.loc[team, 'epa_rush'] = epa
                logger.info("Loaded NFL rushing EPA stats")
            
        except Exception as e:
            logger.warning(f"Could not load advanced stats: {e}")
        
        # Calculate combined EPA
        self.nfl_team_stats['epa_per_play'] = (
            self.nfl_team_stats['epa_pass'] + self.nfl_team_stats['epa_rush']
        ) / 2
    
    def extract_nfl_features(
        self, 
        home_team: str, 
        away_team: str,
        include_enhanced: bool = True
    ) -> Optional[Dict[str, float]]:
        """
        Extract NFL features for a matchup.
        Returns feature dict ready for model prediction.
        """
        if not self._nfl_data_loaded or self.nfl_team_stats is None:
            logger.error("NFL data not loaded")
            return None
        
        # Find teams
        if home_team not in self.nfl_team_stats.index:
            logger.warning(f"NFL team not found: {home_team}")
            return None
        if away_team not in self.nfl_team_stats.index:
            logger.warning(f"NFL team not found: {away_team}")
            return None
        
        home_stats = self.nfl_team_stats.loc[home_team]
        away_stats = self.nfl_team_stats.loc[away_team]
        
        features = {
            'home_ppg': float(home_stats['ppg']),
            'home_oppg': float(home_stats['oppg']),
            'home_win_pct': float(home_stats['win_pct']),
            'away_ppg': float(away_stats['ppg']),
            'away_oppg': float(away_stats['oppg']),
            'away_win_pct': float(away_stats['win_pct']),
        }
        
        if include_enhanced:
            # Enhanced features
            
            # 1. Point differential
            features['home_point_diff'] = features['home_ppg'] - features['home_oppg']
            features['away_point_diff'] = features['away_ppg'] - features['away_oppg']
            features['point_diff_advantage'] = features['home_point_diff'] - features['away_point_diff']
            
            # 2. Win percentage differential
            features['wpct_diff'] = features['home_win_pct'] - features['away_win_pct']
            
            # 3. Home field advantage
            features['home_field'] = 1.0
            
            # 4. Offensive/Defensive ratings
            features['home_off_rating'] = features['home_ppg']
            features['home_def_rating'] = features['home_oppg']
            features['away_off_rating'] = features['away_ppg']
            features['away_def_rating'] = features['away_oppg']
            
            # 5. Net rating
            features['home_net_rating'] = features['home_ppg'] - features['home_oppg']
            features['away_net_rating'] = features['away_ppg'] - features['away_oppg']
            
            # 6. EPA features (Expected Points Added)
            features['home_epa_per_play'] = float(home_stats.get('epa_per_play', 0))
            features['home_epa_pass'] = float(home_stats.get('epa_pass', 0))
            features['home_epa_rush'] = float(home_stats.get('epa_rush', 0))
            features['away_epa_per_play'] = float(away_stats.get('epa_per_play', 0))
            features['away_epa_pass'] = float(away_stats.get('epa_pass', 0))
            features['away_epa_rush'] = float(away_stats.get('epa_rush', 0))
            features['epa_advantage'] = features['home_epa_per_play'] - features['away_epa_per_play']
            
            # 7. Turnover features
            features['home_turnover_margin'] = float(home_stats.get('turnover_margin', 0))
            features['away_turnover_margin'] = float(away_stats.get('turnover_margin', 0))
            features['turnover_margin_diff'] = features['home_turnover_margin'] - features['away_turnover_margin']
            
            # 8. Third down and red zone efficiency
            features['home_third_down_pct'] = float(home_stats.get('third_down_pct', 0.40))
            features['away_third_down_pct'] = float(away_stats.get('third_down_pct', 0.40))
            features['home_red_zone_pct'] = float(home_stats.get('red_zone_pct', 0.55))
            features['away_red_zone_pct'] = float(away_stats.get('red_zone_pct', 0.55))
            
            # 9. Yards per game
            features['home_pass_ypg'] = float(home_stats.get('pass_yards_per_game', 220))
            features['home_rush_ypg'] = float(home_stats.get('rush_yards_per_game', 110))
            features['away_pass_ypg'] = float(away_stats.get('pass_yards_per_game', 220))
            features['away_rush_ypg'] = float(away_stats.get('rush_yards_per_game', 110))
        
        return features
    
    def features_to_array(self, features: Dict[str, float]) -> 'np.ndarray':
        """Convert feature dict to numpy array for model input."""
        if not PANDAS_AVAILABLE:
            raise RuntimeError("numpy not available")
        
        # Sort keys for consistent ordering
        sorted_keys = sorted(features.keys())
        return np.array([features[k] for k in sorted_keys], dtype=np.float32)
    
    def get_feature_names(self, sport: str = 'nba') -> List[str]:
        """Get ordered list of feature names for a sport."""
        if sport.lower() == 'nba':
            sample = self.extract_nba_features('Boston Celtics', 'Los Angeles Lakers')
        else:
            sample = self.extract_nfl_features('KC', 'PHI')
        
        if sample:
            return sorted(sample.keys())
        return []


# Singleton instance
_extractor = None

def get_feature_extractor() -> ApexFeatureExtractor:
    global _extractor
    if _extractor is None:
        _extractor = ApexFeatureExtractor()
    return _extractor


async def extract_nba_features(home_team: str, away_team: str) -> Optional[Dict[str, float]]:
    """Convenience function to extract NBA features."""
    extractor = get_feature_extractor()
    await extractor.load_nba_data()
    return extractor.extract_nba_features(home_team, away_team)


async def extract_nfl_features(home_team: str, away_team: str) -> Optional[Dict[str, float]]:
    """Convenience function to extract NFL features."""
    extractor = get_feature_extractor()
    await extractor.load_nfl_data()
    return extractor.extract_nfl_features(home_team, away_team)
