#!/usr/bin/env python3

import sys
sys.path.append('/app/src')

from sport_factory import SportFactory

try:
    print("Testing NASCAR data loading via SportFactory...")
    sport, label = SportFactory.get_sport('nascar', 'cup')
    print(f"Sport loaded successfully with label: {label}")
    
    df = sport.load_data()
    print(f"Data loaded: {df.shape}")
    print(f"Columns: {list(df.columns)[:5]}...")
    
    if df.empty:
        print("ERROR: DataFrame is empty")
    else:
        # Check for season/year column
        year_col = None
        for col in ['year', 'season', 'Season', 'schedule_season']:
            if col in df.columns:
                year_col = col
                break
        
        print(f"Year column: {year_col}")
        
        if year_col:
            print(f"Year range: {df[year_col].min()} - {df[year_col].max()}")
            df_2026 = df[df[year_col] == 2026]
            print(f"2026 data: {df_2026.shape}")
            
            if 'Team' in df_2026.columns:
                teams = df_2026['Team'].nunique()
                print(f"Unique teams in 2026: {teams}")
                print(f"Sample teams: {df_2026['Team'].value_counts().head()}")
            else:
                print("No Team column found")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
