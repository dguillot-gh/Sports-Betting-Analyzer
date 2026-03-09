
import asyncio
import asyncpg
import json
from src.config import DATABASE_URL

async def debug_nascar():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        print(f"NASCAR Sport ID: {sport_id}")
        
        # Check seasons available
        seasons = await conn.fetch("SELECT DISTINCT season FROM results WHERE sport_id = $1 ORDER BY season DESC", sport_id)
        print(f"Seasons in DB: {[s['season'] for s in seasons]}")
        
        # Check latest results for 2026 if any
        results_2026 = await conn.fetch("SELECT r.series, r.track, r.metadata FROM results r WHERE r.sport_id = $1 AND r.season = 2026 LIMIT 5", sport_id)
        print(f"2026 Results Count: {len(results_2026)}")
        for r in results_2026:
            print(f"  {r['series']} at {r['track']}: {r['metadata']}")
            
        # Check total count
        total = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1", sport_id)
        print(f"Total NASCAR results: {total}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(debug_nascar())
