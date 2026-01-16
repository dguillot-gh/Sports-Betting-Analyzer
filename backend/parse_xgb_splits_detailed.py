
import json
import os

model_path = r"c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\XGBoost_Models\XGBoost_50.1%_UO_md12_eta0p112_sub0p939_col0p687_cbl0p783_cbn0p635_mcw7_g1p606_mds4_mb823_l0p984_a0p281_nb829.json"

with open(model_path, 'r') as f:
    model = json.load(f)

trees = model['learner']['gradient_booster']['model']['trees']

split_stats = {} 

for tree in trees:
    indices = tree.get('split_indices', [])
    conditions = tree.get('split_conditions', [])
    for idx, cond in zip(indices, conditions):
        if idx not in split_stats:
            split_stats[idx] = []
        split_stats[idx].append(cond)

print("=== Split Analysis (Indices 100-106) ===")
for i in range(100, 107):
    vals = split_stats.get(i, [])
    if vals:
        print(f"\nFeature {i}: {len(vals)} splits")
        unique_vals = sorted(list(set(vals)))
        print(f"  Range: {min(vals)} - {max(vals)}")
        print(f"  Examples: {unique_vals[:5]} ... {unique_vals[-5:]}")
        is_line = any(150 <= v <= 300 for v in vals)
        is_rest = all(0 <= v <= 14 for v in vals)
        print(f"  Likely: {'O/U Line' if is_line else 'Rest Days/Stats' if is_rest else 'Unknown'}")
    else:
        print(f"\nFeature {i}: No splits")
