import asyncpg
import asyncio
from src.config import DATABASE_URL
from datetime import datetime

async def check_times():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT sport, status, start_time 
            FROM import_logs 
            ORDER BY start_time DESC 
            LIMIT 10
        """)
        print(f"Current Server Time: {datetime.now()}")
        for r in rows:
            print(f"{r['sport']}: {r['status']} at {r['start_time']}")
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_times())
