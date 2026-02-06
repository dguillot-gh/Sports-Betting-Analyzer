import sqlite3
import os

db_path = r'd:\repo\backend\data\sports_data.db'
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("PRAGMA table_info(nba_games)")
    columns = cursor.fetchall()
    print(f"Found {len(columns)} columns in nba_games:")
    for col in columns:
        print(f"{col[1]} ({col[2]})")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
