import asyncio, asyncpg, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.config import DATABASE_URL

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    
    print("=== ALL indexes on entities table ===")
    rows = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='entities'"
    )
    for r in rows:
        print(f"  {r['indexname']}")
        print(f"    {r['indexdef']}")
    
    print("\n=== ALL constraints on entities table ===")
    rows = await conn.fetch("""
        SELECT conname, contype, pg_get_constraintdef(oid) as def
        FROM pg_constraint 
        WHERE conrelid = 'entities'::regclass
    """)
    for r in rows:
        print(f"  {r['conname']} ({r['contype']}): {r['def']}")
    
    print("\n=== Test: ON CONFLICT (sport_id, name, type) ===")
    try:
        sid = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        if sid:
            eid = await conn.fetchval("""
                INSERT INTO entities (sport_id, name, type)
                VALUES ($1, '__test_team__', 'team')
                ON CONFLICT (sport_id, name, type) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, sid)
            print(f"  PASS - entity_id={eid}")
            await conn.execute("DELETE FROM entities WHERE id=$1", eid)
            print("  Cleaned up")
        else:
            print("  No nba sport")
    except Exception as e:
        print(f"  FAIL: {e}")
    
    print("\n=== ALL indexes on results table ===")
    rows = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='results'"
    )
    for r in rows:
        print(f"  {r['indexname']}")
        print(f"    {r['indexdef']}")
    
    print("\n=== ALL constraints on results table ===")
    rows = await conn.fetch("""
        SELECT conname, contype, pg_get_constraintdef(oid) as def
        FROM pg_constraint
        WHERE conrelid = 'results'::regclass
    """)
    for r in rows:
        print(f"  {r['conname']} ({r['contype']}): {r['def']}")
    
    await conn.close()

asyncio.run(main())
