import xgboost as xgb
import numpy as np
import pandas as pd
from pathlib import Path

# Fix path to match Docker environment
REFERENCE_REPO_PATH = Path('/app/scripts/nba_ml_reference')
if not REFERENCE_REPO_PATH.exists():
    REFERENCE_REPO_PATH = Path('c:/Users/dguil/source/repos/PythonMLService/backend/scripts/nba_ml_reference')

def test_ou_index():
    model_dir = REFERENCE_REPO_PATH / "Models" / "XGBoost_Models"
    candidates = list(model_dir.glob("*UO*.json"))
    if not candidates: return
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    model_path = candidates[0]
    
    bst = xgb.Booster()
    bst.load_model(str(model_path))
    
    # Mock data (104 stats + 2 rest days)
    # Let's say stats are mostly 0, rest days are 2
    data = np.zeros((1, 106))
    data[0, 104] = 2.0 # Rest Home
    data[0, 105] = 2.0 # Rest Away
    
    total_line = 230.0
    
    # Position 104 (Current)
    for l in [100.0, 150.0, 200.0, 220.0, 240.0, 300.0]:
        data_line = np.insert(data, 104, l, axis=1)
        prob = bst.predict(xgb.DMatrix(data_line))[0]
        print(f"Line {l}: Over Prob {prob[1]:.4f} (Under {prob[0]:.4f}, Other {prob[2]:.4f})")

if __name__ == "__main__":
    test_ou_index()
