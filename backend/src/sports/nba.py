"""
NBA sport implementation.
"""
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
from .base import BaseSport


class NBASport(BaseSport):
    """NBA-specific sport implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Override data_dir to use mllearning/data path (where NBA data actually is)
        project_root = Path(__file__).resolve().parents[2]
        self.data_dir = project_root / 'mllearning' / 'data' / self.name
        self.df = None  # Cache loaded data
        self._team_name_map = None  # Cache team abbrev -> full name mapping
        self._abbrev_to_name = None  # OKC -> Oklahoma City Thunder

    def _load_team_names(self) -> None:
        """Load team abbreviation to full name mapping."""
        if self._team_name_map is not None:
            return
            
        abbrev_file = self.data_dir / 'raw' / 'Team Abbrev.csv'
        if abbrev_file.exists():
            try:
                team_df = pd.read_csv(abbrev_file)
                # Get latest mapping for each abbreviation
                team_df = team_df.sort_values('season', ascending=False)
                team_df = team_df.drop_duplicates('abbreviation', keep='first')
                
                # Create abbrev -> full name mapping
                self._abbrev_to_name = dict(zip(team_df['abbreviation'], team_df['team']))
                # Create full name -> abbrev mapping
                self._team_name_map = dict(zip(team_df['team'], team_df['abbreviation']))
            except Exception as e:
                print(f"Warning: Could not load team names: {e}")
                self._abbrev_to_name = {}
                self._team_name_map = {}
        else:
            self._abbrev_to_name = {}
            self._team_name_map = {}

    def _get_full_team_name(self, abbrev: str) -> str:
        """Convert team abbreviation to full name."""
        self._load_team_names()
        return self._abbrev_to_name.get(abbrev, abbrev)
    
    def _get_team_abbrev(self, full_name: str) -> str:
        """Convert full team name to abbreviation."""
        self._load_team_names()
        return self._team_name_map.get(full_name, full_name)

    def load_data(self) -> pd.DataFrame:
        """Load NBA data from CSV files. Tries game-level data first, falls back to player data."""
        if self.df is not None:
            return self.df
        
        # Try loading game-level data first (for game predictions)
        game_df = self._load_game_data()
        if game_df is not None and not game_df.empty:
            self.df = game_df
            return self.df
            
        # Fall back to player per game stats (original behavior)
        player_file = self.data_dir / 'raw' / 'Player Per Game.csv'
        if not player_file.exists():
            raise FileNotFoundError(f"NBA player data not found at {player_file}")
            
        df = pd.read_csv(player_file)
        
        # Basic cleaning
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        
        # Apply preprocessing
        df = self.preprocess_data(df)
        
        self.df = df
        return df
    
    def _load_game_data(self) -> Optional[pd.DataFrame]:
        """Load game-level team statistics for game predictions."""
        # Check for box_scores data from Kaggle - use project root
        project_root = Path(__file__).resolve().parents[2]
        box_scores_dir = project_root / 'data' / 'nba' / 'box_scores'
        team_stats_file = box_scores_dir / 'TeamStatistics.csv'
        
        if not team_stats_file.exists():
            print(f"DEBUG: NBA TeamStatistics not found at {team_stats_file}")
            return None
            
        try:
            print(f"DEBUG: Loading NBA TeamStatistics from {team_stats_file}")
            ts = pd.read_csv(team_stats_file)
            print(f"DEBUG: Loaded {len(ts)} team-game records")
            
            # Parse date and sort
            ts['game_date'] = pd.to_datetime(ts['gameDateTimeEst'], errors='coerce')
            ts = ts.sort_values(['teamName', 'game_date'])
            
            # Calculate rolling averages for key stats (last 5 games)
            rolling_cols = ['teamScore', 'assists', 'reboundsTotal', 'turnovers', 
                           'fieldGoalsPercentage', 'threePointersPercentage']
            
            for col in rolling_cols:
                ts[f'{col}_rolling5'] = ts.groupby('teamName')[col].transform(
                    lambda x: x.shift(1).rolling(5, min_periods=1).mean()
                )
            
            # Add opponent score rolling average
            ts['opponentScore_rolling5'] = ts.groupby('teamName')['opponentScore'].transform(
                lambda x: x.shift(1).rolling(5, min_periods=1).mean()
            )
            
            # Calculate rest days (important for NBA)
            ts['days_rest'] = ts.groupby('teamName')['game_date'].diff().dt.days.fillna(7)
            ts['back_to_back'] = (ts['days_rest'] <= 1).astype(int)
            
            # --- Schedule Fatigue Features (Vectorized for speed) ---
            # Sort by team and date for proper sequential calculations
            ts = ts.sort_values(['teamName', 'game_date']).reset_index(drop=True)
            
            # Games in last 7 days - use rolling count with a 7-day window
            # Create a game counter (1 for each game)
            ts['game_marker'] = 1
            # For games_last_7, we count games in the 7 days BEFORE this game (excluding current)
            ts['games_last_7'] = ts.groupby('teamName')['game_marker'].transform(
                lambda x: x.shift(1).rolling(7, min_periods=0).sum()
            ).fillna(0).astype(int)
            
            # 3-in-4 nights: Look at the gap from 3 games ago
            # If the game 3 positions ago was within 3 days, we're playing 3-in-4
            ts['days_since_3_ago'] = ts.groupby('teamName')['game_date'].transform(
                lambda x: (x - x.shift(2)).dt.days
            )
            ts['three_in_4'] = ((ts['days_since_3_ago'].notna()) & (ts['days_since_3_ago'] <= 3)).astype(int)
            
            # 4-in-5 nights: Look at the gap from 4 games ago
            ts['days_since_4_ago'] = ts.groupby('teamName')['game_date'].transform(
                lambda x: (x - x.shift(3)).dt.days
            )
            ts['four_in_5'] = ((ts['days_since_4_ago'].notna()) & (ts['days_since_4_ago'] <= 4)).astype(int)
            
            # Road trip game number: Count consecutive away games
            # When home=True, reset to 0. When home=False, increment counter.
            ts['is_away'] = (~ts['home']).astype(int)
            
            # Create groups that reset when we have a home game
            ts['home_reset'] = ts['home'].astype(int)
            ts['road_trip_group'] = ts.groupby('teamName')['home_reset'].transform('cumsum')
            
            # Count within each road trip
            ts['road_trip_game'] = ts.groupby(['teamName', 'road_trip_group'])['is_away'].transform('cumsum')
            # Zero out for home games
            ts.loc[ts['home'] == True, 'road_trip_game'] = 0
            
            # Days since last home game
            # Forward fill the date of the last home game
            ts['last_home_date'] = ts['game_date'].where(ts['home'] == True)
            ts['last_home_date'] = ts.groupby('teamName')['last_home_date'].transform(lambda x: x.ffill())
            ts['days_since_home'] = (ts['game_date'] - ts['last_home_date']).dt.days.fillna(0).astype(int)
            # For home games, days_since_home should be 0
            ts.loc[ts['home'] == True, 'days_since_home'] = 0
            
            # Clean up temp columns
            ts = ts.drop(columns=['game_marker', 'days_since_3_ago', 'days_since_4_ago', 
                                  'is_away', 'home_reset', 'road_trip_group', 'last_home_date'], errors='ignore')
            


            # Now pivot to create matchup-level records
            # Filter to home games only (each game appears twice, once per team)
            home_games = ts[ts['home'] == True].copy()
            away_games = ts[ts['home'] == False].copy()
            
            # Rename columns for merge
            home_cols = {
                'teamName': 'home_team', 'opponentTeamName': 'away_team',
                'teamScore': 'home_score', 'opponentScore': 'away_score',
                'teamScore_rolling5': 'home_ppg_rolling5',
                'opponentScore_rolling5': 'home_opp_ppg_rolling5',
                'assists_rolling5': 'home_assists_rolling5',
                'reboundsTotal_rolling5': 'home_rebounds_rolling5',
                'turnovers_rolling5': 'home_turnovers_rolling5',
                'fieldGoalsPercentage_rolling5': 'home_fg_pct_rolling5',
                'threePointersPercentage_rolling5': 'home_three_pct_rolling5',
                'days_rest': 'home_days_rest',
                'back_to_back': 'home_back_to_back',
                'games_last_7': 'home_games_last_7',
                'three_in_4': 'home_three_in_4',
                'four_in_5': 'home_four_in_5',
                'win': 'home_team_win',
                'game_date': 'schedule_date',
                'gameId': 'game_id'
            }
            
            home_games = home_games.rename(columns=home_cols)
            
            # Get away team rolling stats (including fatigue features)
            away_rolling = away_games[['gameId', 'teamName', 'teamScore_rolling5', 
                                       'opponentScore_rolling5', 'assists_rolling5', 
                                       'reboundsTotal_rolling5', 'turnovers_rolling5',
                                       'fieldGoalsPercentage_rolling5', 'threePointersPercentage_rolling5',
                                       'days_rest', 'back_to_back',
                                       'games_last_7', 'three_in_4', 'four_in_5',
                                       'road_trip_game', 'days_since_home']].copy()
            away_rolling.columns = ['game_id', 'away_team_check', 'away_ppg_rolling5', 
                                    'away_opp_ppg_rolling5', 'away_assists_rolling5',
                                    'away_rebounds_rolling5', 'away_turnovers_rolling5',
                                    'away_fg_pct_rolling5', 'away_three_pct_rolling5',
                                    'away_days_rest', 'away_back_to_back',
                                    'away_games_last_7', 'away_three_in_4', 'away_four_in_5',
                                    'away_road_trip_game', 'away_days_since_home']
            
            # Merge away stats to home games
            games = home_games.merge(away_rolling, on='game_id', how='left')
            
            # Extract season from date
            games['schedule_season'] = games['schedule_date'].dt.year
            # Adjust for NBA season spanning years (games before June are previous season)
            games.loc[games['schedule_date'].dt.month < 6, 'schedule_season'] -= 1
            
            # Add differential features
            games['ppg_diff_rolling5'] = games['home_ppg_rolling5'] - games['away_ppg_rolling5']
            games['fg_pct_diff_rolling5'] = games['home_fg_pct_rolling5'] - games['away_fg_pct_rolling5']
            
            # Convert home_team_win to int
            games['home_team_win'] = games['home_team_win'].astype(int)
            games['point_diff'] = games['home_score'] - games['away_score']
            
            print(f"DEBUG: Created {len(games)} NBA game records with rolling features")
            print(f"DEBUG: Non-null home_ppg_rolling5: {games['home_ppg_rolling5'].notna().sum()}")
            
            return games
            
        except Exception as e:
            print(f"DEBUG: Error loading NBA game data: {e}")
            import traceback
            traceback.print_exc()
            return None

    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply NBA-specific preprocessing."""
        df = df.copy()
        
        # Standardize column names
        rename_map = {
            'player_id': 'player_id',
            'player': 'player_name',
            'team': 'team_abbrev',
            'pos': 'position',
            'g': 'games',
            'gs': 'games_started',
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        
        # Coerce numeric columns
        numeric_cols = ['season', 'age', 'games', 'games_started', 'mp_per_game',
                       'fg_per_game', 'fga_per_game', 'fg_percent',
                       'x3p_per_game', 'x3pa_per_game', 'x3p_percent',
                       'ft_per_game', 'fta_per_game', 'ft_percent',
                       'orb_per_game', 'drb_per_game', 'trb_per_game',
                       'ast_per_game', 'stl_per_game', 'blk_per_game',
                       'tov_per_game', 'pf_per_game', 'pts_per_game']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if 'schedule_season' not in df.columns and 'season' in df.columns:
            df['schedule_season'] = df['season']
        elif 'schedule_season' not in df.columns:
            df['schedule_season'] = 2024 # Default fallback

        # Create target column 'is_all_star' (approximation: >20 PPG)
        if 'is_all_star' not in df.columns:
            if 'pts_per_game' in df.columns:
                df['is_all_star'] = (df['pts_per_game'] >= 20.0).astype(int)
            else:
                # Fallback if no points data
                df['is_all_star'] = 0

        return df

    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return NBA feature column groupings."""
        # Check if we have game-level data
        if self.df is not None and 'home_ppg_rolling5' in self.df.columns:
            # Game-level features for win prediction
            return {
                'categorical': ['home_team', 'away_team'],
                'boolean': ['home_back_to_back', 'away_back_to_back',
                           'home_three_in_4', 'home_four_in_5',
                           'away_three_in_4', 'away_four_in_5'],
                'numeric': [
                    'schedule_season',
                    # Rolling averages - home team
                    'home_ppg_rolling5', 'home_opp_ppg_rolling5', 'home_assists_rolling5',
                    'home_rebounds_rolling5', 'home_turnovers_rolling5',
                    'home_fg_pct_rolling5', 'home_three_pct_rolling5',
                    'home_days_rest', 'home_games_last_7',
                    # Rolling averages - away team
                    'away_ppg_rolling5', 'away_opp_ppg_rolling5', 'away_assists_rolling5',
                    'away_rebounds_rolling5', 'away_turnovers_rolling5',
                    'away_fg_pct_rolling5', 'away_three_pct_rolling5',
                    'away_days_rest', 'away_games_last_7',
                    # Away team road trip fatigue
                    'away_road_trip_game', 'away_days_since_home',
                    # Differentials
                    'ppg_diff_rolling5', 'fg_pct_diff_rolling5'
                ]
            }
        else:
            # Player-level features (original)
            return {
                'categorical': ['player_name', 'team_abbrev', 'position'],
                'boolean': [],
                'numeric': ['season', 'age', 'games', 'games_started', 'mp_per_game',
                           'fg_per_game', 'fga_per_game', 'fg_percent',
                           'x3p_per_game', 'x3pa_per_game', 'x3p_percent',
                           'ft_per_game', 'fta_per_game', 'ft_percent',
                           'orb_per_game', 'drb_per_game', 'trb_per_game',
                           'ast_per_game', 'stl_per_game', 'blk_per_game',
                           'tov_per_game', 'pf_per_game', 'pts_per_game']
            }

    def get_target_columns(self) -> Dict[str, str]:
        """Return NBA target column names."""
        # Check if we have game-level data
        if self.df is not None and 'home_team_win' in self.df.columns:
            return {
                'classification': 'home_team_win',
                'regression': 'point_diff'
            }
        else:
            return {
                'classification': 'is_all_star',
                'regression': 'pts_per_game'
            }

    def get_entities(self) -> List[str]:
        """Return list of all players."""
        df = self.load_data()
        if 'player_name' in df.columns:
            return sorted(df['player_name'].dropna().unique().tolist())
        elif 'player' in df.columns:
            return sorted(df['player'].dropna().unique().tolist())
        return []

    def get_teams(self) -> List[str]:
        """Return list of all teams with FULL NAMES."""
        df = self.load_data()
        col = 'team_abbrev' if 'team_abbrev' in df.columns else 'team'
        if col in df.columns:
            # Get unique abbreviations
            abbrevs = df[col].dropna().unique().tolist()
            # Convert to full names
            full_names = []
            for abbrev in abbrevs:
                full_name = self._get_full_team_name(abbrev)
                full_names.append(full_name)
            return sorted(set(full_names))
        return []

    def get_drivers(self, team_id: Optional[str] = None) -> List[str]:
        """Return list of players (NBA equivalent of 'drivers')."""
        return self.get_players(team_id)

    def get_players(self, team_id: Optional[str] = None) -> List[str]:
        """Return list of players, optionally filtered by team (accepts full name or abbrev)."""
        df = self.load_data()
        
        player_col = 'player_name' if 'player_name' in df.columns else 'player'
        team_col = 'team_abbrev' if 'team_abbrev' in df.columns else 'team'
        
        if team_id and team_col in df.columns:
            # Try to match - could be abbreviation or full name
            self._load_team_names()
            
            # Check if it's a full name and convert to abbrev
            if team_id in self._team_name_map:
                team_abbrev = self._team_name_map[team_id]
            else:
                team_abbrev = team_id  # Assume it's already an abbreviation
            
            df = df[df[team_col] == team_abbrev]
            
        if player_col in df.columns:
            return sorted(df[player_col].dropna().unique().tolist())
        return []

    def get_entity_stats(self, entity_id: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Return comprehensive stats for a player."""
        df = self.load_data()
        
        player_col = 'player_name' if 'player_name' in df.columns else 'player'
        
        # Filter for this player
        player_data = df[df[player_col] == entity_id].copy()
        
        if player_data.empty:
            return {'stats': {}, 'splits': {}, 'history': [], 'years': []}
        
        # Sort by season descending
        if 'season' in player_data.columns:
            player_data = player_data.sort_values('season', ascending=False)
            years = sorted(player_data['season'].dropna().unique().tolist(), reverse=True)
        else:
            years = []
        
        # Filter by year if specified
        if year and 'season' in player_data.columns:
            player_data = player_data[player_data['season'] == year]
        
        if player_data.empty:
            return {'stats': {}, 'splits': {}, 'history': [], 'years': years}
        
        # Get latest season data for stats
        latest = player_data.iloc[0]
        
        # Get full team name
        team_abbrev = latest.get('team_abbrev', latest.get('team', 'N/A'))
        team_full = self._get_full_team_name(team_abbrev) if pd.notna(team_abbrev) else 'N/A'
        
        # Build stats dictionary
        stats = {
            "Season": int(latest.get('season', 0)) if pd.notna(latest.get('season')) else 'N/A',
            "Team": team_full,
            "Position": latest.get('position', latest.get('pos', 'N/A')),
            "Age": int(latest.get('age', 0)) if pd.notna(latest.get('age')) else 'N/A',
            "Games": int(latest.get('games', latest.get('g', 0))) if pd.notna(latest.get('games', latest.get('g'))) else 0,
            "Games Started": int(latest.get('games_started', latest.get('gs', 0))) if pd.notna(latest.get('games_started', latest.get('gs'))) else 0,
            "PPG": f"{latest.get('pts_per_game', 0):.1f}" if pd.notna(latest.get('pts_per_game')) else 'N/A',
            "RPG": f"{latest.get('trb_per_game', 0):.1f}" if pd.notna(latest.get('trb_per_game')) else 'N/A',
            "APG": f"{latest.get('ast_per_game', 0):.1f}" if pd.notna(latest.get('ast_per_game')) else 'N/A',
            "SPG": f"{latest.get('stl_per_game', 0):.1f}" if pd.notna(latest.get('stl_per_game')) else 'N/A',
            "BPG": f"{latest.get('blk_per_game', 0):.1f}" if pd.notna(latest.get('blk_per_game')) else 'N/A',
            "FG%": f"{latest.get('fg_percent', 0)*100:.1f}%" if pd.notna(latest.get('fg_percent')) else 'N/A',
            "3P%": f"{latest.get('x3p_percent', 0)*100:.1f}%" if pd.notna(latest.get('x3p_percent')) else 'N/A',
            "FT%": f"{latest.get('ft_percent', 0)*100:.1f}%" if pd.notna(latest.get('ft_percent')) else 'N/A',
            "MPG": f"{latest.get('mp_per_game', 0):.1f}" if pd.notna(latest.get('mp_per_game')) else 'N/A',
        }
        
        # Splits by team (using full names)
        team_col = 'team_abbrev' if 'team_abbrev' in player_data.columns else 'team'
        splits = {}
        if team_col in player_data.columns:
            for team, group in player_data.groupby(team_col):
                team_name = self._get_full_team_name(str(team))
                splits[team_name] = {
                    "Seasons": len(group),
                    "Avg PPG": f"{group['pts_per_game'].mean():.1f}" if 'pts_per_game' in group.columns else 'N/A',
                    "Avg RPG": f"{group['trb_per_game'].mean():.1f}" if 'trb_per_game' in group.columns else 'N/A',
                    "Avg APG": f"{group['ast_per_game'].mean():.1f}" if 'ast_per_game' in group.columns else 'N/A',
                }
        
        # History (season by season)
        history = []
        for _, row in player_data.head(10).iterrows():
            team_abbrev_hist = row.get('team_abbrev', row.get('team', 'N/A'))
            team_full_hist = self._get_full_team_name(team_abbrev_hist) if pd.notna(team_abbrev_hist) else 'N/A'
            history.append({
                "Season": int(row.get('season', 0)) if pd.notna(row.get('season')) else 'N/A',
                "Team": team_full_hist,
                "Games": int(row.get('games', row.get('g', 0))) if pd.notna(row.get('games', row.get('g'))) else 0,
                "PPG": f"{row.get('pts_per_game', 0):.1f}" if pd.notna(row.get('pts_per_game')) else 'N/A',
                "RPG": f"{row.get('trb_per_game', 0):.1f}" if pd.notna(row.get('trb_per_game')) else 'N/A',
                "APG": f"{row.get('ast_per_game', 0):.1f}" if pd.notna(row.get('ast_per_game')) else 'N/A',
            })
        
        return {
            "stats": stats,
            "splits": splits,
            "history": history,
            "years": years
        }

    def get_year_range(self) -> Dict[str, int]:
        """Return the min and max season years available in the data."""
        df = self.load_data()
        if 'season' in df.columns:
            return {
                "min_year": int(df['season'].min()),
                "max_year": int(df['season'].max())
            }
        return {"min_year": 1947, "max_year": 2026}
