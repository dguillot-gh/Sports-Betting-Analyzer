
import asyncio
import asyncpg
from src.config import DATABASE_URL

async def check_2025_data():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Check NFL
        nfl_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nfl'")
        nfl_2025 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2025", nfl_id)
        print(f"NFL 2025 Results: {nfl_2025}")
        
        # Check NBA
        nba_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        nba_2025 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2025", nba_id)
        print(f"NBA 2025 Results: {nba_2025}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_2025_data())
