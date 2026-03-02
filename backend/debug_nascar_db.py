
import asyncio
import asyncpg
import json
from src.config import DATABASE_URL

async def debug_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Check sport
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        print(f"NASCAR Sport ID: {sport_id}")
        
        if not sport_id:
            print("No sport entry for 'nascar'")
            return

        # Check results count
        count = await conn.fetchval("SELECT COUNT(*) FROM results WHERE sport_id = $1", sport_id)
        print(f"Total NASCAR Results: {count}")
        
        # Check series distribution
        series_counts = await conn.fetch("""
            SELECT series, COUNT(*) as c 
            FROM results 
            WHERE sport_id = $1 
            GROUP BY series
        """, sport_id)
        
        print("\nResults by Series:")
        for row in series_counts:
            print(f"  {row['series']}: {row['c']}")
            
        # Check a sample row
        sample = await conn.fetchrow("""
            SELECT season, series, track, metadata
            FROM results 
            WHERE sport_id = $1 AND series = 'cup'
            LIMIT 1
        """, sport_id)
        
        if sample:
            print("\nSample Cup Result:")
            print(f"  Season: {sample['season']}")
            print(f"  Series: {repr(sample['series'])}")
            print(f"  Track: {sample['track']}")
            print(f"  Metadata: {sample['metadata'][:100]}...")
        else:
             print("\nNo Cup results found.")

        # Check unique series values with repr
        print("\nUnique Series Values (repr):")
        distinct_series = await conn.fetch("SELECT DISTINCT series FROM results WHERE sport_id = $1", sport_id)
        for row in distinct_series:
            print(f"  {repr(row['series'])}")

        # Test exact query match
        print("\nTesting Query with series='cup':")
        try:
            cup_count = await conn.fetchval(
                "SELECT COUNT(*) FROM results WHERE sport_id = $1 AND series = $2", 
                sport_id, 'cup'
            )
            print(f"  Count for 'cup': {cup_count}")
        except Exception as e:
            print(f"  Query failed: {e}")
            
        # Test case insensitive
        print("\nTesting Query with series='Cup' (case check):")
        cup_count_upper = await conn.fetchval(
            "SELECT COUNT(*) FROM results WHERE sport_id = $1 AND series = $2", 
            sport_id, 'Cup'
        )
        print(f"  Count for 'Cup': {cup_count_upper}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(debug_db())
