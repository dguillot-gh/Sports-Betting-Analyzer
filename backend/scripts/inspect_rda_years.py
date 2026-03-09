
import pyreadr
import pandas as pd
from pathlib import Path

def inspect_rda(filepath):
    print(f"Inspecting {filepath}...")
    result = pyreadr.read_r(str(filepath))
    key = list(result.keys())[0]
    df = result[key]
    
    print(f"Total rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Try to find Season or Year column
    year_col = None
    for col in ['Season', 'Year', 'season', 'year']:
        if col in df.columns:
            year_col = col
            break
            
    if year_col:
        print(f"Unique values in {year_col}: {sorted(df[year_col].unique())[-5:]}")
        count_2025 = len(df[df[year_col] == 2025])
        count_2026 = len(df[df[year_col] == 2026])
        print(f"2025 entries: {count_2025}")
        print(f"2026 entries: {count_2026}")
    else:
        print("No year column found!")

if __name__ == "__main__":
    for p in Path("/app/data/nascar/raw").glob("*.rda"):
        inspect_rda(p)
        print("-" * 30)
