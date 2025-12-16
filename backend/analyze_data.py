import pandas as pd
from pathlib import Path

data_dir = Path('data/nascar')
csv_path = data_dir / 'cup_enhanced.csv'

if csv_path.exists():
    print(f"Reading {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Columns: {df.columns.tolist()}")
    
    if 'year' in df.columns:
        print(f"Years present: {sorted(df['year'].unique())}")
        print(f"Total rows: {len(df)}")
        
        # Check for specific teams
        teams_to_check = ["Hendrick Motorsports", "Joe Gibbs Racing", "Spire Motorsports", "Front Row Motorsports"]
        if 'team_name' in df.columns:
            for team in teams_to_check:
                team_rows = df[df['team_name'] == team]
                print(f"Team '{team}': {len(team_rows)} rows. Years: {sorted(team_rows['year'].unique()) if not team_rows.empty else 'None'}")
    else:
        print("No 'year' column found.")
else:
    print(f"{csv_path} does not exist.")
