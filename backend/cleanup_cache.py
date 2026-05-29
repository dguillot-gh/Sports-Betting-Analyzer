import asyncio
from src.database import get_pool

async def cleanup():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Delete all expired cache entries (anything with expires_at in the past)
        result = await conn.execute("DELETE FROM game_odds_cache WHERE expires_at < NOW()")
        print(f"Deleted expired entries: {result}")
        
        # Verify what's left
        rows = await conn.fetch("SELECT id, home_team, away_team, game_date, expires_at FROM game_odds_cache WHERE sport = 'nba'")
        print(f"Remaining NBA cached games: {len(rows)}")
        for r in rows:
            print(f"  {r['id']} | {r['home_team']} vs {r['away_team']} | expires={r['expires_at']}")

asyncio.run(cleanup())
