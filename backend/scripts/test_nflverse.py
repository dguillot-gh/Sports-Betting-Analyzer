"""
Test script to verify nflverse data fetching works correctly
"""
import asyncio
import sys
sys.path.insert(0, r'c:\Users\dguil\source\repos\PythonMLService\backend')

async def test_nflverse():
    from scripts.nflverse_adapter import NflversePredictor
    
    predictor = NflversePredictor()
    
    print("Testing nflverse data fetching...")
    
    # Fetch stats
    stats = await predictor.fetch_team_stats_from_nflverse()
    
    if not stats:
        print("ERROR: No stats returned from nflverse")
        return
    
    print(f"[OK] Fetched stats for {len(stats) // 2} teams")
    
    # Show sample team stats
    sample_teams = ['Kansas City Chiefs', 'Philadelphia Eagles', 'Buffalo Bills']
    
    for team in sample_teams:
        if team in stats:
            ts = stats[team]
            print(f"\n=== {team} ===")
            print(f"  PPG: {ts.get('ppg')}")
            print(f"  OPPG: {ts.get('oppg')}")
            print(f"  Win%: {ts.get('win_pct')}")
            print(f"  Off EPA: {ts.get('off_epa')}")
            print(f"  Def EPA: {ts.get('def_epa')}")
            print(f"  Pass EPA: {ts.get('pass_epa')}")
            print(f"  Rush EPA: {ts.get('rush_epa')}")
            print(f"  Success Rate: {ts.get('success_rate')}")
        else:
            print(f"\n{team} - NOT FOUND in stats")
            print(f"Available keys sample: {list(stats.keys())[:5]}")
    
    # Test prediction
    print("\n\n=== Testing Prediction ===")
    result = await predictor.predict_game(
        "Kansas City Chiefs",
        "Buffalo Bills",
        total_line=47.5,
        home_ml=-150,
        away_ml=130
    )
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    
    print(f"Home Win Prob: {result.get('home_win_probability')}")
    print(f"Predicted Winner: {result.get('predicted_winner')}")
    print(f"Model: {result.get('model')}")
    
    if result.get('over_under'):
        ou = result['over_under']
        print(f"O/U Pick: {ou.get('pick')} @ {ou.get('total_line')}")
        print(f"O/U Confidence: {ou.get('confidence')}")

if __name__ == "__main__":
    asyncio.run(test_nflverse())
