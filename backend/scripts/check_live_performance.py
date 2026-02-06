
import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.nba_odds import get_todays_nba_odds
from scripts.nba_predictor import NBAPredictor

# Configure logging to be clean
logging.basicConfig(level=logging.ERROR) # Only show errors
logger = logging.getLogger(__name__)

async def check_performance():
    print("=" * 110)
    print(f"{'NBA LIVE PERFORMANCE CHECK':^110}")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^110}")
    print("=" * 110)
    
    # 1. Fetch live odds/scores
    try:
        data = get_todays_nba_odds()
        games = data.get("games", [])
    except Exception as e:
        print(f"Error fetching odds: {e}")
        return

    if not games:
        print("No NBA games found for today.")
        return

    predictor = NBAPredictor()
    
    results = []
    
    print(f"\n{'MATCHUP':<25} | {'STATUS':<12} | {'SCORE':<10} | {'TOTAL':<6} | {'PRED':<6} | {'LINE':<6} | {'EDGE':<6} | {'RESULT'}")
    print("-" * 110)

    for game in games:
        home = game['home_team']
        away = game['away_team']
        status = game['status']
        h_score = game.get('home_score')
        a_score = game.get('away_score')
        
        # Get line
        line = game.get('over_under', 220) # Default if missing
        
        # Get Prediction
        pred_res = await predictor.predict_game(home, away, over_under=line)
        pred_total = pred_res.get('predicted_total', 0)
        edge = pred_res.get('ou_edge', 0)
        pick = pred_res.get('ou_pick', 'N/A')
        
        score_str = f"{h_score}-{a_score}" if h_score is not None else "N/A"
        current_total = (h_score + a_score) if h_score is not None else 0
        
        # Determine if pick is currently "winning"
        # Since we use Sports Day logic, we compare current_total vs line
        # Note: If game is live, this is just a progress check
        outcome = ""
        if h_score is not None:
            is_over = current_total > line
            if status.lower() in ['final', 'ff']:
                if (pick == 'OVER' and is_over) or (pick == 'UNDER' and not is_over):
                    outcome = "✅ WIN"
                else:
                    outcome = "❌ LOSS"
            else:
                outcome = f"(LIVE: {current_total:.1f})"
        
        print(f"{away + ' @ ' + home:<25} | {status:<12} | {score_str:<10} | {current_total:<6.1f} | {pred_total:<6.1f} | {line:<6.1f} | {edge:<6.1f} | {outcome}")

    print("-" * 110)
    print("\nDIAGNOSTIC NOTES:")
    print("1. Predictions are based on simple PPG averages (Last 20 games).")
    print("2. The model currently treats all opponent defenses as '114.0' league average.")
    print("3. Check for games with large 'EDGE' values (> 10) - these might be due to missing defensive stats.")

if __name__ == "__main__":
    asyncio.run(check_performance())
