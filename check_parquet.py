#!/usr/bin/env python3

import pandas as pd

df = pd.read_parquet('/app/data/nascar/raw/cup_series.parquet')
print(f'Total parquet shape: {df.shape}')

# Filter to 2026 season
df_2026 = df[df['Season'] == 2026].copy()
print(f'2026 data shape: {df_2026.shape}')

if df_2026.empty:
    print('No 2026 data found')
else:
    # Check team counts
    team_counts = df_2026['Team'].value_counts()
    print(f'Teams in 2026: {len(team_counts)}')
    print(f'Teams with 3+ races: {(team_counts >= 3).sum()}')
    
    if (team_counts >= 3).sum() > 0:
        print('Top teams by race count:')
        print(team_counts.head(10))
    else:
        print('No teams have 3+ races in 2026')
        print('Max races per team:', team_counts.max())
