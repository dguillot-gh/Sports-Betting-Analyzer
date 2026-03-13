import xgboost as xgb
import os
from pathlib import Path

def verify():
    print(f"XGBoost version: {xgb.__version__}")
    model_dir = Path("/app/scripts/nba_ml_reference/Models/XGBoost_Models")
    models = list(model_dir.glob("*.json"))
    
    if not models:
        print(f"Error: No models found in {model_dir}")
        return False
        
    print(f"Found {len(models)} models.")
    test_model = models[0]
    print(f"Attempting to load: {test_model.name}")
    
    try:
        booster = xgb.Booster()
        booster.load_model(str(test_model))
        print("Successfully loaded model!")
        return True
    except Exception as e:
        print(f"Failed to load model: {e}")
        return False

if __name__ == "__main__":
    success = verify()
    exit(0 if success else 1)
