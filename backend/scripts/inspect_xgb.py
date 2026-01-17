import xgboost as xgb
import os
from pathlib import Path

# Fix path to match Docker environment
REFERENCE_REPO_PATH = Path('/app/scripts/nba_ml_reference')
if not REFERENCE_REPO_PATH.exists():
    REFERENCE_REPO_PATH = Path('c:/Users/dguil/source/repos/PythonMLService/backend/scripts/nba_ml_reference')

def inspect_model(kind):
    model_dir = REFERENCE_REPO_PATH / "Models" / "XGBoost_Models"
    candidates = list(model_dir.glob(f"*{kind}*.json"))
    if not candidates:
        print(f"No {kind} model found")
        return
    
    # Sort by mtime to get latest
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    model_path = candidates[0]
    print(f"\nInspecting {kind} model: {model_path.name}")
    
    bst = xgb.Booster()
    bst.load_model(str(model_path))
    
    # Try to get feature names
    names = bst.feature_names
    if names:
        print(f"Feature names (first 5): {names[:5]}")
        print(f"Feature names (last 5): {names[-5:]}")
        # Look for OU or Total Line
        for i, name in enumerate(names):
            if 'OU' in name or 'Total' in name:
                print(f"Found OU at index {i}: {name}")
    else:
        print("No feature names found in booster.")
        
    # Check num_features
    # We can't directly get num_features of a booster easily without a DMatrix
    # but we can try to see the size of a weight vector?
    # Actually, we can just use dump_model and check the max index.
    import re
    dump = bst.get_dump()
    max_idx = 0
    pattern = re.compile(r'\[f(\d+)')
    for tree in dump:
        indices = [int(m.group(1)) for m in pattern.finditer(tree)]
        if indices:
            max_idx = max(max_idx, max(indices))
    print(f"Max feature index found in split nodes: {max_idx} (Total features >= {max_idx + 1})")

if __name__ == "__main__":
    inspect_model("UO")
    inspect_model("ML")
