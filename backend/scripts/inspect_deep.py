
import pandas as pd
from pathlib import Path
import numpy as np

def inspect_deep():
    base_dir = Path("c:/Users/dguil/source/repos/PythonMLService/backend/data/ncaab")
    path = base_dir / "ncaab_team_box_history.parquet"
    
    if not path.exists():
        print("Data not found")
        return

    df = pd.read_parquet(path)
    df['game_date'] = pd.to_datetime(df['game_date'])
    
    # Simulate _load_data calculations
    print("Calculating metrics...")
    df['is_win'] = (df['team_score'] > df['opponent_team_score']).astype(int)
    
    # expanding mean
    df['win_pct'] = df.groupby(['season', 'team_display_name'])['is_win'].expanding().mean().reset_index(level=[0,1], drop=True)
    
    print(f"Win Pct Dtype: {df['win_pct'].dtype}")
    
    # Check for stringified lists in ANY column
    print("Scanning entire dataframe for stringified lists...")
    for col in df.columns:
        if df[col].dtype == 'object':
            sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else ""
            if isinstance(sample, str) and (sample.startswith('[') or 'E-' in sample):
                print(f"MATCH FOUND in column '{col}': {sample}")
                # check count
                bad_count = df[col].astype(str).str.contains(r'\[.*\]', regex=True).sum()
                print(f" -> Count of bad rows: {bad_count}")

    # Check if 'win_pct' somehow became object in the original file
    # (The calculation above overrides it, so check BEFORE calculation if it exists?)
    # Reload to check raw
    df_raw = pd.read_parquet(path)
    if 'win_pct' in df_raw.columns:
        print(f"Raw win_pct dtype: {df_raw['win_pct'].dtype}")
        if df_raw['win_pct'].dtype == 'object':
            print(f"Raw win_pct sample: {df_raw['win_pct'].iloc[0]}")

if __name__ == "__main__":
    inspect_deep()
