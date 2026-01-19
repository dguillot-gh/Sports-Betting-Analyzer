
import pandas as pd
from pathlib import Path
import numpy as np

def inspect_box():
    base_dir = Path("c:/Users/dguil/source/repos/PythonMLService/backend/data/ncaab")
    path = base_dir / "ncaab_team_box_history.parquet"
    
    if not path.exists():
        print("Box history not found")
        return

    df = pd.read_parquet(path)
    print(f"Loaded {len(df)} rows")
    
    # Check for object columns that should be numeric
    print("\n--- Object Columns ---")
    obj_cols = df.select_dtypes(include=['object']).columns
    print(obj_cols)
    
    # Check specific suspiciously looking columns
    for col in df.columns:
        if df[col].dtype == 'object':
            # check if first value looks like a list string
            val = df[col].iloc[0]
            if isinstance(val, str) and (val.startswith('[') or 'E-' in val):
                print(f"SUSPICIOUS COLUMN: {col} -> {val}")

    # Also check existing v2 features if we can load them
    feat_path = "c:/Users/dguil/source/repos/PythonMLService/backend/models/ncaab_features_v2.joblib"
    import joblib
    try:
        feats = joblib.load(feat_path)
        print(f"\nModel expects {len(feats)} features")
        print(feats[:10])
    except:
        print("Could not load feature list")

if __name__ == "__main__":
    inspect_box()
