#!/usr/bin/env python3

import asyncio
import asyncpg

async def check_database_data():
    try:
        # Connect to database
        conn = await asyncpg.connect(
            "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"
        )
        
        print("=== Database Data Overview ===")
        
        # Check sports table
        sports = await conn.fetch("SELECT id, name FROM sports ORDER BY name")
        print(f"Sports in database: {len(sports)}")
        for sport in sports:
            print(f"  - {sport['name']} (ID: {sport['id']})")
        
        # Check results table by sport
        print("\n=== Results Data by Sport ===")
        for sport in sports:
            sport_name = sport['name']
            sport_id = sport['id']
            
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM results WHERE sport_id = $1", sport_id
            )
            
            if count > 0:
                # Check latest season
                latest_season = await conn.fetchval(
                    "SELECT MAX(season) FROM results WHERE sport_id = $1", sport_id
                )
                
                # Check if scores exist
                with_scores = await conn.fetchval(
                    "SELECT COUNT(*) FROM results WHERE sport_id = $1 AND home_score IS NOT NULL AND away_score IS NOT NULL",
                    sport_id
                )
                
                print(f"  {sport_name}: {count:,} total games, latest season: {latest_season}, {with_scores:,} with scores")
            else:
                print(f"  {sport_name}: No data")
        
        # Check entities table
        print("\n=== Entities Data ===")
        entity_count = await conn.fetchval("SELECT COUNT(*) FROM entities")
        print(f"Total entities: {entity_count:,}")
        
        # Show sample entities by sport
        for sport in sports:
            sport_name = sport['name']
            sport_id = sport['id']
            
            entities = await conn.fetch(
                """
                SELECT e.name, e.type 
                FROM entities e 
                WHERE e.sport_id = $1 
                LIMIT 3
                """, sport_id
            )
            
            if entities:
                print(f"  {sport_name} entities sample:")
                for entity in entities:
                    print(f"    - {entity['name']} ({entity['type']})")
        
        await conn.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_database_data())
