"""Investigate: are 'duplicates' actually different series entries?"""
import asyncio, asyncpg, os

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])

    # Check Allmendinger specifically
    rows = await conn.fetch(
        "SELECT id, sport_id, name, type, series, content_hash "
        "FROM entities WHERE name ILIKE '%allmendinger%' ORDER BY id"
    )
    print(f"=== A.J. Allmendinger entries ({len(rows)}) ===")
    for r in rows:
        print(f"  id={r['id']} sport_id={r['sport_id']} type={r['type']} "
              f"series={r['series']} hash={r['content_hash']}")

    # Check a random sample of duplicates - do they have different series?
    print("\n=== Sample of 'duplicates' on (sport_id, name, type) ===")
    sample = await conn.fetch("""
        SELECT e.id, e.sport_id, e.name, e.type, e.series, e.content_hash
        FROM entities e
        JOIN (
            SELECT sport_id, name, type
            FROM entities GROUP BY sport_id, name, type
            HAVING COUNT(*) > 1
            LIMIT 5
        ) d ON e.sport_id = d.sport_id AND e.name = d.name AND e.type = d.type
        ORDER BY e.name, e.series, e.id
    """)
    current_name = None
    for r in sample:
        if r['name'] != current_name:
            current_name = r['name']
            print(f"\n  {r['name']}:")
        print(f"    id={r['id']} series={r['series']} hash={r['content_hash']}")

    # Count: how many have DIFFERENT series vs truly identical?
    diff_series = await conn.fetchval("""
        SELECT COUNT(*) FROM (
            SELECT sport_id, name, type
            FROM entities GROUP BY sport_id, name, type
            HAVING COUNT(*) > 1
              AND COUNT(DISTINCT COALESCE(series, '')) > 1
        ) t
    """)
    same_series = await conn.fetchval("""
        SELECT COUNT(*) FROM (
            SELECT sport_id, name, type
            FROM entities GROUP BY sport_id, name, type
            HAVING COUNT(*) > 1
              AND COUNT(DISTINCT COALESCE(series, '')) = 1
        ) t
    """)
    print(f"\n=== Summary ===")
    print(f"Groups with DIFFERENT series (legitimate): {diff_series}")
    print(f"Groups with SAME series (true duplicates): {same_series}")

    await conn.close()

asyncio.run(main())
