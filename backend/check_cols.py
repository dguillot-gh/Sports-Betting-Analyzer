import sys
from pathlib import Path
import pandas as pd

# Add src to path
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / 'src'))

from sport_factory import SportFactory

def check_columns():
    print("Checking available columns...")
    
    sport, _ = SportFactory.get_sport('nascar', 'cup')
    df = sport.load_data()
    
    print(f"Columns: {list(df.columns)}")
    
    # Check for specific interesting columns
    interesting = ['laps_led', 'status', 'start', 'pole', 'dnf']
    for col in interesting:
        found = False
        for c in df.columns:
            if col in c.lower():
                print(f"Found potential match for '{col}': {c}")
                found = True
        if not found:
            print(f"Did not find exact match for '{col}'")

    # Check unique values for 'status' to identify DNFs
    if 'status' in df.columns:
        print("\nUnique Status values:")
        print(df['status'].unique())

if __name__ == "__main__":
    check_columns()
