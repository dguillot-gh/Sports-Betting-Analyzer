"""
NCAAB Prediction Engine Verification Test
Ensures all prediction engines are working correctly after integration changes.
"""
import sys
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.ncaab_predictor import NCAABPredictor, analyze_ncaab_matchup


def test_predictor():
    """Test the NCAABPredictor class directly."""
    print("=" * 60)
    print("NCAAB Predictor Engine Verification")
    print("=" * 60)
    
    predictor = NCAABPredictor()
    
    # Test teams (commonly named teams for data matching)
    home_team = "Duke Blue Devils"
    away_team = "North Carolina Tar Heels"
    
    print(f"\nTest Matchup: {home_team} vs {away_team}")
    print("-" * 60)
    
    # Run predict_game (main method)
    result = predictor.predict_game(home_team, away_team, spread=-3.5, over_under=145.5)
    
    # Validate required fields
    required_fields = ['predicted_winner', 'home_win_probability', 'predicted_margin', 'predicted_total']
    v2_fields = ['v2_available', 'v2_win_prob', 'v2_total', 'v2_winner', 'v2_factors', 'v2_radar']
    
    print("\n--- Simple Model (Heuristic) ---")
    for field in required_fields:
        value = result.get(field, "MISSING")
        status = "[OK]" if field in result else "[X]"
        print(f"  {status} {field}: {value}")
    
    print("\n--- XGBoost v2 Model ---")
    if result.get('v2_available'):
        for field in v2_fields:
            value = result.get(field, "MISSING")
            status = "[OK]" if field in result and value not in [None, [], {}] else "[!!]"
            # Truncate long values
            if isinstance(value, list) and len(value) > 2:
                value = f"[{len(value)} factors]"
            elif isinstance(value, dict) and len(value) > 2:
                value = f"{{homeRdr: {len(value.get('home', {}))}, awayRdr: {len(value.get('away', {}))}}}"
            print(f"  {status} {field}: {value}")
    else:
        print("  [!!] v2 Models not available (may need training)")
    
    print("\n--- O/U Analysis ---")
    ou_pick = result.get('ou_pick', 'N/A')
    v2_total = result.get('v2_total', 0)
    line = 145.5
    print(f"  v2_total: {v2_total:.1f} | Line: {line} | Pick: {ou_pick}")
    
    # Check for UNDER bias
    if v2_total > 0:
        diff = v2_total - line
        if abs(diff) > 10:
            print(f"  [!!] Large deviation from line: {diff:+.1f} points")
        else:
            print(f"  [OK] Reasonable deviation: {diff:+.1f} points")
    
    print("\n--- Torvik Data ---")
    if predictor.torvik_ratings is not None:
        print(f"  [OK] Torvik ratings loaded: {len(predictor.torvik_ratings)} teams")
    else:
        print("  [i] Torvik ratings not loaded (run fetch_torvik_data.R)")
        
    if predictor.torvik_stats is not None:
        print(f"  [OK] Torvik stats loaded: {len(predictor.torvik_stats)} teams")
    else:
        print("  [i] Torvik stats not loaded (run fetch_torvik_data.R)")

    
    print("\n" + "=" * 60)
    print("Verification Complete!")
    print("=" * 60)
    
    return result


async def test_async_matchup():
    """Test the async analyze_ncaab_matchup function."""
    print("\n--- Testing Async Matchup Analysis ---")
    
    result = await analyze_ncaab_matchup(
        home_team="Kansas Jayhawks",
        away_team="Kentucky Wildcats",
        spread=-2.0,
        over_under=148.0,
        home_ml=-130,
        away_ml=+110
    )
    
    print(f"Predicted Winner: {result.get('predicted_winner')}")
    print(f"Has Value: {result.get('has_value', False)}")
    print(f"Value Bets: {result.get('value_bets', [])}")
    
    return result


if __name__ == "__main__":
    # Run sync test
    test_predictor()
    
    # Run async test
    asyncio.run(test_async_matchup())
