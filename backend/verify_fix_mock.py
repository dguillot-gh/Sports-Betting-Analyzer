import asyncio
import sys
import os
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

# Ensure backend acts as root for imports
sys.path.insert(0, os.getcwd())

async def test_sensitivity_mock():
    try:
        from scripts.kyleskom_adapter import predict_with_kyleskom, get_kyleskom_predictor
        
        print("Loading models...")
        pred = get_kyleskom_predictor()
        # Mock the data fetch
        pred.fetch_data_from_nba_api = MagicMock(return_value=True)
        
        # Create mock dataframe with 30 teams and random stats
        # We need roughly 52 columns (stats) + TEAM_ID + TEAM_NAME
        columns = ['TEAM_ID', 'TEAM_NAME'] + [f'Stat_{i}' for i in range(52)] 
        # Actual main.py drops TEAM_ID/NAME and expects ~52 cols per team.
        # kyleskom_adapter takes whatever is there and concats.
        
        teams = ["Boston Celtics", "Denver Nuggets"]
        data = []
        for i, team in enumerate(teams):
            row = [i, team] + list(np.random.rand(52))
            data.append(row)
            
        pred.df = pd.DataFrame(data, columns=columns)
        print("Mock data injected.")
        
        # Force load models
        pred.load_models()
        
        home, away = "Boston Celtics", "Denver Nuggets"
        
        print(f"\n--- Sensitivity Test (Mock Data): {away} @ {home} ---")
        
        # Test 1: Very Low Total (Should be OVER)
        print("\nTest 1: Total = 200.0 (Expect OVER bias)")
        res1 = await predict_with_kyleskom(home, away, total=200.0)
        ou1 = res1.get('over_under', {})
        print(f"Pick: {ou1.get('pick')} ({ou1.get('confidence')}%)")
        print(f"Probs: Over={ou1.get('over_prob')}, Under={ou1.get('under_prob')}")
        
        # Test 2: Very High Total (Should be UNDER)
        print("\nTest 2: Total = 250.0 (Expect UNDER bias)")
        res2 = await predict_with_kyleskom(home, away, total=250.0)
        ou2 = res2.get('over_under', {})
        print(f"Pick: {ou2.get('pick')} ({ou2.get('confidence')}%)")
        print(f"Probs: Over={ou2.get('over_prob')}, Under={ou2.get('under_prob')}")
        
        # Validation
        p1_over = ou1.get('over_prob', 0)
        p2_over = ou2.get('over_prob', 0)
        
        print(f"\nComparison: Over Prob @ 200 ({p1_over}) vs Over Prob @ 250 ({p2_over})")
        
        if p1_over > p2_over:
             print("SUCCESS: Over probability decreases as total line increases.")
        else:
             print("FAILURE: Model is insensitive or biased wrong way.")
             
    except Exception as e:
        print(f"CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sensitivity_mock())
