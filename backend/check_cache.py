import asyncio
from src.database import get_pool

async def check():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, sport, home_team, away_team, game_date, fetched_at, expires_at FROM game_odds_cache WHERE sport = 'nba' ORDER BY fetched_at DESC")
        print(f"Total cached NBA games: {len(rows)}")
        for r in rows:
            print(f"  {r['id']} | {r['home_team']} vs {r['away_team']} | date={r['game_date']} | expires={r['expires_at']}")

asyncio.run(check())
