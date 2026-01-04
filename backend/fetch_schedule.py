"""
Fetch NFL schedules from nflverse.
Uses nflreadpy (preferred, actively maintained) or nfl_data_py (legacy fallback).
"""

import pandas as pd
import os

# Set output path
output_dir = "backend/data/nflverse"
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, "schedules.csv")

years = [2020, 2021, 2022, 2023, 2024, 2025]
print(f"Importing schedules for years {years}...")

try:
    # Try nflreadpy first (actively maintained)
    import nflreadpy as nfl
    print("Using nflreadpy...")
    df_polars = nfl.load_schedules(years)
    df = df_polars.to_pandas()  # nflreadpy returns Polars DataFrame
    print(f"Downloaded {len(df)} games via nflreadpy.")
    
except ImportError:
    print("nflreadpy not available, trying nfl_data_py...")
    import nfl_data_py as nfl
    df = nfl.import_schedules(years)
    print(f"Downloaded {len(df)} games via nfl_data_py.")
    
except Exception as e:
    print(f"Error with nflreadpy: {e}")
    try:
        import nfl_data_py as nfl
        df = nfl.import_schedules(years)
        print(f"Downloaded {len(df)} games via nfl_data_py.")
    except Exception as e2:
        print(f"Both packages failed: {e2}")
        exit(1)

# Save to CSV
df.to_csv(output_file, index=False)
print(f"Saved to {output_file}")
