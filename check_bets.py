import asyncio
import asyncpg
import os

DATABASE_URL = "postgresql://sports_user:sportsbetting2024@localhost:5432/sports_betting"

async def check_bets():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT * FROM bets ORDER BY created_at DESC LIMIT 5")
        print(f"Found {len(rows)} bets in the database.")
        for row in rows:
            print(f"ID: {row['id']}, Created: {row['created_at']}, Description: {row['description']}, Stake: {row['stake']}")
        await conn.close()
    except Exception as e:
        print(f"Error checking bets: {e}")

if __name__ == "__main__":
    asyncio.run(check_bets())
