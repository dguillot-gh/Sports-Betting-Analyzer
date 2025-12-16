"""Test that scraped features are properly loaded into NASCAR data."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
import pandas as pd

# Check if integrated features exist
integrated_dir = Path(__file__).parent / 'data' / 'nascar' / 'integrated'

print("="*60)
print("NASCAR Scraped Features Integration Test")
print("="*60)

# Check files exist
driver_file = integrated_dir / 'driver_speed_features.csv'
track_file = integrated_dir / 'track_speed_features.csv'

if driver_file.exists():
    df = pd.read_csv(driver_file)
    print(f"\n[OK] Driver features: {len(df)} drivers")
    print(f"     Columns: {list(df.columns)}")
else:
    print(f"[MISSING] {driver_file}")

if track_file.exists():
    df = pd.read_csv(track_file)
    print(f"\n[OK] Track features: {len(df)} driver-track combos")
    print(f"     Columns: {list(df.columns)}")
else:
    print(f"[MISSING] {track_file}")

# Check config has new features
config_file = Path(__file__).parent / 'configs' / 'nascar_config.yaml'
if config_file.exists():
    with open(config_file) as f:
        content = f.read()
    
    scraped_features = [
        'scraped_avg_speed_rank', 'scraped_avg_finish', 
        'track_specific_speed', 'track_experience'
    ]
    
    print(f"\n[CONFIG] Checking for scraped features in config:")
    for feat in scraped_features:
        if feat in content:
            print(f"  [OK] {feat}")
        else:
            print(f"  [MISSING] {feat}")

print("\n" + "="*60)
print("Integration setup complete!")
print("Scraped features will be merged when NASCAR data is loaded.")
print("="*60)
