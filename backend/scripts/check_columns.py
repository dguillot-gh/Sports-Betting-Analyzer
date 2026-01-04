import sqlite3
import pandas as pd

con = sqlite3.connect(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite')
df = pd.read_sql_query('select * from "dataset_2012-24_new" limit 1', con)
con.close()

print('=== All columns in training dataset ===')
for i, col in enumerate(df.columns):
    print(f'{i}: {col}')
print(f'\nTotal columns: {len(df.columns)}')
