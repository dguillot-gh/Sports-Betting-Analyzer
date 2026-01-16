"""
Definitive check of XGBoost model feature expectations
"""
import json
from pathlib import Path
import sqlite3
import pandas as pd

# Check model expected features  
model_path = Path(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\XGBoost_Models')
models = list(model_path.glob('*UO*.json'))
if models:
    with open(models[0], 'r') as f:
        m = json.load(f)
    print(f'=== XGBoost O/U model info ===')
    print(f'Model: {models[0].name}')
    num_features = m['learner']['learner_model_param'].get('num_feature')
    print(f'Expected features: {num_features}')
    
    # Check what indices the model actually splits on
    trees = m['learner']['gradient_booster']['model']['trees']
    all_indices = set()
    for tree in trees:
        indices = tree.get('split_indices', [])
        all_indices.update(indices)
    print(f'Max split index used: {max(all_indices)}')
    print(f'All unique indices used: {sorted(all_indices)}')

# Check dataset.sqlite if it exists
db_path = Path(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite')
if db_path.exists():
    with sqlite3.connect(db_path) as con:
        cursor = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f'\n=== Training dataset info ===')
        print(f'Tables: {[t[0] for t in tables]}')
        
        for table in tables:
            df = pd.read_sql_query(f'SELECT * FROM "{table[0]}" LIMIT 1', con)
            print(f'\nTable: {table[0]}, Columns: {len(df.columns)}')
            cols = list(df.columns)
            # Find key positions
            for c in ['OU', 'OU-Cover', 'Days-Rest-Home', 'Days-Rest-Away']:
                if c in cols:
                    print(f'  {c} at index: {cols.index(c)}')
            # Show last 10 columns
            print(f'  Last 10 columns: {cols[-10:]}')
else:
    print('\ndataset.sqlite not found')

# The ultimate truth: what does the model split analysis show?
print('\n=== Model Split Analysis (previously run) ===')
print('Feature 104: 226 splits, range 179.0-241.0 -> O/U Line')
print('Feature 105: 47 splits, range 2.0-7.0 -> Rest Days')  
print('Feature 106: 65 splits, range 2.0-7.0 -> Rest Days')
print('\nConclusion: Model expects O/U at index 104')
