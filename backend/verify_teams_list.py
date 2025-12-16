import sys
from pathlib import Path
import pandas as pd

# Add src to path
sys.path.append(str(Path.cwd() / 'src'))

from sport_factory import SportFactory

def verify_teams():
    try:
        sport, label = SportFactory.get_sport('nascar', 'cup')
        
        # Inspect raw data columns
        print("\n--- Inspecting Raw Data ---")
        df = sport._load_raw_data()
        print(f"Columns: {list(df.columns)}")
        if 'series' in df.columns:
            print(f"Series values: {df['series'].unique()}")
        else:
            print("No 'series' column found.")
            
        teams = sport.get_teams()
        print(f"\nTotal Teams: {len(teams)}")
        
        missing = []
        expected = ["Hendrick Motorsports", "Joe Gibbs Racing", "Spire Motorsports", "Front Row Motorsports"]
        for exp in expected:
            if exp not in teams:
                missing.append(exp)
        
        if missing:
            print(f"\nERROR: The following expected teams are MISSING: {missing}")
        else:
            print("\nSUCCESS: All expected teams are present.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_teams()
