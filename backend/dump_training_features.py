import sqlite3
import pandas as pd
import os

db_path = r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite'

if os.path.exists(db_path):
    print('Opening database...')
    with sqlite3.connect(db_path) as con:
        # Get one row
        df = pd.read_sql_query('SELECT * FROM "dataset_2012-26" LIMIT 1', con)
        
        # Apply strict cleaning that happens in XGBoost_Model_UO.py
        # DROP_COLUMNS = ["index", "Score", "Home-Team-Win", "TEAM_NAME", "Date", "index.1", "TEAM_NAME.1", "Date.1", "OU-Cover"]
        drop_cols = ["index", "Score", "Home-Team-Win", "TEAM_NAME", "Date", "index.1", "TEAM_NAME.1", "Date.1", "OU-Cover"]
        
        final_df = df.drop(columns=drop_cols, errors='ignore')
        
        print(f'\nFinal Expected Features ({len(final_df.columns)}):')
        cols = list(final_df.columns)
        for i, c in enumerate(cols):
            print(f'{i}: {c}')
            
        # Check O/U position specifically
        if 'OU' in cols:
            print(f'\nOU Index: {cols.index("OU")}')
            
else:
    print('DB not found')
