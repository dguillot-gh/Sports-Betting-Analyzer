import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.getcwd())

from scripts.gemini_predictor import get_gemini_predictor

async def test_injury_insight():
    predictor = get_gemini_predictor()
    
    # Example: NBA game tonight (Lakers vs Suns - example)
    # Using a high-profile game to see if it finds injury news
    sport = "nba"
    home = "Los Angeles Lakers"
    away = "Phoenix Suns"
    stats = {
        "home": {"ppg": 117.5, "oppg": 115.0},
        "away": {"ppg": 118.2, "oppg": 114.5}
    }
    
    print(f"Requesting insight for {away} @ {home}...")
    insight = await predictor.get_insight(sport, home, away, stats)
    
    import json
    print(json.dumps(insight, indent=2))
    
    if "injury" in insight.get("rationale", "").lower() or "injury" in insight.get("key_factor", "").lower():
        print("\nSUCCESS: Injury data mentioned in rationale/key_factor.")
    else:
        print("\nNOTE: No injury data mentioned (might be no major injuries or search did not find them).")

if __name__ == "__main__":
    asyncio.run(test_injury_insight())
