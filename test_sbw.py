import asyncio
import sys
import os
from dotenv import load_dotenv

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from services.sportsbookwire_service import get_sportsbookwire_service

async def test_sbw():
    load_dotenv('backend/.env')
    service = get_sportsbookwire_service()
    
    # Using one of the games we saw earlier
    home = "Houston Rockets"
    away = "Dallas Mavericks"
    
    print(f"Fetching picks for {away} @ {home}...")
    picks = await service.get_picks(home, away)
    
    import json
    print(json.dumps(picks, indent=2))
    
    if picks:
        print("\nSUCCESS: Picks retrieved and parsed.")
    else:
        print("\nFAILURE: No picks retrieved.")

if __name__ == "__main__":
    asyncio.run(test_sbw())
