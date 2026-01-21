"""
One-time script to permanently fix corrupted base_score values in XGBoost model files.
This resolves the SHAP error: "could not convert string to float: '[6.502445E-1]'"

Run this script ONCE to fix the models:
    python scripts/fix_models.py

After running, the SHAP warnings should be resolved.
"""

import json
import os
import tempfile
from pathlib import Path
import xgboost as xgb
import joblib

def fix_model_file(model_path: Path) -> bool:
    """Fix a single XGBoost model file by re-saving with corrected base_score."""
    if not model_path.exists():
        print(f"  SKIP: {model_path.name} not found")
        return False
    
    try:
        # Load the model
        model = joblib.load(model_path)
        booster = model.get_booster()
        
        # Save to JSON temp file
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as tf:
            temp_json = tf.name
        
        booster.save_model(temp_json)
        
        with open(temp_json, 'r') as f:
            model_json = json.load(f)
        
        # Find and fix ALL bracketed values recursively
        def fix_bracket_values(obj, path=""):
            fixes = []
            if isinstance(obj, dict):
                for key, val in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    if isinstance(val, str) and val.startswith('[') and val.endswith(']'):
                        try:
                            fixed_val = float(val.strip('[] '))
                            obj[key] = str(fixed_val)
                            fixes.append(f"  {new_path}: {val} -> {fixed_val}")
                        except ValueError:
                            pass
                    elif isinstance(val, (dict, list)):
                        fixes.extend(fix_bracket_values(val, new_path))
            elif isinstance(obj, list):
                for i, val in enumerate(obj):
                    new_path = f"{path}[{i}]"
                    if isinstance(val, str) and val.startswith('[') and val.endswith(']'):
                        try:
                            fixed_val = float(val.strip('[] '))
                            obj[i] = str(fixed_val)
                            fixes.append(f"  {new_path}: {val} -> {fixed_val}")
                        except ValueError:
                            pass
                    elif isinstance(val, (dict, list)):
                        fixes.extend(fix_bracket_values(val, new_path))
            return fixes
        
        fixes = fix_bracket_values(model_json)
        
        if not fixes:
            print(f"  OK: {model_path.name} - no fixes needed")
            os.remove(temp_json)
            return True
        
        print(f"  FIXING: {model_path.name}")
        for fix in fixes:
            print(fix)
        
        # Write fixed JSON and reload into booster
        fixed_json = temp_json + "_fixed.json"
        with open(fixed_json, 'w') as f:
            json.dump(model_json, f)
        
        # Create a new clean booster and load the fixed model
        new_booster = xgb.Booster()
        new_booster.load_model(fixed_json)
        
        # Replace the internal booster in the sklearn wrapper
        model._Booster = new_booster
        
        # Also fix the base_score attribute if present
        if 'learner' in model_json and 'learner_model_param' in model_json['learner']:
            bs = model_json['learner']['learner_model_param'].get('base_score')
            if bs:
                try:
                    model.base_score = float(bs)
                except:
                    pass
        
        # Backup original and save fixed model
        backup_path = model_path.with_suffix('.joblib.bak')
        if not backup_path.exists():
            os.rename(model_path, backup_path)
            print(f"  Backed up original to {backup_path.name}")
        
        joblib.dump(model, model_path)
        print(f"  SAVED: {model_path.name}")
        
        # Cleanup
        os.remove(temp_json)
        os.remove(fixed_json)
        
        return True
        
    except Exception as e:
        print(f"  ERROR: {model_path.name} - {e}")
        return False


def main():
    print("=" * 60)
    print("XGBoost Model Base Score Fix Utility")
    print("=" * 60)
    
    # Find models directory
    script_dir = Path(__file__).parent.absolute()
    backend_dir = script_dir.parent
    models_dir = backend_dir / "models"
    
    if not models_dir.exists():
        models_dir = script_dir / "models"
    
    if not models_dir.exists():
        print(f"ERROR: Models directory not found at {models_dir}")
        return
    
    print(f"\nModels directory: {models_dir}")
    
    # Model files to fix
    model_files = [
        "ncaab_ml_v2.joblib",
        "ncaab_ou_v2.joblib", 
        "ncaab_xgb_v1.joblib",
    ]
    
    print("\nProcessing models...")
    for model_file in model_files:
        model_path = models_dir / model_file
        fix_model_file(model_path)
    
    print("\n" + "=" * 60)
    print("Done! Restart your service to use the fixed models.")
    print("=" * 60)


if __name__ == "__main__":
    main()
