
import json
import os

model_path = r"c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\XGBoost_Models\XGBoost_50.1%_UO_md12_eta0p112_sub0p939_col0p687_cbl0p783_cbn0p635_mcw7_g1p606_mds4_mb823_l0p984_a0p281_nb829.json"

with open(model_path, 'r') as f:
    model = json.load(f)

trees = model['learner']['gradient_booster']['model']['trees']

split_stats = {} # feature_idx -> [split_values]

for tree in trees:
    indices = tree.get('split_indices', [])
    conditions = tree.get('split_conditions', [])
    for idx, cond in zip(indices, conditions):
        if idx not in split_stats:
            split_stats[idx] = []
        split_stats[idx].append(cond)

print("=== Search for Rest Days / O/U Line Splits ===")
for i in [104, 105, 106]:
    vals = split_stats.get(i, [])
    if vals:
        print(f"\nFeature {i}: {len(vals)} splits")
        # Show unique sorted values
        unique_vals = sorted(list(set(vals)))
        print(f"  Unique split values (Top 10): {unique_vals[:10]} ... {unique_vals[-5:]}")
        # Identify if it looks like Rest Days (0-10) or O/U Line (200-250)
        is_rest = any(0 <= v <= 10 for v in vals) and all(v < 30 for v in vals)
        is_line = any(150 <= v <= 300 for v in vals)
        print(f"  Likely: {'Rest Days' if is_rest else 'O/U Line' if is_line else 'Unknown'}")
    else:
        print(f"\nFeature {i}: No splits found.")
