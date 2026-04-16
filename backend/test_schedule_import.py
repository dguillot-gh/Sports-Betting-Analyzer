"""
Quick test: verify the ON CONFLICT index fix works for NBA schedule import.
Run from backend/:  python test_schedule_import.py
"""
import asyncio
import sys
import os
from pathlib import Path

# Make imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

import asyncpg
from src.config import DATABASE_URL


async def main():
    print(f"Connecting to: {DATABASE_URL[:40]}...")
    conn = await asyncpg.connect(DATABASE_URL)

    # ── Step 1: Check current index state ──
    print("\n── Current indexes on results.content_hash ──")
    rows = await conn.fetch("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'results' AND indexdef LIKE '%content_hash%'
    """)
    for r in rows:
        print(f"  {r['indexname']}: {r['indexdef']}")
    if not rows:
        print("  (none found)")

    # ── Step 2: Run ensure_schema (same logic as nba_importer) ──
    print("\n── Running ensure_schema fix ──")
    stmts = [
        "ALTER TABLE results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "DROP INDEX IF EXISTS idx_results_hash",
        "DROP INDEX IF EXISTS idx_stats_hash",
        "DROP INDEX IF EXISTS idx_entities_hash",
    ]
    for s in stmts:
        try:
            await conn.execute(s)
            print(f"  OK: {s[:60]}")
        except Exception as e:
            print(f"  WARN: {s[:60]} -> {e}")

    # Dedup before creating unique index
    print("\n── Deduplicating content_hash ──")
    try:
        deleted = await conn.execute("""
            DELETE FROM results a USING results b
            WHERE a.id < b.id AND a.content_hash IS NOT NULL
              AND a.content_hash = b.content_hash
        """)
        print(f"  Dedup result: {deleted}")
    except Exception as e:
        print(f"  Dedup error: {e}")

    # Create non-partial unique index
    print("\n── Creating non-partial unique index ──")
    try:
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_results_content_hash ON results(content_hash)"
        )
        print("  OK: idx_results_content_hash created")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── Step 3: Verify new index state ──
    print("\n── Updated indexes on results.content_hash ──")
    rows = await conn.fetch("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'results' AND indexdef LIKE '%content_hash%'
    """)
    for r in rows:
        print(f"  {r['indexname']}: {r['indexdef']}")

    # ── Step 4: Test a dummy ON CONFLICT insert ──
    print("\n── Testing ON CONFLICT (content_hash) upsert ──")
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        if not sport_id:
            print("  No 'nba' sport found — skipping upsert test")
        else:
            await conn.execute("""
                INSERT INTO results (sport_id, season, series, metadata, content_hash)
                VALUES ($1, 9999, 'test', '{}', '__test_hash_deleteme__')
                ON CONFLICT (content_hash)
                DO UPDATE SET metadata = EXCLUDED.metadata
            """, sport_id)
            print("  OK: ON CONFLICT upsert succeeded!")
            # Clean up
            await conn.execute("DELETE FROM results WHERE content_hash = '__test_hash_deleteme__'")
            print("  Cleaned up test row")
    except Exception as e:
        print(f"  FAILED: {e}")

    # ── Step 5: Count existing schedule rows ──
    print("\n── Current NBA schedule data in results ──")
    count = await conn.fetchval("""
        SELECT COUNT(*) FROM results r
        JOIN sports s ON r.sport_id = s.id
        WHERE s.name = 'nba'
          AND r.home_entity_id IS NOT NULL
          AND r.away_entity_id IS NOT NULL
          AND r.game_date IS NOT NULL
    """)
    print(f"  Games with proper home/away columns: {count}")

    total = await conn.fetchval("""
        SELECT COUNT(*) FROM results r
        JOIN sports s ON r.sport_id = s.id
        WHERE s.name = 'nba'
    """)
    print(f"  Total NBA results rows: {total}")

    await conn.close()
    print("\n✅ Done. If the upsert test passed, the fix is working.")


if __name__ == "__main__":
    asyncio.run(main())
