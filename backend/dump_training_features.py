import pandas as pd
import sqlite3
from pathlib import Path

def dump_train_cols():
    print("--- DUMPING TRAINING COLS (SQLITE) ---")
    db_path = Path(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite')
    
    if db_path.exists():
        with sqlite3.connect(db_path) as con:
            print(f"Connected to {db_path.name}")
            # Get table name
            cursor = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            if not tables:
                print("No tables found.")
                return
            
            # Use the latest table usually?
            # check_model_features used filtered logic, but let's just grab the first one that looks like dataset
            # User output earlier showed 'dataset_2012-24_new' and 'dataset_2012-26'
            # We want 'dataset_2012-26' if available.
            table_name = tables[0][0]
            for t in tables:
                if '2012-26' in t[0]:
                    table_name = t[0]
                    break
            
            print(f"Reading table: {table_name}")
            df = pd.read_sql_query(f'SELECT * FROM "{table_name}" LIMIT 1', con)
            
            cols = list(df.columns)
            
            # Filter targets to match inputs
            # The model drops: Score, Home-Team-Win, OU, OU-Cover, Date
            # And usually keeps Rest Days?
            # Wait. Logic in Create_Games puts Rest Days at end?
            # check_model_features said Rest Days are 114, 115.
            # But Feature 105, 106.
            # This implies 115 cols total.
            # 115 - 5 targets (Score, Win, OU, Cover, Date) = 110?
            # 110 is close to 107.
            # Let's just dump the raw columns.
            
            print(f"Total Cols: {len(cols)}")
            print("--- TRAINING COLUMNS (First 20) ---")
            print(cols[:20])
            print("--- TRAINING COLUMNS (Middle 40-60) ---")
            print(cols[40:60])
            print("--- TRAINING COLUMNS (Contains RANK) ---")
            ranks = [c for c in cols if 'RANK' in c]
            print(ranks[:10])
            
            # Check for suffixes (Home vs Away)
            # Usually Home has no suffix, Away has .1?
            has_dot_one = [c for c in cols if '.1' in c]
            print(f"Columns with .1 suffix (Away?): {len(has_dot_one)}")
            if has_dot_one:
                print(f"Sample .1 cols: {has_dot_one[:5]}")

    else:
        print("dataset.sqlite not found.")

if __name__ == "__main__":
    dump_train_cols()
