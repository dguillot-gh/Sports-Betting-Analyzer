#!/usr/bin/env python3

import pandas as pd
from pathlib import Path

# Check NASCAR parquet columns
data_dir = Path("/app/data/nascar/raw")

print("=== NASCAR Data Structure ===")

for parquet_file in data_dir.glob("*.parquet"):
    print(f"\n📁 {parquet_file.name}")
    try:
        df = pd.read_parquet(parquet_file)
        
        print(f"   Columns ({len(df.columns)}): {list(df.columns)}")
        
        # Check 2026 data sample
        df_2026 = df[df['Season'] == 2026]
        if not df_2026.empty:
            sample = df_2026.iloc[0]
            print(f"   2026 Sample Data:")
            for col in df.columns[:10]:  # First 10 columns
                val = sample[col]
                print(f"     {col}: {val}")
                
        print(f"   ✅ 2026 races: {len(df_2026)}")
            
    except Exception as e:
        print(f"   ❌ Error reading: {e}")
