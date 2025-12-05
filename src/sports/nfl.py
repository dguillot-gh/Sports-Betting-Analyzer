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
        """Load NFL data from CSV files."""
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
            'numeric': ['schedule_season', 'schedule_week', 'weather_temperature',
                       'weather_wind_mph', 'weather_humidity', 'spread_favorite', 'over_under_line']
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
