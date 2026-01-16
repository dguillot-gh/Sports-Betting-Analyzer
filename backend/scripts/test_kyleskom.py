"""
Test script to verify kyleskom adapter feature counts match the pre-trained model
"""
import asyncio
import sys
sys.path.insert(0, r'c:\Users\dguil\source\repos\PythonMLService\backend')

async def test_adapter():
    from scripts.kyleskom_adapter import KyleskomPredictor
    
    predictor = KyleskomPredictor()
    
    # Load models
    if not predictor.load_models():
        print("ERROR: Could not load models")
        return
    
    print("[OK] Models loaded successfully")
    print(f"  ML model: {predictor.xgb_ml}")
    print(f"  O/U model: {predictor.xgb_ou}")
    
    # Fetch NBA data
    success = await predictor.fetch_data_from_nba_api()
    if not success:
        print("ERROR: Could not fetch NBA API data")
        return
    
    print(f"[OK] Fetched data for {len(predictor.df)} teams")
    print(f"  Columns per team: {len(predictor.df.columns)}")
    
    # Test prediction
    result = await predictor.predict_game(
        "Los Angeles Lakers",
        "Boston Celtics",
        total_line=225.0,
        home_ml=-150,
        away_ml=130
    )
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    
    print(f"\n=== Prediction Result ===")
    print(f"Home Win Prob: {result.get('home_win_probability')}")
    print(f"Away Win Prob: {result.get('away_win_probability')}")
    print(f"Predicted Winner: {result.get('predicted_winner')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"Features Used: {result.get('features_used')}")
    
    if result.get('over_under'):
        ou = result['over_under']
        print(f"\n=== O/U Prediction ===")
        print(f"Pick: {ou.get('pick')}")
        print(f"Total Line: {ou.get('total_line')}")
        print(f"Confidence: {ou.get('confidence')}")
    else:
        print("\n[WARNING] No O/U prediction returned")
    
    print(f"\nEV Home: {result.get('ev_home')}")
    print(f"Kelly Home: {result.get('kelly_home')}")

if __name__ == "__main__":
    asyncio.run(test_adapter())
