import sys
import os
from pathlib import Path
import yaml

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.sports.nascar import NASCARSport

def verify():
    print("Verifying NASCAR data loading...")
    
    # Load config
    config_path = Path("configs/nascar_config.yaml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    # Initialize sport
    sport = NASCARSport(config)
    
    # Load data
    try:
        df = sport.load_data()
        print(f"✅ Successfully loaded data. Shape: {df.shape}")
        print(f"Columns: {len(df.columns)}")
        
        # Check for new features
        new_features = [
            'pole_position', 'career_wins', 'career_avg_finish', 
            'avg_finish_last_5', 'team_wins_this_season'
        ]
        
        missing = [f for f in new_features if f not in df.columns]
        
        if missing:
            print(f"❌ Missing expected new features: {missing}")
        else:
            print("✅ All checked new features are present.")
            
        # Check numeric types
        if pd.api.types.is_numeric_dtype(df['career_wins']):
             print("✅ 'career_wins' is numeric.")
        else:
             print(f"❌ 'career_wins' is NOT numeric. Type: {df['career_wins'].dtype}")
             
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import pandas as pd
    verify()
