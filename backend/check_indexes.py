import asyncio, asyncpg, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.config import DATABASE_URL

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    print("=== All content_hash indexes ===")
    for table in ['results', 'entities', 'stats']:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename=$1 AND indexdef LIKE '%content_hash%'",
            table
        )
        for r in rows:
            is_partial = "WHERE" in r['indexdef']
            flag = " *** PARTIAL (BAD) ***" if is_partial else " OK"
            print(f"  [{table}] {r['indexname']}{flag}")
            print(f"    {r['indexdef']}")
    
    print("\n=== Quick ON CONFLICT test on each table ===")
    # Test results
    try:
        sid = await conn.fetchval("SELECT id FROM sports LIMIT 1")
        await conn.execute(
            "INSERT INTO results (sport_id, season, series, metadata, content_hash) "
            "VALUES ($1, 9999, 'test', '{}', '__idx_test_r__') "
            "ON CONFLICT (content_hash) DO UPDATE SET metadata = EXCLUDED.metadata",
            sid
        )
        await conn.execute("DELETE FROM results WHERE content_hash = '__idx_test_r__'")
        print("  results: PASS")
    except Exception as e:
        print(f"  results: FAIL - {e}")

    # Test entities
    try:
        sid = await conn.fetchval("SELECT id FROM sports LIMIT 1")
        await conn.execute(
            "INSERT INTO entities (sport_id, name, type, content_hash) "
            "VALUES ($1, '__test__', 'team', '__idx_test_e__') "
            "ON CONFLICT (content_hash) DO UPDATE SET name = EXCLUDED.name",
            sid
        )
        await conn.execute("DELETE FROM entities WHERE content_hash = '__idx_test_e__'")
        print("  entities: PASS")
    except Exception as e:
        print(f"  entities: FAIL - {e}")

    # Test stats
    try:
        await conn.execute(
            "INSERT INTO stats (entity_id, season, stat_type, stats, content_hash) "
            "VALUES (1, 9999, 'test', '{}', '__idx_test_s__') "
            "ON CONFLICT (content_hash) DO UPDATE SET stats = EXCLUDED.stats"
        )
        await conn.execute("DELETE FROM stats WHERE content_hash = '__idx_test_s__'")
        print("  stats: PASS")
    except Exception as e:
        print(f"  stats: FAIL - {e}")

    await conn.close()

asyncio.run(main())
