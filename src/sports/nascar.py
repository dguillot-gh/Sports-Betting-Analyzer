"""
NASCAR sport implementation.
"""
from typing import Dict, List, Any
import pandas as pd
from pathlib import Path

from .base import BaseSport


class NASCARSport(BaseSport):
    """NASCAR-specific sport implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def load_data(self) -> pd.DataFrame:
        """Load NASCAR race results from CSV if present, else fall back to .rda files."""
        paths = self.get_data_paths()

        results_path: Path = paths.get('results_file')  # type: ignore

        # Preferred: CSV as defined in config, if it exists
        if results_path and results_path.exists():
            # If a single RDA file is configured, read it with pyreadr
            if results_path.suffix.lower() == '.rda':
                try:
                    import pyreadr  # type: ignore
                except Exception:
                    raise ImportError(
                        "pyreadr is required to read .rda files. Install with: pip install pyreadr"
                    )
                result = pyreadr.read_r(str(results_path))
                frames = [df for df in result.values() if isinstance(df, pd.DataFrame)]
                if not frames:
                    raise ValueError(f"No tabular data found inside RDA file: {results_path}")
                df = pd.concat(frames, ignore_index=True, sort=False)
            else:
                df = pd.read_csv(results_path)
            df.columns = [c.strip() for c in df.columns]
            return self.preprocess_data(df)

        # Fallback: scan for .rda files in data/nascar/raw
        raw_dir = self.data_dir / 'raw'
        rda_files = sorted(raw_dir.glob('*.rda'))

        if not rda_files:
            # If no .rda files either, raise a clear error mentioning both options
            expected = str(results_path) if results_path else '<configured results_file>'
            raise FileNotFoundError(
                f"NASCAR data not found. Expected CSV at {expected} or .rda files in {raw_dir}"
            )

        try:
            import pyreadr  # type: ignore
        except Exception:
            raise ImportError(
                "pyreadr is required to read .rda files. Install with: pip install pyreadr"
            )

        # Read all data frames from all .rda files, concatenate into a single DataFrame
        frames: List[pd.DataFrame] = []
        for rda in rda_files:
            try:
                result = pyreadr.read_r(str(rda))  # returns a dict-like of dataframes
            except Exception as e:
                raise RuntimeError(f"Failed to read RDA file {rda}: {e}")

            for name, frame in result.items():
                if not isinstance(frame, pd.DataFrame):
                    continue
                # Normalize column names
                frame = frame.copy()
                frame.columns = [str(c).strip() for c in frame.columns]
                frames.append(frame)

        if not frames:
            raise ValueError(f"No tabular data found inside RDA files: {[str(p) for p in rda_files]}")

        # Heuristic: prefer dataframes that contain key NASCAR columns; otherwise concatenate all
        def has_core_cols(df: pd.DataFrame) -> bool:
            core = {'year', 'track', 'fin', 'driver'}
            return core.issubset(set(map(str.lower, df.columns))) or core.issubset(set(df.columns))

        preferred = [f for f in frames if has_core_cols(f)]
        if preferred:
            df = pd.concat(preferred, ignore_index=True, sort=False)
        else:
            df = pd.concat(frames, ignore_index=True, sort=False)

        return self.preprocess_data(df)

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
            'categorical': feats.get('categorical', []),
            'boolean': feats.get('boolean', []),
            'numeric': feats.get('numeric', []),
        }

    def get_target_columns(self) -> Dict[str, str]:
        """Return target columns mapping for NASCAR."""
        t = self.config.get('targets', {})
        # Defaults if not present
        classification = t.get('classification', 'race_win')
        regression = t.get('regression', 'finishing_position')
        return {'classification': classification, 'regression': regression}