import pandas as pd
from pathlib import Path
import pyreadr

data_dir = Path('data/nascar')
csv_path = data_dir / 'cup_enhanced.csv'
rda_path = data_dir / 'raw' / 'cup_series.rda'

def get_teams_from_df(df, source_name):
    print(f"\n--- {source_name} ---")
    df.columns = [c.strip() for c in df.columns]
    
    # Normalize columns
    col_lower = {c.lower(): c for c in df.columns}
    
    team_col = 'team_name'
    if 'team_name' not in df.columns:
        if 'team' in col_lower:
            team_col = col_lower['team']
        elif 'Team' in df.columns:
            team_col = 'Team'
            
    year_col = 'year'
    if 'year' not in df.columns:
        if 'season' in col_lower:
            year_col = col_lower['season']
            
    print(f"Team Col: {team_col}, Year Col: {year_col}")
    
    if team_col in df.columns:
        teams = df[team_col].dropna().unique().tolist()
        print(f"Total Teams: {len(teams)}")
        
        # Check specific teams
        targets = ["Hendrick Motorsports", "Joe Gibbs Racing", "Spire Motorsports", "Front Row Motorsports", "JR Motorsports"]
        found = []
        for t in targets:
            if t in teams:
                found.append(t)
        print(f"Found Targets: {found}")
        
        # Check filtering
        if year_col in df.columns:
            df[year_col] = pd.to_numeric(df[year_col], errors='coerce')
            filtered_teams = df[df[year_col] < 2025][team_col].dropna().unique().tolist()
            print(f"Teams with year < 2025: {len(filtered_teams)}")
            
            found_filtered = []
            for t in targets:
                if t in filtered_teams:
                    found_filtered.append(t)
            print(f"Found Targets (Filtered): {found_filtered}")
            
        return set(teams)
    else:
        print("Team column not found.")
        return set()

# 1. CSV
if csv_path.exists():
    df_csv = pd.read_csv(csv_path)
    teams_csv = get_teams_from_df(df_csv, "CSV (cup_enhanced.csv)")
else:
    print("CSV not found.")
    teams_csv = set()

# 2. RDA
if rda_path.exists():
    try:
        result = pyreadr.read_r(str(rda_path))
        frames = [df for df in result.values() if isinstance(df, pd.DataFrame)]
        if frames:
            df_rda = pd.concat(frames, ignore_index=True, sort=False)
            teams_rda = get_teams_from_df(df_rda, "RDA (cup_series.rda)")
        else:
            print("No dataframes in RDA.")
            teams_rda = set()
    except Exception as e:
        print(f"Error reading RDA: {e}")
        teams_rda = set()
else:
    print("RDA not found.")
    teams_rda = set()

# Compare
print("\n--- Comparison ---")
only_in_csv = teams_csv - teams_rda
only_in_rda = teams_rda - teams_csv

print(f"Only in CSV: {len(only_in_csv)}")
print(f"Only in RDA: {len(only_in_rda)}")

if "Joe Gibbs Racing" in only_in_rda:
    print("CRITICAL: Joe Gibbs Racing is ONLY in RDA!")
if "Joe Gibbs Racing" in only_in_csv:
    print("INFO: Joe Gibbs Racing is in CSV.")
