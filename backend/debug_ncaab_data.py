
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
        print(f"\n--- Main Stats ({box_path.name}): {len(df)} rows ---")
        
        for col in df.columns:
            try:
                series_str = df[col].astype(str)
                # Check for brackets OR purely scientific notation strings like [4.94E-1] or just 4.94E-1 if in object col
                has_corruption = series_str.str.contains(r'\[|\]|E\-', regex=True)
                if has_corruption.any():
                    bad_rows = df[has_corruption]
                    print(f"Column '{col}' HAS CORRUPTION! Total bad rows: {len(bad_rows)}")
                    print(f"Sample values: {bad_rows[col].head(5).tolist()}")
            except: pass
                
    torvik_path = DATA_DIR / "torvik_ratings.parquet"
    if torvik_path.exists():
        tdf = pd.read_parquet(torvik_path)
        print(f"\n--- Torvik Stats ({torvik_path.name}): {len(tdf)} rows ---")
        for col in tdf.columns:
            try:
                series_str = tdf[col].astype(str)
                if series_str.str.contains(r'\[|\]', regex=True).any():
                    has_bracket = series_str.str.contains(r'\[|\]', regex=True)
                    bad_rows = tdf[has_bracket]
                    print(f"Column '{col}' HAS CORRUPTION! Total bad rows: {len(bad_rows)}")
                    print(f"Sample values: {bad_rows[col].head(5).tolist()}")
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
