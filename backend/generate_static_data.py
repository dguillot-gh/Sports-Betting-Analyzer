import pandas as pd
import json
import pyreadr
from pathlib import Path
import numpy as np

def generate_static_data():
    """
    Reads raw .rda files, processes them, and generates a static JSON file
    containing active entities and historical data.
    """
    base_dir = Path(__file__).parent
    # Read from mllearning/data/nascar/raw (where .rda files are)
    raw_dir = base_dir / 'mllearning' / 'data' / 'nascar' / 'raw'
    # Output to data/nascar (where NASCAR sport class expects it)
    output_dir = base_dir / 'data' / 'nascar'
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / 'nascar_data.json'
    
    print(f"Scanning {raw_dir} for .rda files...")
    rda_files = sorted(raw_dir.glob('*.rda'))
    
    if not rda_files:
        print("No .rda files found!")
        return

    frames = []
    for rda in rda_files:
        try:
            print(f"Processing {rda.name}...")
            result = pyreadr.read_r(str(rda))
            series_name = rda.stem.replace('_series', '').lower()
            
            for name, frame in result.items():
                if isinstance(frame, pd.DataFrame):
                    frame = frame.copy()
                    # Normalize columns
                    frame.columns = [str(c).strip() for c in frame.columns]
                    frame['series'] = series_name
                    frames.append(frame)
        except Exception as e:
            print(f"Error reading {rda.name}: {e}")

    if not frames:
        print("No data frames extracted.")
        return

    # Combine all data
    df = pd.concat(frames, ignore_index=True, sort=False)
    
    # --- Preprocessing ---
    
    # Standardize Season/Year
    if 'schedule_season' not in df.columns:
        if 'year' in df.columns:
            df['schedule_season'] = pd.to_numeric(df['year'], errors='coerce')
        elif 'season' in df.columns:
            df['schedule_season'] = pd.to_numeric(df['season'], errors='coerce')
        else:
            # Fallback: try to infer from 'Season' (capitalized)
            if 'Season' in df.columns:
                df['schedule_season'] = pd.to_numeric(df['Season'], errors='coerce')
            else:
                # Last resort: create empty column
                df['schedule_season'] = 0

    # Ensure numeric year for filtering
    df['year_num'] = pd.to_numeric(df['schedule_season'], errors='coerce').fillna(0).astype(int)

    # Standardize Team Name
    if 'team_name' not in df.columns:
        # Try to find a team column
        for col in ['Team', 'team', 'owner', 'Owner']:
            if col in df.columns:
                df['team_name'] = df[col]
                break
        else:
            df['team_name'] = 'Unknown'
            
    df['team_name'] = df['team_name'].fillna('Unknown').astype(str)

    # Standardize Driver
    if 'driver' not in df.columns:
        for col in ['Driver', 'driver_name']:
            if col in df.columns:
                df['driver'] = df[col]
                break
        else:
            df['driver'] = 'Unknown'
            
    df['driver'] = df['driver'].fillna('Unknown').astype(str)

    # --- Active Entities Logic (2024-2025) ---
    active_df = df[df['year_num'] >= 2024]
    
    # Categorize teams by series
    active_teams_by_series = {}
    for series in active_df['series'].unique():
        series_teams = active_df[active_df['series'] == series]['team_name'].unique().tolist()
        # Clean up
        series_teams = sorted([t for t in series_teams if t != 'Unknown'])
        active_teams_by_series[series] = series_teams
        
    # Also keep a master list of all active teams
    active_teams = sorted(active_df['team_name'].unique().tolist())
    active_drivers = sorted(active_df['driver'].unique().tolist())
    
    # Remove 'Unknown' if present
    if 'Unknown' in active_teams: active_teams.remove('Unknown')
    if 'Unknown' in active_drivers: active_drivers.remove('Unknown')

    # --- NEW: Driver Rosters by Series with Metadata ---
    active_drivers_by_series = {}
    
    for series in active_df['series'].unique():
        series_df = active_df[active_df['series'] == series]
        driver_roster = []
        
        for driver_name in series_df['driver'].unique():
            if driver_name == 'Unknown':
                continue
                
            driver_df = series_df[series_df['driver'] == driver_name]
            
            # Get most recent team and make
            latest_entry = driver_df.sort_values('year_num', ascending=False).iloc[0]
            team = latest_entry['team_name'] if 'team_name' in latest_entry else 'Unknown'
            make = latest_entry['Make'] if 'Make' in latest_entry else latest_entry.get('make', 'Unknown')
            
            # Count races by year
            races_2024 = len(driver_df[driver_df['year_num'] == 2024])
            races_2025 = len(driver_df[driver_df['year_num'] == 2025])
            total_races = len(driver_df)
            
            driver_roster.append({
                'name': str(driver_name),
                'team': str(team),
                'manufacturer': str(make),
                'races_2024': int(races_2024),
                'races_2025': int(races_2025),
                'total_races': int(total_races)
            })
        
        # Sort by total races descending (most active first)
        driver_roster.sort(key=lambda x: x['total_races'], reverse=True)
        active_drivers_by_series[series] = driver_roster

    print(f"Found {len(active_teams)} active teams and {len(active_drivers)} active drivers.")
    for series, drivers in active_drivers_by_series.items():
        print(f"  {series}: {len(drivers)} drivers")

    # --- Historical Data (2012+) ---
    # We keep data from 2012 onwards for the profile history
    history_df = df[df['year_num'] >= 2012].copy()
    
    # Clean up for JSON serialization
    # Replace NaN with None
    history_df = history_df.where(pd.notnull(history_df), None)
    
    # Convert to list of dicts
    records = history_df.to_dict(orient='records')
    
    # --- Output ---
    output_data = {
        "metadata": {
            "generated_at": str(pd.Timestamp.now()),
            "source_files": [f.name for f in rda_files]
        },
        "active_teams": active_teams,
        "active_teams_by_series": active_teams_by_series,
        "active_drivers": active_drivers,
        "active_drivers_by_series": active_drivers_by_series,
        "records": records
    }
    
    print(f"Writing to {output_file}...")
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2, default=str)
        
    print("Done!")

if __name__ == "__main__":
    generate_static_data()
