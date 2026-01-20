
import sys
import logging
from pathlib import Path
import os
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
# Ensure the backend loggers are visible
logging.getLogger('scripts.ncaab_predictor').setLevel(logging.INFO)

from scripts.ncaab_predictor import NCAABPredictor

def test_shap():
    print("--- NCAAB SHAP Diagnostic ---")
    
    predictor = NCAABPredictor()
    print("Calling _load_data() explicitly...")
    predictor._load_data()
    
    if predictor.stats_df is None:
        print("ERROR: stats_df is STILL None after explicit _load_data().")
    elif predictor.stats_df.empty:
        print("ERROR: stats_df is Empty after explicit _load_data().")
    else:
        print(f"SUCCESS: Loaded {len(predictor.stats_df)} rows into stats_df.")
        
        teams = predictor.stats_df['team_display_name'].unique()
        print(f"Unique teams found: {len(teams)}")
        
        if len(teams) >= 2:
            home, away = teams[0], teams[1]
            print(f"Testing SHAP for {home} vs {away}...")
            
            try:
                # predict_v2 also triggers _load_models_v2
                res = predictor.predict_v2(home, away)
                if not res:
                    print("FAILED: predict_v2 returned empty dict")
                else:
                    print(f"V2 Available: {res.get('v2_available')}")
                    factors = res.get('v2_factors', [])
                    print(f"V2 Factors found: {len(factors)}")
                    for f in factors:
                        print(f"  - {f['label']}: {f['impact']:.4f}")
            except Exception as e:
                print(f"EXCEPTION during predict_v2: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("Not enough teams to test.")

if __name__ == "__main__":
    test_shap()
