import asyncio
import sys
import os
import logging
import json

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.append(os.getcwd())

async def test_prediction():
    try:
        from scripts.kyleskom_adapter import predict_with_kyleskom, get_kyleskom_predictor
        
        print("\n--- Kyleskom Adapter Verification ---")
        
        # Test team name normalization
        predictor = get_kyleskom_predictor()
        from scripts.kyleskom_adapter import normalize_team_name
        print(f"Normalizing 'LA Clippers' -> {normalize_team_name('LA Clippers')}")
        print(f"Normalizing 'Lakers' -> {normalize_team_name('Lakers')}")
        
        # Test live prediction
        # Use teams that should be in the current season
        home, away = "Golden State Warriors", "Sacramento Kings"
        print(f"\nPredicting: {away} @ {home}")
        
        res = await predict_with_kyleskom(home, away)
        
        if "error" in res:
            print(f"Prediction FAILED: {res['error']}")
            if "xgb_error" in res:
                print(f"XGB Error: {res['xgb_error']}")
            if "nn_error" in res:
                print(f"NN Error: {res['nn_error']}")
        else:
            print("Prediction SUCCESSFUL")
            print(json.dumps(res, indent=2))
            
            # Check for XGB and NN win probs
            xgb_prob = res.get('home_win_probability')
            nn_prob = res.get('nn_home_win_probability')
            
            print(f"\nXGB Home Win Prob: {xgb_prob}")
            print(f"NN Home Win Prob: {nn_prob}")
            
            if xgb_prob == 0.5 and res.get('xgb_error'):
                 print("WARNING: XGB fell back to 0.5 due to error")
            if nn_prob is None:
                 print("WARNING: NN Probability is MISSING")

    except Exception as e:
        print(f"Test crashed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_prediction())
