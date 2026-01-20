
import pandas as pd
import numpy as np
import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_data():
    SCRIPT_DIR = Path(__file__).parent.absolute()
    BACKEND_ROOT = SCRIPT_DIR.parent
    
    possible_paths = [
        BACKEND_ROOT / "data" / "ncaab",
        Path.cwd() / "data" / "ncaab",
        Path.cwd() / "backend" / "data" / "ncaab",
        Path("/app/data/ncaab")
    ]
    
    DATA_DIR = None
    for p in possible_paths:
        if p.exists():
            DATA_DIR = p
            break
    
    if not DATA_DIR:
        print("Data directory not found.")
        return

    box_path = DATA_DIR / "ncaab_team_box_history.parquet"
    if box_path.exists():
        df = pd.read_parquet(box_path)
        print(f"Loaded {len(df)} rows.")
        
        for col in df.columns:
            # Check for corruption markers in ANY row
            try:
                # Optimized check: first check if it's object, then search
                if df[col].dtype == 'object':
                    has_bracket = df[col].astype(str).str.contains(r'\[|\]', regex=True)
                    if has_bracket.any():
                        bad_rows = df[has_bracket]
                        print(f"Column '{col}' HAS CORRUPTION! Total bad rows: {len(bad_rows)}")
                        print(f"Sample bad values: {bad_rows[col].head(5).tolist()}")
                else:
                    # Even if it's numeric, check if some values are strings?
                    # (rare in parquet but possible if mixed)
                    pass
            except Exception as e:
                print(f"Error checking column {col}: {e}")
                
        # Targeted search for the specific value from the logs: [6.502445E-1]
        target_pat = "6.502445E-1"
        for col in df.columns:
            try:
                found = df[df[col].astype(str).str.contains(target_pat)]
                if not found.empty:
                    print(f"Value '{target_pat}' FOUND in column '{col}'!")
                    print(f"Raw value: {found[col].head(1).iloc[0]}")
            except: pass

def test_cleaning_logic():
    # Simulate the data we saw in logs
    corrupted_val = "[4.9455655E-1]"
    print(f"\nTesting cleaning for: {corrupted_val}")
    
    import re
    cleaned = re.sub(r'[\[\]\'\"]', '', corrupted_val)
    print(f"Regex cleaned: {cleaned}")
    try:
        val = float(cleaned)
        print(f"Float conversion: {val}")
    except Exception as e:
        print(f"Float conversion failed: {e}")

if __name__ == "__main__":
    test_cleaning_logic()
    debug_data()
