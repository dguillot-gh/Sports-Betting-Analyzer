import asyncio
import asyncpg
import json

async def test():
    conn = await asyncpg.connect('postgresql://user:password@localhost:5432/sports_betting')
    sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
    if sport_id:
        count = await conn.fetchval("SELECT count(*) FROM results WHERE sport_id=$1", sport_id)
        series_counts = await conn.fetch("SELECT series, count(*) FROM results WHERE sport_id=$1 GROUP BY series", sport_id)
        season_counts = await conn.fetch("SELECT season, count(*) FROM results WHERE sport_id=$1 GROUP BY season", sport_id)
        print("Total NASCAR results:", count)
        print("By series:", series_counts)
        print("By season:", season_counts)
        
        # sample 1 row
        sample = await conn.fetchrow("SELECT series, season, track, metadata FROM results WHERE sport_id=$1 LIMIT 1", sport_id)
        print("Sample:", sample)
    else:
        print("NASCAR sport not found")
        
    await conn.close()

asyncio.run(test())
