
import logging
import sys
from ncaab_predictor import NCAABPredictor

# Set logging to see warnings/errors
logging.basicConfig(level=logging.INFO)

def test():
    print("Initializing Predictor...")
    predictor = NCAABPredictor()
    
    # Test valid matchup
    print("\n--- Testing Duke vs North Carolina ---")
    res = predictor.predict_game("Duke", "North Carolina")
    print(res)
    
    if 'xgb_available' in res:
        print(f"V1 Model Available: {res['xgb_available']}")
    else:
        print("V1 Model NOT available (Expected if file corrupted/legacy)")
        
    if 'v2_available' in res and res['v2_available']:
        print("V2 Model Available: Yes")
        if 'v2_factors' in res:
            print("V2 Factors (SHAP) found:")
            for f in res['v2_factors'][:3]:
                print(f" - {f['label']}: {f['impact']}")
        else:
            print("V2 Factors NOT found (Check SHAP logic)")
    else:
        print("V2 Model NOT available")

if __name__ == "__main__":
    test()
