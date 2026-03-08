
import asyncio
import asyncpg
from src.config import DATABASE_URL

async def check_nba_seasons():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        nba_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        seasons = await conn.fetch("SELECT season, COUNT(*) FROM results WHERE sport_id = $1 GROUP BY season ORDER BY season DESC", nba_id)
        print("NBA Results by Season:")
        for s in seasons:
            print(f"  {s['season']}: {s['count']}")
            
        # Check some sample metadata for 2025 to see actual dates
        sample_2025 = await conn.fetch("SELECT metadata FROM results WHERE sport_id = $1 AND season = 2025 LIMIT 1", nba_id)
        if sample_2025:
             print(f"Sample 2025 Metadata: {sample_2025[0]['metadata']}")
             
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_nba_seasons())
