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
df = pd.read_sql_query(f'SELECT * FROM "{target_table}" LIMIT 1', conn)
cols = list(df.columns)
print(f"Total Columns: {len(cols)}")
for i, c in enumerate(cols):
    print(f"{i}: {c}")

conn.close()
