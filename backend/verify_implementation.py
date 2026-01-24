
import asyncio
import json
from datetime import date, timedelta
from src.odds_cache import get_cache_service
from scripts.nba_importer import get_db_connection, update_historical_odds_task

async def get_safe_connection():
    from src.config import DATABASE_URL
    import asyncpg
    # Force localhost for local verification outside Docker
    local_url = DATABASE_URL.replace("@postgres:", "@localhost:")
    try:
        return await asyncpg.connect(local_url)
    except Exception as e:
        print(f"Failed to connect to {local_url}: {e}")
        raise e

async def verify_cache():
    print("--- Verifying Cache Persistence ---")
    cache = get_cache_service()
    test_id = f"test_verification_{int(asyncio.get_event_loop().time())}"
    test_data = {"home_team": "Lakers", "away_team": "Celtics", "analysis": {"result": "Win"}}
    
    # Store with current logic (48h expiration)
    await cache.store_games("nba", [{"id": test_id, **test_data}])
    
    # Retrieve
    stored = await cache.get_game(test_id)
    if stored and stored.get("analysis") == test_data["analysis"]:
        print("✅ Cache store/retrieve working.")
        # Check expire_at in DB
        conn = await get_safe_connection()
        expire_at = await conn.fetchval("SELECT expires_at FROM odds_cache WHERE game_id = $1", test_id)
        print(f"✅ Cache expiration set to: {expire_at}")
        await conn.execute("DELETE FROM odds_cache WHERE game_id = $1", test_id)
        await conn.close()
    else:
        print("❌ Cache verification failed.")

async def verify_historical_backfill():
    print("\n--- Verifying Historical Backfill ---")
    conn = await get_safe_connection()
    try:
        # Check if we have recent NBA games with missing lines
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
        target_date = date.today() - timedelta(days=2)
        date_str = target_date.strftime('%Y-%m-%d')
        
        count_missing = await conn.fetchval(
            "SELECT count(*) FROM results WHERE sport_id = $1 AND game_date LIKE $2 AND (metadata->>'closing_total' IS NULL)",
            sport_id, f"{date_str}%"
        )
        print(f"Found {count_missing} games from {date_str} missing lines.")
        
        if count_missing > 0:
            # Run the supplemental task for 3 days back
            def log_progress(msg): print(f"  [Progress] {msg}")
            await update_historical_odds_task(conn, days_back=3, progress_callback=log_progress)
            
            # Re-check
            count_after = await conn.fetchval(
                "SELECT count(*) FROM results WHERE sport_id = $1 AND game_date LIKE $2 AND (metadata->>'closing_total' IS NOT NULL)",
                sport_id, f"{date_str}%"
            )
            print(f"✅ Games with lines after backfill: {count_after}")
        else:
            print("No missing lines to test with (data might already be full).")
            
    finally:
        await conn.close()

async def main():
    await verify_cache()
    await verify_historical_backfill()

if __name__ == "__main__":
    asyncio.run(main())
