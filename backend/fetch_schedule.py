
import nfl_data_py as nfl
import pandas as pd
import os

# Set output path
output_dir = "backend/data/nflverse"
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, "schedules.csv")

print("Importing schedules via nfl_data_py...")
try:
    # Import schedules for all relevant years
    df = nfl.import_schedules(years=[2020, 2021, 2022, 2023, 2024, 2025])
    print(f"Downloaded {len(df)} games.")
    
    # Save to CSV
    df.to_csv(output_file, index=False)
    print(f"Saved to {output_file}")
    
except Exception as e:
    print(f"Error: {e}")
    # try nflreadpy import if nfl_data_py fails (sometimes naming confusion)
    try:
        import nflreadpy as nfl
        df = nfl.import_schedules(years=[2020, 2021, 2022, 2023, 2024, 2025])
        df.to_csv(output_file, index=False)
        print(f"Saved to {output_file} (via nflreadpy)")
    except Exception as e2:
        print(f"Error 2: {e2}")
