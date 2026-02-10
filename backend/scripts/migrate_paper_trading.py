"""
Manual migration script to add game_id and bet_metadata columns to the bets table.
"""
import asyncio
import asyncpg
import os

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting')

async def run_migration():
    print(f"Connecting to: {DATABASE_URL[:50]}...")
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # Check and add game_id
        val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='game_id'")
        if not val:
            print("Adding game_id column...")
            await conn.execute("ALTER TABLE bets ADD COLUMN game_id VARCHAR(100)")
            print("✅ game_id column added")
        else:
            print("ℹ️ game_id column already exists")
        
        # Check and add bet_metadata
        val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='bet_metadata'")
        if not val:
            print("Adding bet_metadata column...")
            await conn.execute("ALTER TABLE bets ADD COLUMN bet_metadata JSONB")
            print("✅ bet_metadata column added")
        else:
            print("ℹ️ bet_metadata column already exists")
        
        # Create index for game_id
        print("Creating index on game_id...")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_game_id ON bets(game_id)")
        print("✅ Index created")
        
        # Verify
        columns = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='bets'")
        print(f"\nFinal columns: {[c['column_name'] for c in columns]}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
