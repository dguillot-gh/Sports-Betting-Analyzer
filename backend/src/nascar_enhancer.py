"""
NASCAR Data Enhancer Module
Contains core logic for processing RDA files and calculating features.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import pyreadr

def load_rda_file(filepath):
    """Load .rda file using pyreadr"""
    try:
        result = pyreadr.read_r(str(filepath))
        # The key is usually the filename without extension
        key = list(result.keys())[0]
        return result[key]
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def standardize_columns(df, series_name):
    """Standardize column names across different series"""
    # Map for Truck/Xfinity series which have different names
    column_map = {
        'Season': 'year',
        'Race': 'race_num', 
        'Track': 'track',
        'Name': 'race_name',
        'Finish': 'finishing_position',
        'Start': 'start',
        'Car': 'car_num',
        'Driver': 'driver',
        'Make': 'manu',
        'Team': 'team_name',
        'Laps': 'laps',
        'Led': 'laps_led',
        'Status': 'status',
        'Win': 'race_win',
        'S1': 'stage_1',
        'S2': 'stage_2',
        'Pts': 'points'
    }
    
    # Rename columns if they exist
    df = df.rename(columns=column_map)
    
    # Ensure year column exists (handle case where it might be 'year' or 'Season')
    if 'year' not in df.columns and 'Season' in df.columns:
        df['year'] = df['Season']
        
    # Ensure finishing_position exists
    if 'finishing_position' not in df.columns and 'fin' in df.columns:
        df['finishing_position'] = df['fin']
        
    # Ensure race_win exists
    if 'race_win' not in df.columns:
        if 'finishing_position' in df.columns:
            df['race_win'] = (df['finishing_position'] == 1).astype(int)
            
    return df

def calculate_features(df):
    """Calculate powerful features for the model"""
    # Sort by date (year, race_num) to ensure historical features don't leak future data
    df = df.sort_values(['year', 'race_num'])
    
    # 1. Basic Features
    if 'start' in df.columns:
        df['pole_position'] = (df['start'] == 1).astype(int)
        df['qualified_top5'] = (df['start'] <= 5).astype(int)
        df['qualified_top10'] = (df['start'] <= 10).astype(int)
    
    # Track Type Features
    if 'track' in df.columns:
        # Create explicit track_type column
        df['track_type'] = 'Speedway' # Default
        
        # Define masks
        is_road = df['track'].astype(str).str.contains('Road|Glen|Sonoma|Circuit|Roval|Chicago Street', case=False)
        is_ss = df['track'].astype(str).str.contains('Daytona|Talladega|Atlanta', case=False) # Atlanta is SS now
        is_short = df['track'].astype(str).str.contains('Bristol|Martinsville|Richmond|Iowa|North Wilkesboro', case=False)
        is_dirt = df['track'].astype(str).str.contains('Dirt', case=False)
        
        # Apply types
        df.loc[is_road, 'track_type'] = 'Road Course'
        df.loc[is_ss, 'track_type'] = 'Superspeedway'
        df.loc[is_short, 'track_type'] = 'Short Track'
        df.loc[is_dirt, 'track_type'] = 'Dirt'

        # Keep boolean flags for ML compatibility if needed, or rely on one-hot encoding of track_type later
        df['is_road_course'] = is_road.astype(int)
        df['is_superspeedway'] = is_ss.astype(int)
        df['is_short_track'] = is_short.astype(int)

    # 2. Driver Career Stats (Cumulative)
    # Use transform to ensure alignment with original index
    
    # Career Races
    df['career_races'] = df.groupby('driver').cumcount()
    
    # Career Wins
    df['career_wins'] = df.groupby('driver')['race_win'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
    
    # Career Win Percentage
    df['career_win_pct'] = (df['career_wins'] / df['career_races'].replace(0, 1)).fillna(0)
    
    # Career Top 5/10
    df['is_top5'] = (df['finishing_position'] <= 5).astype(int)
    df['is_top10'] = (df['finishing_position'] <= 10).astype(int)
    
    df['career_top5'] = df.groupby('driver')['is_top5'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
    df['career_top10'] = df.groupby('driver')['is_top10'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
    
    # Career Average Finish
    df['career_avg_finish'] = df.groupby('driver')['finishing_position'].transform(lambda x: x.expanding().mean().shift(1)).fillna(20)
    
    # 3. Driver Track History
    # Group by driver AND track
    track_groups = df.groupby(['driver', 'track'])
    
    df['races_at_track'] = track_groups.cumcount()
    df['wins_at_track'] = track_groups['race_win'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
    df['avg_finish_at_track'] = track_groups['finishing_position'].transform(lambda x: x.expanding().mean().shift(1)).fillna(20)
    df['best_finish_at_track'] = track_groups['finishing_position'].transform(lambda x: x.expanding().min().shift(1)).fillna(40)
    
    # 4. Recent Form (Rolling Averages)
    # Sort by driver then date for rolling calcs
    
    for window in [3, 5, 10]:
        df[f'avg_finish_last_{window}'] = df.groupby('driver')['finishing_position'] \
            .transform(lambda x: x.shift(1).rolling(window, min_periods=1).mean()) \
            .fillna(20)
            
    # 5. Team Stats (Season Level)
    if 'team_name' in df.columns:
        team_groups = df.groupby(['team_name', 'year'])
        
        df['team_wins_this_season'] = team_groups['race_win'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
        df['team_top5_this_season'] = team_groups['is_top5'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
        df['team_avg_finish_this_season'] = team_groups['finishing_position'].transform(lambda x: x.expanding().mean().shift(1)).fillna(20)
        
    # 6. Manufacturer Stats
    if 'manu' in df.columns:
        manu_groups = df.groupby(['manu', 'year'])
        df['manu_wins_this_season'] = manu_groups['race_win'].transform(lambda x: x.cumsum().shift(1)).fillna(0)
        df['manu_win_pct_this_season'] = manu_groups['race_win'].transform(lambda x: x.expanding().mean().shift(1)).fillna(0)

    # Clean up temporary columns
    drop_cols = ['is_top5', 'is_top10']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    
    # Fill any remaining NaNs with reasonable defaults
    df = df.fillna(0)
    
    return df

def process_series(series_name, rda_filename, output_filename, data_dir):
    """Process a single series"""
    raw_dir = data_dir / "raw"
    input_path = raw_dir / rda_filename
    output_path = data_dir / output_filename
    
    if not input_path.exists():
        return False, f"Input file not found: {input_path}"
        
    # 1. Load Data
    df = load_rda_file(input_path)
    if df is None:
        return False, "Failed to load RDA file"
        
    # 2. Standardize Columns
    df = standardize_columns(df, series_name)
    
    # 3. Filter Years (Modern Era: 2012 onwards)
    if 'year' in df.columns:
        df = df[df['year'] >= 2012]
    
    # 4. Calculate Features
    try:
        df = calculate_features(df)
    except Exception as e:
        return False, f"Error calculating features: {e}"
        
    # 5. Save to CSV
    df.to_csv(output_path, index=False)
    
    return True, f"Successfully processed {len(df)} rows"

def enhance_all_series(data_dir: Path):
    """Run enhancement for all series"""
    results = {}
    
    series_list = [
        ("Cup Series", "cup_series.rda", "cup_enhanced.csv"),
        ("Truck Series", "truck_series.rda", "truck_enhanced.csv"),
        ("Xfinity Series", "xfinity_series.rda", "xfinity_enhanced.csv")
    ]
    
    for name, rda, csv in series_list:
        success, message = process_series(name, rda, csv, data_dir)
        results[name] = {"success": success, "message": message}
        
    return results
