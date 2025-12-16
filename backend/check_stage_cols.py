import json
import pandas as pd

try:
    with open('data/nascar/nascar_data.json', 'r') as f:
        data = json.load(f)
        
    records = data.get('records', [])
    if not records:
        print("No records found.")
    else:
        # Create DataFrame from list of dicts, which handles missing keys gracefully
        df = pd.DataFrame(records)
        stage_cols = [c for c in df.columns if 'stage' in c.lower()]
        print(f"Stage columns found: {stage_cols}")
        
except Exception as e:
    print(f"Error: {e}")
