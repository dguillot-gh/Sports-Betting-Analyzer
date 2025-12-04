"""
NASCAR sport implementation.
"""
from typing import Dict, List, Any, Optional
import pandas as pd
from pathlib import Path
import json
import numpy as np



from .base import BaseSport


class NASCARSport(BaseSport):
    """NASCAR-specific sport implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def load_data(self) -> pd.DataFrame:
        """Load NASCAR data from static JSON file."""
        json_path = self.data_dir / 'nascar_data.json'
        
        if not json_path.exists():
            # Fallback to old method if JSON doesn't exist
            print(f"WARNING: Static data file {json_path} not found. Falling back to raw data.")
            return self._load_raw_data()
            
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            # Cache active lists for get_teams/get_drivers
            self._active_teams = data.get('active_teams', [])
            self._active_teams_by_series = data.get('active_teams_by_series', {})
            self._active_drivers = data.get('active_drivers', [])
            self._active_drivers_by_series = data.get('active_drivers_by_series', {})
            
            # Load records into DataFrame
            records = data.get('records', [])
            if not records:
                return pd.DataFrame()
                
            df = pd.DataFrame(records)
            self.df = self.preprocess_data(df)
            return self.df
            
        except Exception as e:
            print(f"Error loading static data: {e}")
            return self._load_raw_data()

    def get_roster(self, series: str = "cup", min_races: int = 1, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return driver roster for given series, filtered by minimum races and optionally year."""
        # Ensure data is loaded
        if not hasattr(self, '_active_drivers_by_series'):
            self.load_data()
        
        # If year is not specified, use the pre-calculated active list (default behavior)
        if year is None:
            if not hasattr(self, '_active_drivers_by_series'):
                return []
            roster = self._active_drivers_by_series.get(series, [])
            if min_races > 1:
                roster = [d for d in roster if d['total_races'] >= min_races]
            return roster

        # If year IS specified, calculate from historical data
        if not hasattr(self, 'df') or self.df is None:
            return []

        # Filter by year and series
        # Note: series in df is lowercase
        series_lower = series.lower()
        year_df = self.df[(self.df['year_num'] == year) & (self.df['series'] == series_lower)]
        
        if year_df.empty:
            return []

        driver_roster = []
        for driver_name in year_df['driver'].unique():
            if driver_name == 'Unknown':
                continue
                
            driver_df = year_df[year_df['driver'] == driver_name]
            
            # Get most recent team and make for that year
            # Sort by race number if available, or just take the last one
            # Assuming the data is somewhat ordered or we can just take the mode
            latest_entry = driver_df.iloc[-1] # Simple approach
            
            team = latest_entry['team_name'] if 'team_name' in latest_entry else 'Unknown'
            make = latest_entry['Make'] if 'Make' in latest_entry else latest_entry.get('make', 'Unknown')
            
            total_races = len(driver_df)
            
            if total_races >= min_races:
                driver_roster.append({
                    'name': str(driver_name),
                    'team': str(team),
                    'manufacturer': str(make),
                    'races_2024': 0, # Not relevant for specific year view
                    'races_2025': 0, # Not relevant for specific year view
                    'total_races': int(total_races)
                })
        
        # Sort by total races descending
        driver_roster.sort(key=lambda x: x['total_races'], reverse=True)
        return driver_roster

    def get_teams(self) -> List[str]:
        """Return a list of all available teams."""
        # Check if we have active teams loaded from JSON
        if hasattr(self, '_active_teams') and self._active_teams:
            # Check if a specific series is configured
            series = self.config.get('series')
            
            if series and hasattr(self, '_active_teams_by_series'):
                # Return teams for this series, or fallback to all active teams
                return self._active_teams_by_series.get(series, self._active_teams)
            
            return self._active_teams
            
        # Fallback to unique values in dataframe
        if hasattr(self, 'df') and self.df is not None and 'team_name' in self.df.columns:
            return sorted(self.df['team_name'].dropna().unique().tolist())
        return []



    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply NASCAR-specific preprocessing and target creation."""
        df = df.copy()

        # Normalize column names - handle case variations
        df.columns = [c.strip() for c in df.columns]
        col_lower = {c.lower(): c for c in df.columns}

        # Ensure expected columns exist; create if missing
        # Map various finish position column names to standardized 'finishing_position'
        if 'finishing_position' not in df.columns:
            # Try different possible column names for finish position
            finish_cols = ['fin', 'finish', 'finishing_position']
            found = None
            for fc in finish_cols:
                if fc in df.columns:
                    found = fc
                    break
                elif fc in col_lower:
                    found = col_lower[fc]
                    break
            
            if found:
                df['finishing_position'] = pd.to_numeric(df[found], errors='coerce')
            else:
                # If none exists, we can't determine finishing position
                raise ValueError(
                    f"Missing required column: no finish position column found. "
                    f"Looked for: {finish_cols}. Available columns: {list(df.columns)}"
                )

        # Classification target: race win flag
        if 'race_win' not in df.columns:
            # Check if 'Win' column exists (some series have this pre-calculated)
            if 'Win' in df.columns or 'win' in col_lower:
                win_col = 'Win' if 'Win' in df.columns else col_lower['win']
                df['race_win'] = pd.to_numeric(df[win_col], errors='coerce').fillna(0).astype(int)
            elif 'finishing_position' in df.columns:
                df['race_win'] = (df['finishing_position'] == 1).astype(int)
            else:
                raise ValueError("Cannot create 'race_win' target without 'finishing_position' or 'Win' column")

        # Standardize season column expected by generic trainer
        if 'schedule_season' not in df.columns:
            # Try various season column names
            season_cols = ['year', 'season', 'Year', 'Season']
            found_season = None
            for sc in season_cols:
                if sc in df.columns:
                    found_season = sc
                    break
            
            if found_season:
                df['schedule_season'] = pd.to_numeric(df[found_season], errors='coerce')
                # Log how many valid seasons we got
                valid_seasons = df['schedule_season'].notna().sum()
                print(f"Created schedule_season from '{found_season}': {valid_seasons} valid values out of {len(df)} rows")
                if valid_seasons == 0:
                    print(f"WARNING: No valid season values found. Sample of '{found_season}' column: {df[found_season].head(10).tolist()}")
            else:
                # Fallback: set to NA
                print(f"WARNING: No season column found. Available columns: {list(df.columns)}")
                df['schedule_season'] = pd.NA

        # Coerce numerics - handle different column name variations
        numeric_mapping = {
            'year': ['year', 'Year', 'season', 'Season'],
            'race_num': ['race_num', 'Race', 'race', 'race_number'],
            'start': ['start', 'Start'],
            'car_num': ['car_num', 'Car', 'car', 'car_number'],
            'laps': ['laps', 'Laps'],
            'laps_led': ['laps_led', 'Led', 'led'],
            'points': ['points', 'Pts', 'pts'],
            'stage_1': ['stage_1', 'S1', 's1'],
            'stage_2': ['stage_2', 'S2', 's2'],
            'stage_3_or_duel': ['stage_3_or_duel', 'S3', 's3'],
            'stage_points': ['stage_points', 'Seg Points', 'seg_points'],
        }
        
        # Map columns to standardized names
        for std_name, variations in numeric_mapping.items():
            if std_name not in df.columns:
                for var in variations:
                    if var in df.columns:
                        df[std_name] = pd.to_numeric(df[var], errors='coerce')
                        break
        
        # Always ensure these core columns are numeric
        core_numeric = ['year', 'race_num', 'start', 'car_num', 'laps', 'laps_led',
                       'points', 'stage_1', 'stage_2', 'stage_3_or_duel', 'stage_points',
                       'finishing_position', 'schedule_season']
        
        # Add configured numeric features
        features = self.get_feature_columns()
        core_numeric.extend(features.get('numeric', []))
        
        # Remove duplicates
        core_numeric = list(set(core_numeric))

        for col in core_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Fill simple categorical text fields with strings - handle variations
        categorical_mapping = {
            'driver': ['driver', 'Driver'],
            'track': ['track', 'Track'],
            'track_type': ['track_type', 'Surface', 'surface'],
            'manu': ['manu', 'Make', 'make', 'manufacturer'],
            'team_name': ['team_name', 'Team', 'team'],
            'status': ['status', 'Status'],
        }
        
        for std_name, variations in categorical_mapping.items():
            if std_name not in df.columns:
                for var in variations:
                    if var in df.columns:
                        df[std_name] = df[var].astype(str).fillna('Unknown')
                        break
            else:
                df[std_name] = df[std_name].astype(str).fillna('Unknown')

        # Debug: print final columns
        print(f"Final preprocessed columns: {sorted(df.columns.tolist())}")
        print(f"Sample row: {df.iloc[0].to_dict()}")
        
        return df

    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return NASCAR feature columns as configured."""
        feats = self.config.get('features', {})
        return {
            'numeric': feats.get('numeric', []),
            'categorical': feats.get('categorical', [])
        }
    def get_target_columns(self) -> Dict[str, str]:
        """Return target columns mapping for NASCAR."""
        t = self.config.get('targets', {})
        # Defaults if not present
        classification = t.get('classification', 'race_win')
        regression = t.get('regression', 'finishing_position')
        return {'classification': classification, 'regression': regression}

    def _load_raw_data(self) -> pd.DataFrame:
        """Load raw NASCAR data from .rda files (ignoring configured results_file)."""
        raw_dir = self.data_dir / 'raw'
        rda_files = sorted(raw_dir.glob('*.rda'))

        if not rda_files:
            return pd.DataFrame()

        try:
            import pyreadr  # type: ignore
        except Exception:
            return pd.DataFrame()


        frames: List[pd.DataFrame] = []
        for rda in rda_files:
            try:
                result = pyreadr.read_r(str(rda))
                # Infer series from filename (e.g. cup_series.rda -> cup)
                series_name = rda.stem.replace('_series', '').lower()
                
                for name, frame in result.items():
                    if isinstance(frame, pd.DataFrame):
                        frame = frame.copy()
                        frame.columns = [str(c).strip() for c in frame.columns]
                        # Inject series column
                        frame['series'] = series_name
                        frames.append(frame)
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        # Concatenate all
        df = pd.concat(frames, ignore_index=True, sort=False)
        return self.preprocess_data(df)

    def get_entities(self) -> List[str]:
        """Return list of all drivers."""
        # Use raw data for complete list
        df = self._load_raw_data()
        if df.empty:
            df = self.load_data()
            
        if 'driver' not in df.columns:
            return []
        
        # Filter out future/mock data (2025+)
        if 'year' in df.columns:
            df = df[df['year'] < 2025]
    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply NASCAR-specific preprocessing and target creation."""
        df = df.copy()

        # Normalize column names - handle case variations
        df.columns = [c.strip() for c in df.columns]
        col_lower = {c.lower(): c for c in df.columns}

        # Ensure expected columns exist; create if missing
        # Map various finish position column names to standardized 'finishing_position'
        if 'finishing_position' not in df.columns:
            # Try different possible column names for finish position
            finish_cols = ['fin', 'finish', 'finishing_position']
            found = None
            for fc in finish_cols:
                if fc in df.columns:
                    found = fc
                    break
                elif fc in col_lower:
                    found = col_lower[fc]
                    break
            
            if found:
                df['finishing_position'] = pd.to_numeric(df[found], errors='coerce')
            else:
                # If none exists, we can't determine finishing position
                raise ValueError(
                    f"Missing required column: no finish position column found. "
                    f"Looked for: {finish_cols}. Available columns: {list(df.columns)}"
                )

        # Classification target: race win flag
        if 'race_win' not in df.columns:
            # Check if 'Win' column exists (some series have this pre-calculated)
            if 'Win' in df.columns or 'win' in col_lower:
                win_col = 'Win' if 'Win' in df.columns else col_lower['win']
                df['race_win'] = pd.to_numeric(df[win_col], errors='coerce').fillna(0).astype(int)
            elif 'finishing_position' in df.columns:
                df['race_win'] = (df['finishing_position'] == 1).astype(int)
            else:
                raise ValueError("Cannot create 'race_win' target without 'finishing_position' or 'Win' column")

        # Standardize season column expected by generic trainer
        if 'schedule_season' not in df.columns:
            # Try various season column names
            season_cols = ['year', 'season', 'Year', 'Season']
            found_season = None
            for sc in season_cols:
                if sc in df.columns:
                    found_season = sc
                    break
            
            if found_season:
                df['schedule_season'] = pd.to_numeric(df[found_season], errors='coerce')
                # Log how many valid seasons we got
                valid_seasons = df['schedule_season'].notna().sum()
                print(f"Created schedule_season from '{found_season}': {valid_seasons} valid values out of {len(df)} rows")
                if valid_seasons == 0:
                    print(f"WARNING: No valid season values found. Sample of '{found_season}' column: {df[found_season].head(10).tolist()}")
            else:
                # Fallback: set to NA
                print(f"WARNING: No season column found. Available columns: {list(df.columns)}")
                df['schedule_season'] = pd.NA

        # Coerce numerics - handle different column name variations
        numeric_mapping = {
            'year': ['year', 'Year', 'season', 'Season'],
            'race_num': ['race_num', 'Race', 'race', 'race_number'],
            'start': ['start', 'Start'],
            'car_num': ['car_num', 'Car', 'car', 'car_number'],
            'laps': ['laps', 'Laps'],
            'laps_led': ['laps_led', 'Led', 'led'],
            'points': ['points', 'Pts', 'pts'],
            'stage_1': ['stage_1', 'S1', 's1'],
            'stage_2': ['stage_2', 'S2', 's2'],
            'stage_3_or_duel': ['stage_3_or_duel', 'S3', 's3'],
            'stage_points': ['stage_points', 'Seg Points', 'seg_points'],
        }
        
        # Map columns to standardized names
        for std_name, variations in numeric_mapping.items():
            if std_name not in df.columns:
                for var in variations:
                    if var in df.columns:
                        df[std_name] = pd.to_numeric(df[var], errors='coerce')
                        break
        
        # Always ensure these core columns are numeric
        core_numeric = ['year', 'race_num', 'start', 'car_num', 'laps', 'laps_led',
                       'points', 'stage_1', 'stage_2', 'stage_3_or_duel', 'stage_points',
                       'finishing_position', 'schedule_season']
        
        # Add configured numeric features
        features = self.get_feature_columns()
        core_numeric.extend(features.get('numeric', []))
        
        # Remove duplicates
        core_numeric = list(set(core_numeric))

        json_path = self.data_dir / 'nascar_data.json'
        
        if not json_path.exists():
            # Fallback to old method if JSON doesn't exist
            print(f"WARNING: Static data file {json_path} not found. Falling back to raw data.")
            return self._load_raw_data()
            
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            # Cache active lists for get_teams/get_drivers
            self._active_teams = data.get('active_teams', [])
            self._active_drivers = data.get('active_drivers', [])
            print(f"DEBUG: Loaded {len(self._active_teams)} active teams from JSON.")

            
            # Load records into DataFrame
            records = data.get('records', [])
            if not records:
                return pd.DataFrame()
                
            df = pd.DataFrame(records)
            return self.preprocess_data(df)
            
        except Exception as e:
            print(f"Error loading static data: {e}")
            return self._load_raw_data()

    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return NASCAR feature columns as configured."""
        feats = self.config.get('features', {})
        return {
            'numeric': feats.get('numeric', []),
            'categorical': feats.get('categorical', [])
        }
    def get_target_columns(self) -> Dict[str, str]:
        """Return target columns mapping for NASCAR."""
        t = self.config.get('targets', {})
        # Defaults if not present
        classification = t.get('classification', 'race_win')
        regression = t.get('regression', 'finishing_position')
        return {'classification': classification, 'regression': regression}

    def _load_raw_data(self) -> pd.DataFrame:
        """Legacy load method (fallback)."""
        import pandas as pd
        from typing import List
        raw_dir = self.data_dir / 'raw'
        rda_files = sorted(raw_dir.glob('*.rda'))

        if not rda_files:
            return pd.DataFrame()

        try:
            import pyreadr  # type: ignore
        except Exception:
            return pd.DataFrame()


        frames: List[pd.DataFrame] = []
        for rda in rda_files:
            try:
                result = pyreadr.read_r(str(rda))
                # Infer series from filename (e.g. cup_series.rda -> cup)
                series_name = rda.stem.replace('_series', '').lower()
                
                for name, frame in result.items():
                    if isinstance(frame, pd.DataFrame):
                        frame = frame.copy()
                        frame.columns = [str(c).strip() for c in frame.columns]
                        # Inject series column
                        frame['series'] = series_name
                        frames.append(frame)
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        # Concatenate all
        df = pd.concat(frames, ignore_index=True, sort=False)
        return self.preprocess_data(df)

    def get_entities(self) -> List[str]:
        """Return list of all drivers."""
        # Ensure data is loaded to populate _active_drivers
        if not hasattr(self, '_active_drivers'):
            self.load_data()
            
        if hasattr(self, '_active_drivers') and self._active_drivers:
            return self._active_drivers
            
        # Fallback
        df = self.load_data()
        if 'driver' not in df.columns:
            return []
        return sorted(df['driver'].dropna().unique().tolist())

    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply NASCAR-specific preprocessing and target creation."""
        df = df.copy()

        # Normalize column names - handle case variations
        df.columns = [c.strip() for c in df.columns]
        col_lower = {c.lower(): c for c in df.columns}

        # Ensure expected columns exist; create if missing
        # Map various finish position column names to standardized 'finishing_position'
        if 'finishing_position' not in df.columns:
            # Try different possible column names for finish position
            finish_cols = ['fin', 'finish', 'finishing_position']
            found = None
            for fc in finish_cols:
                if fc in df.columns:
                    found = fc
                    break
                elif fc in col_lower:
                    found = col_lower[fc]
                    break
            
            if found:
                df['finishing_position'] = pd.to_numeric(df[found], errors='coerce')
            else:
                # If none exists, we can't determine finishing position
                raise ValueError(
                    f"Missing required column: no finish position column found. "
                    f"Looked for: {finish_cols}. Available columns: {list(df.columns)}"
                )

        # Classification target: race win flag
        if 'race_win' not in df.columns:
            # Check if 'Win' column exists (some series have this pre-calculated)
            if 'Win' in df.columns or 'win' in col_lower:
                win_col = 'Win' if 'Win' in df.columns else col_lower['win']
                df['race_win'] = pd.to_numeric(df[win_col], errors='coerce').fillna(0).astype(int)
            elif 'finishing_position' in df.columns:
                df['race_win'] = (df['finishing_position'] == 1).astype(int)
            else:
                raise ValueError("Cannot create 'race_win' target without 'finishing_position' or 'Win' column")

        # Standardize season column expected by generic trainer
        if 'schedule_season' not in df.columns:
            # Try various season column names
            season_cols = ['year', 'season', 'Year', 'Season']
            found_season = None
            for sc in season_cols:
                if sc in df.columns:
                    found_season = sc
                    break
            
            if found_season:
                df['schedule_season'] = pd.to_numeric(df[found_season], errors='coerce')
                # Log how many valid seasons we got
                valid_seasons = df['schedule_season'].notna().sum()
                print(f"Created schedule_season from '{found_season}': {valid_seasons} valid values out of {len(df)} rows")
                if valid_seasons == 0:
                    print(f"WARNING: No valid season values found. Sample of '{found_season}' column: {df[found_season].head(10).tolist()}")
            else:
                # Fallback: set to NA
                print(f"WARNING: No season column found. Available columns: {list(df.columns)}")
                df['schedule_season'] = pd.NA

        # Coerce numerics - handle different column name variations
        numeric_mapping = {
            'year': ['year', 'Year', 'season', 'Season'],
            'race_num': ['race_num', 'Race', 'race', 'race_number'],
            'start': ['start', 'Start'],
            'car_num': ['car_num', 'Car', 'car', 'car_number'],
            'laps': ['laps', 'Laps'],
            'laps_led': ['laps_led', 'Led', 'led'],
            'points': ['points', 'Pts', 'pts'],
            'stage_1': ['stage_1', 'S1', 's1'],
            'stage_2': ['stage_2', 'S2', 's2'],
            'stage_3_or_duel': ['stage_3_or_duel', 'S3', 's3'],
            'stage_points': ['stage_points', 'Seg Points', 'seg_points'],
        }
        
        # Map columns to standardized names
        for std_name, variations in numeric_mapping.items():
            if std_name not in df.columns:
                for var in variations:
                    if var in df.columns:
                        df[std_name] = pd.to_numeric(df[var], errors='coerce')
                        break
        
        # Always ensure these core columns are numeric
        core_numeric = ['year', 'race_num', 'start', 'car_num', 'laps', 'laps_led',
                       'points', 'stage_1', 'stage_2', 'stage_3_or_duel', 'stage_points',
                       'finishing_position', 'schedule_season']
        
        # Add configured numeric features
        features = self.get_feature_columns()
        core_numeric.extend(features.get('numeric', []))
        
        # Remove duplicates
        core_numeric = list(set(core_numeric))

        for col in core_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Fill simple categorical text fields with strings - handle variations
        categorical_mapping = {
            'driver': ['driver', 'Driver'],
            'track': ['track', 'Track'],
            'track_type': ['track_type', 'Surface', 'surface'],
            'manu': ['manu', 'Make', 'make', 'manufacturer'],
            'team_name': ['team_name', 'Team', 'team'],
            'status': ['status', 'Status'],
        }
        
        for std_name, variations in categorical_mapping.items():
            if std_name not in df.columns:
                for var in variations:
                    if var in df.columns:
                        df[std_name] = df[var].astype(str).fillna('Unknown')
                        break
            else:
                df[std_name] = df[std_name].astype(str).fillna('Unknown')

        # Debug: print final columns
        print(f"Final preprocessed columns: {sorted(df.columns.tolist())}")
        print(f"Sample row: {df.iloc[0].to_dict()}")
        
        return df

    def get_feature_columns(self) -> Dict[str, List[str]]:
        """Return NASCAR feature columns as configured."""
        feats = self.config.get('features', {})
        return {
            'numeric': feats.get('numeric', []),
            'categorical': feats.get('categorical', [])
        }
    def get_target_columns(self) -> Dict[str, str]:
        """Return target columns mapping for NASCAR."""
        t = self.config.get('targets', {})
        # Defaults if not present
        classification = t.get('classification', 'race_win')
        regression = t.get('regression', 'finishing_position')
        return {'classification': classification, 'regression': regression}

    def _load_raw_data(self) -> pd.DataFrame:
        """Legacy load method (fallback)."""
        import pandas as pd
        from typing import List
        raw_dir = self.data_dir / 'raw'
        rda_files = sorted(raw_dir.glob('*.rda'))

        if not rda_files:
            return pd.DataFrame()

        try:
            import pyreadr  # type: ignore
        except Exception:
            return pd.DataFrame()

        frames: List[pd.DataFrame] = []
        for rda in rda_files:
            try:
                result = pyreadr.read_r(str(rda))
                for name, frame in result.items():
                    if isinstance(frame, pd.DataFrame):
                        frame = frame.copy()
                        frame.columns = [str(c).strip() for c in frame.columns]
                        frames.append(frame)
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        # Concatenate all
        df = pd.concat(frames, ignore_index=True, sort=False)
        return self.preprocess_data(df)

    def get_entities(self) -> List[str]:
        """Return list of all drivers."""
        # Ensure data is loaded to populate _active_drivers
        if not hasattr(self, '_active_drivers'):
            self.load_data()
            
        if hasattr(self, '_active_drivers') and self._active_drivers:
            return self._active_drivers
            
        # Fallback
        df = self.load_data()
        if 'driver' not in df.columns:
            return []
        return sorted(df['driver'].dropna().unique().tolist())

    def get_teams(self) -> List[str]:
        """Return list of all available teams."""
        # Ensure data is loaded to populate _active_teams
        if not hasattr(self, '_active_teams'):
            self.load_data()
            
        if hasattr(self, '_active_teams') and self._active_teams:
            return self._active_teams
            
        # Fallback
        df = self.load_data()
        if 'team_name' not in df.columns:
            return []
        return sorted(df['team_name'].dropna().unique().tolist())

    def get_drivers(self, team_id: Optional[str] = None) -> List[str]:
        """Return list of drivers, optionally filtered by team."""
        # If no team filter, return all active drivers
        if not team_id:
            if not hasattr(self, '_active_drivers'):
                self.load_data()
            if hasattr(self, '_active_drivers') and self._active_drivers:
                return self._active_drivers

        df = self.load_data()
        
        if 'driver' not in df.columns:
            return []
        
        if team_id:
            if 'team_name' in df.columns:
                # Case-insensitive match for team
                df = df[df['team_name'].str.lower() == team_id.lower()]
            else:
                return []
                
        # Filter for active drivers only (present in _active_drivers if available)
        drivers = sorted(df['driver'].dropna().unique().tolist())
        
        if hasattr(self, '_active_drivers') and self._active_drivers:
            active_set = set(self._active_drivers)
            drivers = [d for d in drivers if d in active_set]
            
        return drivers

    def get_entity_stats(self, entity_id: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Return comprehensive stats for a driver."""
        df = self.load_data()
        
        # Filter for driver
        driver_df = df[df['driver'] == entity_id].copy()
        
        if driver_df.empty:
            return {'stats': {}, 'splits': {}, 'history': [], 'years': []}

        # Get all available years for this driver before filtering
        available_years = []
        if 'schedule_season' in driver_df.columns:
            available_years = sorted(driver_df['schedule_season'].dropna().unique().astype(int).tolist(), reverse=True)
        elif 'year' in driver_df.columns:
            available_years = sorted(driver_df['year'].dropna().unique().astype(int).tolist(), reverse=True)

        # Filter by year if provided
        if year:
            if 'schedule_season' in driver_df.columns:
                driver_df = driver_df[driver_df['schedule_season'] == year]
            elif 'year' in driver_df.columns:
                driver_df = driver_df[driver_df['year'] == year]

        # Sort chronologically
        sort_cols = []
        if 'schedule_season' in driver_df.columns: sort_cols.append('schedule_season')
        if 'race_num' in driver_df.columns: sort_cols.append('race_num')
        if sort_cols:
            driver_df = driver_df.sort_values(sort_cols, ascending=False)

        # --- Core Stats ---
        total_races = len(driver_df)
        wins = len(driver_df[driver_df['finishing_position'] == 1])
        top_5 = len(driver_df[driver_df['finishing_position'] <= 5])
        top_10 = len(driver_df[driver_df['finishing_position'] <= 10])
        
        # New Stats
        laps_led = int(driver_df['laps_led'].sum()) if 'laps_led' in driver_df.columns else 0
        poles = len(driver_df[driver_df['start'] == 1]) if 'start' in driver_df.columns else 0
        dnfs = len(driver_df[driver_df['status'].str.lower() != 'running']) if 'status' in driver_df.columns else 0
        
        avg_finish = driver_df['finishing_position'].mean() if total_races > 0 else 0
        avg_start = driver_df['start'].mean() if 'start' in driver_df.columns and total_races > 0 else 0
        
        stats = {
            "Races": total_races,
            "Wins": wins,
            "Win %": f"{(wins/total_races)*100:.1f}%" if total_races > 0 else "0.0%",
            "Top 5": top_5,
            "Top 10": top_10,
            "Poles": poles,
            "Laps Led": laps_led,
            "DNFs": dnfs,
            "Avg Start": f"{avg_start:.1f}",
            "Avg Finish": f"{avg_finish:.1f}",
        }

        # --- Splits (Track Type) ---
        splits = {}
        if 'track_type' in driver_df.columns:
            for t_type, group in driver_df.groupby('track_type'):
                splits[t_type] = {
                    "Races": len(group),
                    "Avg Finish": f"{group['finishing_position'].mean():.1f}",
                    "Wins": len(group[group['finishing_position'] == 1])
                }

        # --- History (Recent 10 or all if filtered by year) ---
        # If year is selected, show all races for that year. If not, show recent 10.
        history_df = driver_df if year else driver_df.head(10)
        
        history = []
        for _, row in history_df.iterrows():
            history.append({
                "Season": row.get('schedule_season', row.get('year', 'N/A')),
                "Race": row.get('race_num', 'N/A'),
                "Track": row.get('track', 'Unknown'),
                "Start": row.get('start', 'N/A'),
                "Finish": row.get('finishing_position', 'N/A'),
                "Status": row.get('status', 'Unknown')
            })

        return {
            "stats": stats,
            "splits": splits,
            "history": history,
            "years": available_years
        }
