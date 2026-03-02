
import asyncio
import json
import logging
import time
from datetime import date, timedelta
import httpx
import asyncpg
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/sports_betting")

# API Configuration
NCAA_API_BASE = "https://ncaa-api.henrygd.me/scoreboard/baseball/d1"

async def fetch_games_for_date(client: httpx.AsyncClient, target_date: date) -> List[Dict[str, Any]]:
    """Fetch games for a specific date from ncaa-api."""
    year = target_date.year
    month = f"{target_date.month:02d}"
    day = f"{target_date.day:02d}"
    url = f"{NCAA_API_BASE}/{year}/{month}/{day}"
    
    try:
        response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get("games", [])
        elif response.status_code == 404:
            # excessive 404s might mean no games that day, which is fine
            return []
        else:
            logger.warning(f"Failed to fetch {target_date}: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error fetching {target_date}: {e}")
        return []

async def save_game_result(conn, game: Dict[str, Any], game_date: date):
    """Save a single game result to the database."""
    try:
        # Extract relevant data
        game_id = game.get("game", {}).get("url", "") # Use URL as unique ID if possible, or build one
        if not game_id:
             game_id = f"{game_date}-{game.get('home', {}).get('names', {}).get('short', 'UNKNOWN')}-{game.get('away', {}).get('names', {}).get('short', 'UNKNOWN')}"
        
        home_team = game.get("home", {}).get("names", {}).get("short", "")
        away_team = game.get("away", {}).get("names", {}).get("short", "")
        
        home_score = game.get("home", {}).get("score", "")
        away_score = game.get("away", {}).get("score", "")
        
        # Skip if game isn't finished or scores are missing
        if game.get("gameState") != "final" or not home_score or not away_score:
            return

        try:
             home_score = int(home_score)
             away_score = int(away_score)
        except:
             return # Skip invalid scores

        # Normalize team names to match our database entities if possible
        # For now, we store raw names and do matching in the trainer/importer
        
        metadata = {
            "gameDate": str(game_date),
            "homeTeam": home_team,
            "awayTeam": away_team,
            "homeScore": home_score,
            "awayScore": away_score,
            "neutralSite": game.get("game", {}).get("neutral", False),
            "source": "ncaa-api"
        }
        
        # Calculate winner for content hash or ID
        # We use a content hash to prevent duplicates
        import hashlib
        content_hash = hashlib.md5(f"college_baseball-{game_date}-{home_team}-{away_team}".encode()).hexdigest()
        
        # Insert into results table
        # We use 'college_baseball' as the series
        await conn.execute("""
            INSERT INTO results (sport_id, series, season, event_date, metadata, content_hash)
            VALUES (
                (SELECT id FROM sports WHERE name = 'college_baseball'),
                'college_baseball',
                $1,
                $2,
                $3,
                $4
            )
            ON CONFLICT (content_hash) DO NOTHING
        """, game_date.year, game_date, json.dumps(metadata), content_hash)
        
    except Exception as e:
        logger.error(f"Error saving game {game_id}: {e}")

async def backfill_season(year: int):
    """Backfill an entire season (Feb-June)."""
    logger.info(f"Starting backfill for {year} season...")
    
    # College baseball season typically Feb 1 - June 30
    start_date = date(year, 2, 1)
    end_date = date(year, 6, 30)
    
    current_date = start_date
    
    # Connect to DB
    try:
        # Try importing config if available, else use env
        try:
            from src.config import DATABASE_URL as CFG_DB
            db_url = CFG_DB
        except:
            db_url = DATABASE_URL
            
        conn = await asyncpg.connect(db_url)
        
        # Ensure sport exists
        await conn.execute("""
            INSERT INTO sports (name, display_name) VALUES ('college_baseball', 'College Baseball') 
            ON CONFLICT (name) DO NOTHING
        """)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            while current_date <= end_date:
                # Don't go into the future
                if current_date > date.today():
                    break
                
                logger.info(f"Fetching {current_date}...")
                games = await fetch_games_for_date(client, current_date)
                
                if games:
                    logger.info(f"  Found {len(games)} games. Saving...")
                    for game in games:
                        await save_game_result(conn, game, current_date)
                else:
                    logger.info("  No games found.")
                
                # Respect rate limit (5 req/sec -> 0.2s delay is safe, we do 0.5s to be nicer)
                await asyncio.sleep(0.5)
                current_date += timedelta(days=1)
                
    except Exception as e:
        logger.error(f"Critical error during backfill: {e}")
    finally:
        if 'conn' in locals():
            await conn.close()
    
    logger.info(f"Season {year} backfill complete.")

if __name__ == "__main__":
    import os
    import sys
    
    # Add project root to path to allow imports if needed
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    
    if len(sys.argv) > 1:
        years = [int(y) for y in sys.argv[1:]]
    else:
        years = [2024, 2025] # Default to last two seasons
        
    for year in years:
        asyncio.run(backfill_season(year))
