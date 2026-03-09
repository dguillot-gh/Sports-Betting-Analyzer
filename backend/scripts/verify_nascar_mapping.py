import asyncpg
import asyncio
import json

async def verify_nascar_2026():
    DATABASE_URL = "postgresql://postgres:postgres@db:5432/sports_ml"
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("""
            SELECT metadata FROM results 
            WHERE sport_id = (SELECT id FROM sports WHERE name = 'nascar') 
              AND season = 2026 
            LIMIT 1
        """)
        if row:
            meta = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
            print("--- NASCAR 2026 Sample Metadata ---")
            print(json.dumps(meta, indent=2))
            
            # Check for critical fields
            required = ['driver_name', 'finish', 'team', 'start']
            missing = [f for f in required if f not in meta]
            if not missing:
                print("\n✅ All critical UI fields found!")
            else:
                print(f"\n❌ Missing fields: {missing}")
        else:
            print("No 2026 NASCAR data found yet. Import might still be in progress.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(verify_nascar_2026())
