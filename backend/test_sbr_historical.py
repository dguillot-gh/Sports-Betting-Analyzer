
import asyncio
from datetime import date, timedelta
from sbrscrape import Scoreboard

async def test_historical_odds():
    # Try yesterday
    target_date = date.today() - timedelta(days=2)
    print(f"Testing SBR for {target_date}...")
    
    try:
        sb = Scoreboard(sport="NBA", date=target_date)
        if not sb.games:
            print("No games found.")
            return
            
        print(f"Found {len(sb.games)} games.")
        for game in sb.games[:2]:
            print(f"\nGame: {game.get('away_team')} @ {game.get('home_team')}")
            print(f"Score: {game.get('away_score')} - {game.get('home_score')}")
            print(f"Total Odds: {game.get('total')}")
            print(f"Spread Odds: {game.get('away_spread')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_historical_odds())
