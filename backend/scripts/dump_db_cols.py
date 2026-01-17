import sqlite3
import pandas as pd
from pathlib import Path

db_path = Path(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite')

if not db_path.exists():
    print(f"Error: {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cursor.fetchall()]
print(f"Tables: {tables}")

target_table = "dataset_2012-26"
if target_table in tables:
    df = pd.read_sql_query(f'SELECT * FROM "{target_table}" LIMIT 1', conn)
    cols = list(df.columns)
    print(f"\nTable: {target_table}")
    print(f"Total Columns: {len(cols)}")
    
    # Identify the "stat" columns
    # We suspect they start at GP (index 2) and go for 52 columns.
    stat_start_idx = cols.index('GP')
    stats_52 = cols[stat_start_idx : stat_start_idx + 52]
    
    print(f"\nStat columns (52 starting from GP):")
    print(stats_52)
    print(f"\nLast column in slice: {stats_52[-1]}")
    
    # Verify OU index
    if 'OU' in cols:
        print(f"\nOU index in full table: {cols.index('OU')}")
        # If we concatenate two sets of 52 stats, OU should be at 104.

conn.close()
