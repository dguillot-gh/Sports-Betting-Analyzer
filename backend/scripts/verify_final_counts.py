
import asyncio
import asyncpg
from src.config import DATABASE_URL

async def verify_final_counts():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # NASCAR
        nascar_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        nascar_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nascar_id)
        
        # NBA
        nba_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        nba_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nba_id)
        
        # NFL
        nfl_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nfl'")
        nfl_2026 = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1 AND season = 2026", nfl_id)
        
        print(f"Final 2026 Counts:")
        print(f"  NASCAR: {nascar_2026}")
        print(f"  NBA:    {nba_2026}")
        print(f"  NFL:    {nfl_2026}")
        
        # NBA Season Breakdown
        print("\nNBA Breakdown:")
        seasons = await conn.fetch("SELECT season, COUNT(*) FROM results WHERE sport_id = $1 GROUP BY season ORDER BY season DESC", nba_id)
        for s in seasons:
            print(f"  {s['season']}: {s['count']}")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(verify_final_counts())
