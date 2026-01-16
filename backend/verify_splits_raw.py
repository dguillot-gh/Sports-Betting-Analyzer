
import json
import os

model_path = r"c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\XGBoost_Models\XGBoost_50.1%_UO_md12_eta0p112_sub0p939_col0p687_cbl0p783_cbn0p635_mcw7_g1p606_mds4_mb823_l0p984_a0p281_nb829.json"

with open(model_path, 'r') as f:
    model = json.load(f)

trees = model['learner']['gradient_booster']['model']['trees']

print(f"Total Trees: {len(trees)}")

for i in range(min(5, len(trees))):
    print(f"\n--- Tree {i} ---")
    tree = trees[i]
    indices = tree.get('split_indices', [])
    conditions = tree.get('split_conditions', [])
    for j in range(len(indices)):
        if indices[j] >= 104:
            print(f"  Split on f{indices[j]} at value {conditions[j]}")
