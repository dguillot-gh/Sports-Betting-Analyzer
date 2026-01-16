import asyncio
import sys
import os

# Ensure backend acts as root for imports
sys.path.insert(0, os.getcwd())

async def test_sensitivity():
    try:
        from scripts.kyleskom_adapter import predict_with_kyleskom, get_kyleskom_predictor
        
        # Load up first
        print("Loading models...")
        pred = get_kyleskom_predictor()
        if not pred.load_models():
            print("Failed to load models")
            return
            
        print("Fetching data...")
        await pred.fetch_data_from_nba_api()
        
        home, away = "Boston Celtics", "Denver Nuggets"
        
        print(f"\n--- Sensitivity Test: {away} @ {home} ---")
        
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
        
        if ou1.get('pick') == 'OVER' and ou2.get('pick') == 'UNDER':
             print("\nSUCCESS: Model responds correctly to line changes!")
        elif ou1.get('over_prob') > ou2.get('over_prob'):
             print("\nPARTIAL SUCCESS: Over probability decreased as line increased.")
        else:
             print("\nFAILURE: Model not responding correctly to line changes.")

    except Exception as e:
        print(f"CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sensitivity())
