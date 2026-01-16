import xgboost as xgb
import os
import re
from pathlib import Path

MODELS_DIR = Path(r"c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\XGBoost_Models")

def get_uo_model():
    candidates = list(MODELS_DIR.glob(f"*UO*.json"))
    if not candidates: return None
    return candidates[0]

path = get_uo_model()
if path:
    bst = xgb.Booster()
    bst.load_model(str(path))
    dump = bst.get_dump()
    
    splits = []
    for tree in dump:
        # Look for [f106<VAL]
        matches = re.findall(r'\[f106<([\d\.]+)\]', tree)
        splits.extend([float(m) for m in matches])
    
    if splits:
        print(f"Found {len(splits)} splits on f106")
        print(f"Min split: {min(splits)}")
        print(f"Max split: {max(splits)}")
        print(f"Sample splits: {sorted(list(set(splits)))[:10]}")
    else:
        print("No splits found on f106 in the entire forest!")
