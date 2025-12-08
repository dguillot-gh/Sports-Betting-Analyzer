"""
NFL sport implementation.
"""
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd
from .base import BaseSport


class NFLSport(BaseSport):
    """NFL-specific sport implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def load_data(self) -> pd.DataFrame:
        """Load NFL data from CSV files and merge with enhanced team stats."""
        self.validate_data_files()
        paths = self.get_data_paths()

        scores_path = paths.get('scores_file')
        teams_path = paths.get('teams_file')

        if not scores_path or not teams_path:
            raise ValueError("NFL config must specify scores_file and teams_file")

        # Load data
        scores = pd.read_csv(scores_path)
        teams = pd.read_csv(teams_path)

        # Basic cleaning
        scores.columns = [c.strip() for c in scores.columns]
        teams.columns = [c.strip() for c in teams.columns]

        # Apply preprocessing
        df = self.preprocess_data(scores)

        # Add team mappings
        df = self._add_team_mappings(df, teams)
        
        # Try to load enhanced team stats and merge
        df = self._merge_team_stats(df)
        
        # Calculate rolling features
        df = self._calculate_rolling_features(df)

        return df
    
    def _get_team_name_map(self) -> dict:
        """Get mapping from short team names (ESPN) to full team names (spreadspoke)."""
        return {
            # Short name (ESPN team_stats) -> Full name (spreadspoke_scores)
            'Cardinals': 'Arizona Cardinals', '49ers': 'San Francisco 49ers',
            'Falcons': 'Atlanta Falcons', 'Ravens': 'Baltimore Ravens',
            'Bills': 'Buffalo Bills', 'Panthers': 'Carolina Panthers',
            'Bears': 'Chicago Bears', 'Bengals': 'Cincinnati Bengals',
            'Browns': 'Cleveland Browns', 'Cowboys': 'Dallas Cowboys',
            'Broncos': 'Denver Broncos', 'Lions': 'Detroit Lions',
            'Packers': 'Green Bay Packers', 'Texans': 'Houston Texans',
            'Colts': 'Indianapolis Colts', 'Jaguars': 'Jacksonville Jaguars',
            'Chiefs': 'Kansas City Chiefs', 'Raiders': 'Las Vegas Raiders',
            'Chargers': 'Los Angeles Chargers', 'Rams': 'Los Angeles Rams',
            'Dolphins': 'Miami Dolphins', 'Vikings': 'Minnesota Vikings',
            'Patriots': 'New England Patriots', 'Saints': 'New Orleans Saints',
            'Giants': 'New York Giants', 'Jets': 'New York Jets',
            'Eagles': 'Philadelphia Eagles', 'Steelers': 'Pittsburgh Steelers',
            'Seahawks': 'Seattle Seahawks', 'Buccaneers': 'Tampa Bay Buccaneers',
            'Titans': 'Tennessee Titans', 'Commanders': 'Washington Commanders',
            # Historical names
            'Redskins': 'Washington Redskins', 'Football Team': 'Washington Football Team',
            'Oilers': 'Houston Oilers', 'St. Louis Rams': 'St. Louis Rams',
            'San Diego Chargers': 'San Diego Chargers', 'Oakland Raiders': 'Oakland Raiders',
        }
    
    def _merge_team_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Merge enhanced team stats from Kaggle dataset."""
        team_stats_path = self.data_dir / 'team_stats' / 'nfl_team_stats_2002-2024.csv'
        
        if not team_stats_path.exists():
            print(f"DEBUG: Team stats file not found at {team_stats_path}, skipping merge")
            return df
            
        try:
            stats = pd.read_csv(team_stats_path)
            print(f"DEBUG: Loaded team stats with {len(stats)} rows")
            
            # Map short team names to full names
            team_map = self._get_team_name_map()
            stats['home_full'] = stats['home'].map(team_map).fillna(stats['home'])
            stats['away_full'] = stats['away'].map(team_map).fillna(stats['away'])
            
            # Parse dates
            if 'schedule_date' in df.columns:
                df['schedule_date'] = pd.to_datetime(df['schedule_date'], errors='coerce')
            if 'date' in stats.columns:
                stats['date'] = pd.to_datetime(stats['date'], errors='coerce')
            
            # Create game-level stats for home and away teams (using full names now)
            home_stats = stats[['date', 'home_full', 'score_home', 'yards_home', 'first_downs_home', 
                               'rush_yards_home', 'pass_yards_home', 'fumbles_home', 'interceptions_home']].copy()
            home_stats.columns = ['date', 'team', 'pts', 'yards', 'first_downs', 'rush_yards', 
                                 'pass_yards', 'fumbles', 'interceptions']
            
            away_stats = stats[['date', 'away_full', 'score_away', 'yards_away', 'first_downs_away',
                               'rush_yards_away', 'pass_yards_away', 'fumbles_away', 'interceptions_away']].copy()
            away_stats.columns = ['date', 'team', 'pts', 'yards', 'first_downs', 'rush_yards',
                                 'pass_yards', 'fumbles', 'interceptions']
            
            # Combine home and away stats
            all_team_stats = pd.concat([home_stats, away_stats], ignore_index=True)
            all_team_stats = all_team_stats.dropna(subset=['date', 'team'])
            all_team_stats = all_team_stats.sort_values(['team', 'date'])
            
            # Store for rolling calculation
            self._team_game_stats = all_team_stats
            print(f"DEBUG: Prepared {len(all_team_stats)} team-game records for rolling stats")
            
        except Exception as e:
            print(f"DEBUG: Error loading team stats: {e}")
            self._team_game_stats = None
            
        return df
    
    def _calculate_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate rolling average features for each team."""
        if not hasattr(self, '_team_game_stats') or self._team_game_stats is None:
            print("DEBUG: No team game stats available, skipping rolling features")
            return df
            
        team_stats = self._team_game_stats
        
        # Calculate rolling means for each team (last 5 games)
        rolling_cols = ['pts', 'yards', 'first_downs', 'rush_yards', 'pass_yards']
        
        for col in rolling_cols:
            team_stats[f'{col}_rolling5'] = team_stats.groupby('team')[col].transform(
                lambda x: x.shift(1).rolling(5, min_periods=1).mean()
            )
        
        # Also add turnovers (fumbles + interceptions)
        team_stats['turnovers'] = team_stats['fumbles'].fillna(0) + team_stats['interceptions'].fillna(0)
        team_stats['turnovers_rolling5'] = team_stats.groupby('team')['turnovers'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
        
        # Now merge rolling stats into main dataframe
        df = df.copy()
        if 'schedule_date' in df.columns:
            df['schedule_date'] = pd.to_datetime(df['schedule_date'], errors='coerce')
        
        # Merge for home team
        home_rolling = team_stats[['date', 'team', 'pts_rolling5', 'yards_rolling5', 
                                   'first_downs_rolling5', 'turnovers_rolling5']].copy()
        home_rolling.columns = ['schedule_date', 'team_home', 'home_ppg_rolling5', 'home_yards_rolling5',
                               'home_first_downs_rolling5', 'home_turnovers_rolling5']
        
        df = df.merge(home_rolling, on=['schedule_date', 'team_home'], how='left')
        
        # Merge for away team
        away_rolling = team_stats[['date', 'team', 'pts_rolling5', 'yards_rolling5',
                                   'first_downs_rolling5', 'turnovers_rolling5']].copy()
        away_rolling.columns = ['schedule_date', 'team_away', 'away_ppg_rolling5', 'away_yards_rolling5',
                               'away_first_downs_rolling5', 'away_turnovers_rolling5']
        
        df = df.merge(away_rolling, on=['schedule_date', 'team_away'], how='left')
        
        # Add differential features
        df['ppg_diff_rolling5'] = df['home_ppg_rolling5'] - df['away_ppg_rolling5']
        df['yards_diff_rolling5'] = df['home_yards_rolling5'] - df['away_yards_rolling5']
        
        print(f"DEBUG: Added rolling features. Non-null home_ppg_rolling5: {df['home_ppg_rolling5'].notna().sum()}")
        
        return df

    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply NFL-specific preprocessing."""
        # Create targets
        df = df.copy()
        df['point_diff'] = df['score_home'] - df['score_away']
        df['home_team_win'] = (df['point_diff'] > 0).astype(int)

        # Convert booleans
        def to_bool(s):
            if pd.api.types.is_bool_dtype(s):
                return s
            return s.astype(str).str.upper().map({'TRUE': True, 'FALSE': False}).fillna(False)

        bool_cols = ['schedule_playoff', 'stadium_neutral']
        for col in bool_cols:
            if col in df.columns:
                df[col] = to_bool(df[col])

        # Coerce numeric columns
        numeric_cols = ['schedule_season', 'schedule_week', 'weather_temperature',
                       'weather_wind_mph', 'weather_humidity', 'spread_favorite', 'over_under_line']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    def _add_team_mappings(self, df: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
        """Add team ID mappings to the dataframe."""
        # Create team mapping dictionary
        team_map = teams.set_index('team_name')['team_id'].to_dict()

        # Add reverse mappings for short names
        for _, row in teams.iterrows():
            team_map.setdefault(row.get('team_name_short', row['team_name']), row['team_id'])

        def map_team(name):
            return team_map.get(name, name)

        df = df.copy()
        df['home_id'] = df['team_home'].map(map_team)
        df['away_id'] = df['team_away'].map(map_team)

        return df

    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return NFL feature column groupings."""
        return {
            'categorical': ['home_id', 'away_id', 'team_favorite_id', 'stadium', 'weather_detail'],
            'boolean': ['schedule_playoff', 'stadium_neutral'],
            'numeric': [
                # Original features
                'schedule_season', 'schedule_week', 'weather_temperature',
                'weather_wind_mph', 'weather_humidity', 'spread_favorite', 'over_under_line',
                # Rolling average features (from enhanced team stats)
                'home_ppg_rolling5', 'home_yards_rolling5', 'home_first_downs_rolling5', 'home_turnovers_rolling5',
                'away_ppg_rolling5', 'away_yards_rolling5', 'away_first_downs_rolling5', 'away_turnovers_rolling5',
                'ppg_diff_rolling5', 'yards_diff_rolling5'
            ]
        }

    def get_target_columns(self) -> Dict[str, str]:
        """Return NFL target column names."""
        return {
            'classification': 'home_team_win',
            'regression': 'point_diff'
        }

    def get_entities(self) -> List[str]:
        """Return list of all teams."""
        df = self.load_data()
        teams = set(df['team_home'].dropna().unique()) | set(df['team_away'].dropna().unique())
        return sorted(list(teams))

    def get_teams(self) -> List[str]:
        """Return list of all teams (same as entities for NFL)."""
        return self.get_entities()

    def get_drivers(self, team_id: str = None) -> List[str]:
        """Return list of players. NFL doesn't track individual players in this dataset."""
        # NFL betting data doesn't include individual player info
        return []

    def get_entity_stats(self, entity_id: str) -> Dict[str, Any]:
        """Return comprehensive stats for a team."""
        df = self.load_data()
        
        # Filter for games involving this team
        team_games = df[(df['team_home'] == entity_id) | (df['team_away'] == entity_id)].copy()
        
        if team_games.empty:
            return {'stats': {}, 'splits': {}, 'history': []}

        # Sort chronologically
        sort_cols = []
        if 'schedule_season' in team_games.columns: sort_cols.append('schedule_season')
        if 'schedule_week' in team_games.columns: sort_cols.append('schedule_week')
        if sort_cols:
            team_games = team_games.sort_values(sort_cols, ascending=False)

        # Helper to get team's score and opponent's score
        def get_scores(row):
            if row['team_home'] == entity_id:
                return row['score_home'], row['score_away'], 'Home'
            else:
                return row['score_away'], row['score_home'], 'Away'

        # Calculate stats
        wins = 0
        losses = 0
        ties = 0
        points_for = 0
        points_against = 0
        
        home_wins = 0
        home_games = 0
        away_wins = 0
        away_games = 0

        history = []

        for _, row in team_games.iterrows():
            pf, pa, loc = get_scores(row)
            
            # Skip if scores are missing (future games)
            if pd.isna(pf) or pd.isna(pa):
                continue
                
            points_for += pf
            points_against += pa
            
            is_win = False
            if pf > pa:
                wins += 1
                is_win = True
                if loc == 'Home': home_wins += 1
                else: away_wins += 1
            elif pf < pa:
                losses += 1
            else:
                ties += 1
                
            if loc == 'Home': home_games += 1
            else: away_games += 1

            # Add to history (limit to recent 10)
            if len(history) < 10:
                history.append({
                    "Season": row.get('schedule_season', 'N/A'),
                    "Week": row.get('schedule_week', 'N/A'),
                    "Opponent": row['team_away'] if loc == 'Home' else row['team_home'],
                    "Result": "W" if is_win else ("T" if pf == pa else "L"),
                    "Score": f"{int(pf)}-{int(pa)}",
                    "Location": loc
                })

        total_games = wins + losses + ties
        if total_games == 0:
             return {'stats': {}, 'splits': {}, 'history': []}

        stats = {
            "Games": total_games,
            "Record": f"{wins}-{losses}-{ties}",
            "Win %": f"{(wins/total_games)*100:.1f}%",
            "Avg Points For": f"{(points_for/total_games):.1f}",
            "Avg Points Against": f"{(points_against/total_games):.1f}",
            "Point Diff": int(points_for - points_against),
            "Avg Diff": f"{((points_for - points_against)/total_games):.1f}"
        }

        splits = {
            "Home": {
                "Games": home_games,
                "Record": f"{home_wins}-{home_games-home_wins}",
                "Win %": f"{(home_wins/home_games*100) if home_games > 0 else 0:.1f}%"
            },
            "Away": {
                "Games": away_games,
                "Record": f"{away_wins}-{away_games-away_wins}",
                "Win %": f"{(away_wins/away_games*100) if away_games > 0 else 0:.1f}%"
            }
        }

        return {
            "stats": stats,
            "splits": splits,
            "history": history
        }
