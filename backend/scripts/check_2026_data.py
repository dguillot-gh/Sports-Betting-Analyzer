
import asyncio
import asyncpg
from src.config import DATABASE_URL

async def check_2026_data():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Check NFL
        nfl_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nfl'")
        nfl_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nfl_id)
        print(f"NFL 2026 Results: {nfl_2026}")
        
        # Check NBA
        nba_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        nba_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nba_id)
        print(f"NBA 2026 Results: {nba_2026}")
        
        # Check NASCAR (for completeness)
        nascar_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        nascar_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nascar_id)
        print(f"NASCAR 2026 Results: {nascar_2026}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_2026_data())
