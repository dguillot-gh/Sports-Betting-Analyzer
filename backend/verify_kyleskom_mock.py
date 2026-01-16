import asyncio
import sys
import os
import logging
import json
import pandas as pd
import numpy as np
import sklearn
from sklearn.base import is_classifier

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.append(os.getcwd())

async def test_prediction():
    try:
        from scripts.kyleskom_adapter import predict_with_kyleskom, get_kyleskom_predictor, BoosterWrapper
        
        print("\n--- Sklearn Debug Info ---")
        print(f"Sklearn Version: {sklearn.__version__}")
        
        bw = BoosterWrapper()
        print(f"BoosterWrapper is_classifier: {is_classifier(bw)}")
        print(f"BoosterWrapper _estimator_type: {getattr(bw, '_estimator_type', 'N/A')}")
        
        if hasattr(bw, "__sklearn_tags__"):
             try:
                 tags = bw.__sklearn_tags__()
                 print(f"BoosterWrapper tags: {tags}")
                 if hasattr(tags, 'classifier'):
                     print(f"  tags.classifier: {tags.classifier}")
             except Exception as e:
                 print(f"Error calling __sklearn_tags__: {e}")
        
        print("\n--- Kyleskom Adapter DIRECT Verification (w/ Mock Data) ---")
        
        predictor = get_kyleskom_predictor()
        
        # 1. Manually populate mock data frame 
        columns = [
            'TEAM_ID', 'TEAM_NAME', 'GP', 'W', 'L', 'W_PCT', 'MIN', 'FGM', 'FGA', 'FG_PCT',
            'FG3M', 'FG3A', 'FG3_PCT', 'FTM', 'FTA', 'FT_PCT', 'OREB', 'DREB', 'REB',
            'AST', 'TOV', 'STL', 'BLK', 'BLKA', 'PF', 'PFD', 'PTS', 'PLUS_MINUS',
            'GP_RANK', 'W_RANK', 'L_RANK', 'W_PCT_RANK', 'MIN_RANK', 'FGM_RANK', 'FGA_RANK',
            'FG_PCT_RANK', 'FG3M_RANK', 'FG3A_RANK', 'FG3_PCT_RANK', 'FTM_RANK', 'FTA_RANK',
            'FT_PCT_RANK', 'OREB_RANK', 'DREB_RANK', 'REB_RANK', 'AST_RANK', 'TOV_RANK',
            'STL_RANK', 'BLK_RANK', 'BLKA_RANK', 'PF_RANK', 'PFD_RANK', 'PTS_RANK', 'PLUS_MINUS_RANK'
        ]
        
        dummy_row_home = [0, "Golden State Warriors"] + [100.0] * (len(columns) - 2)
        dummy_row_away = [1, "Sacramento Kings"] + [90.0] * (len(columns) - 2)
        
        predictor.df = pd.DataFrame([dummy_row_home, dummy_row_away], columns=columns)
        predictor._data_loaded = True
        
        # 2. Test live prediction
        home, away = "Golden State Warriors", "Sacramento Kings"
        print(f"Predicting: {away} @ {home}")
        
        res = await predictor.predict_game(home, away)
        
        if "error" in res:
            print(f"Prediction FAILED: {res['error']}")
            if "xgb_error" in res:
                 print(f"XGB Error: {res['xgb_error']}")
        else:
            print("Prediction SUCCESSFUL")
            print(f"XGB Home Win Prob: {res.get('home_win_probability')}")
            print(f"NN Home Win Prob: {res.get('nn_home_win_probability')}")

    except Exception as e:
        print(f"Test crashed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_prediction())
