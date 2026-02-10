import asyncio
import asyncpg
import os

async def check():
    try:
        # Use verified DATABASE_URL from container
        conn = await asyncpg.connect('postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting')
        columns = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='bets'")
        print("COLUMNS:" + ",".join([c['column_name'] for c in columns]))
        
        # Check if table exists
        if not columns:
            print("ERROR: 'bets' table not found or no columns.")
            
        await conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(check())
