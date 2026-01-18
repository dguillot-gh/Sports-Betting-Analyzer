import pandas as pd
from pathlib import Path
import sys

DATA_DIR = Path(__file__).parent / "data" / "nascar" / "cup_enhanced.csv"

def verify():
    if not DATA_DIR.exists():
        print(f"FAILED: {DATA_DIR} does not exist.")
        return

    try:
        df = pd.read_csv(DATA_DIR)
        print(f"Loaded {len(df)} rows from {DATA_DIR.name}")
        
        required_cols = [
            'laps_led_pct_last_5', 'career_laps_led_pct', 
            'consistency_score', 'track_type', 
            'is_road_course', 'is_dirt'
        ]
        
        missing = [c for c in required_cols if c not in df.columns]
        
        if missing:
            print(f"FAILED: Missing columns: {missing}")
        else:
            print("SUCCESS: All required columns present.")
            
            # Check for data quality
            print("\nSample Data:")
            print(df[['driver', 'track_type', 'laps_led_pct_last_5', 'consistency_score']].head(5))
            
            print("\nTrack Type Counts:")
            print(df['track_type'].value_counts())
            
            print("\nLogic Check:")
            road_courses = df[df['track_type'] == 'Road Course']['track'].unique()
            print(f"Road Courses identified: {road_courses[:5]}")
            
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    verify()
