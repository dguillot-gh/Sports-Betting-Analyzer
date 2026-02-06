import asyncio
import logging
import json
import hashlib
import requests
import pandas as pd
import asyncpg
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any, Optional

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nhl_importer")

# Database Configuration
try:
    # Try to import from project config
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    from src.config import DATABASE_URL
except ImportError:
    DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# MoneyPuck URLs
MONEYPUCK_ALL_TEAMS_GAME_BY_GAME = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv"
MONEYPUCK_PLAYER_BIOS = "https://moneypuck.com/moneypuck/playerData/playerBios/allPlayersLookup.csv"

# Request Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# NHL API Base
NHL_API_BASE = "https://api-web.nhle.com/v1"

# Local Data Cache
DATA_DIR = Path(__file__).parent.parent / "data" / "nhl"
DATA_DIR.mkdir(parents=True, exist_ok=True)

async def ensure_schema(conn):
    """Ensure required columns and NHL sport exist."""
    try:
        await conn.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        # Indexes are now correctly total (not partial)
    except Exception as e:
        logger.warning(f"Schema update warning: {e}")

def compute_hash(data: dict) -> str:
    """Compute MD5 hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

async def ensure_sport_exists(conn) -> int:
    """Ensure NHL sport exists in the database."""
    sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nhl'")
    if not sport_id:
        logger.info("Registering 'nhl' sport...")
        sport_id = await conn.fetchval(
            "INSERT INTO sports (name, config) VALUES ('nhl', '{}') RETURNING id"
        )
    return sport_id

async def import_moneypuck_game_data(conn, sport_id: int, limit: int = None, progress_callback=None):
    """Import team game-by-game data from MoneyPuck."""
    logger.info("Starting MoneyPuck game-level import...")
    
    # Download file
    local_file = DATA_DIR / "all_teams_games.csv"
    if not local_file.exists():
        logger.info(f"Downloading MoneyPuck guest dataset: {MONEYPUCK_ALL_TEAMS_GAME_BY_GAME}")
        response = requests.get(MONEYPUCK_ALL_TEAMS_GAME_BY_GAME, headers=HEADERS, stream=True)
        if response.status_code == 200:
            local_file.write_bytes(response.content)
            logger.info("Download complete.")
        else:
            logger.error(f"Failed to download MoneyPuck data: {response.status_code}")
            return

    # Process CSV in chunks to save memory
    count = 0
    batch_size = 500
    
    # We use a set of team names for lookup
    team_map = {} 

    logger.info("Ingesting game data into 'results' table...")
    for chunk in pd.read_csv(local_file, chunksize=batch_size):
        for _, row in chunk.iterrows():
            if limit and count >= limit:
                break
            # Basic Game Info
            team_name = row.get('team')
            game_id = row.get('gameId')
            season = row.get('season')
            game_date = row.get('gameDate')
            
            if pd.isna(team_name) or pd.isna(game_id):
                continue
                
            # Create Team Entity if not exists (using content hash for uniqueness)
            if team_name not in team_map:
                team_hash = compute_hash({"sport": "nhl", "team_name": team_name})
                try:
                    ent_id = await conn.fetchval(
                        """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                           VALUES ($1, $2, 'team', 'nhl', $3, $4)
                           ON CONFLICT (content_hash) DO UPDATE SET name = EXCLUDED.name
                           RETURNING id""",
                        sport_id, team_name, json.dumps({"is_nhl": True}), team_hash
                    )
                    team_map[team_name] = ent_id
                except Exception as e:
                    logger.error(f"Error creating team entity {team_name}: {e}")
                    # Try to fetch existing if insertion fails
                    ent_id = await conn.fetchval("SELECT id FROM entities WHERE content_hash = $1", team_hash)
                    team_map[team_name] = ent_id

            # Result Mapping (MoneyPuck uses exhaustive stats)
            # We store the full row as metadata for future model training
            metadata = row.to_dict()
            # Clean up NaN for JSON
            metadata = {k: (None if pd.isna(v) else v) for k, v in metadata.items()}
            
            result_hash = compute_hash({
                "sport": "nhl",
                "game_id": str(game_id),
                "team": team_name
            })
            
            # Robust Season Parsing
            try:
                if isinstance(season, str) and '-' in season:
                    clean_season = int(season.split('-')[0])
                else:
                    clean_season = int(float(season))
            except:
                clean_season = 0

            try:
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nhl', $3, $4)
                       ON CONFLICT (content_hash) DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, clean_season, json.dumps(metadata), result_hash
                )
                count += 1
            except Exception as e:
                logger.error(f"Row skip error for game {game_id} (Team: {team_name}): {e}")

        if limit and count >= limit:
            break
            
        if progress_callback:
            progress_callback(f"Imported {count} games...")
        elif count % 5000 == 0:
            logger.info(f"Progress: {count} results imported.")

    logger.info(f"Finished MoneyPuck import. Total results: {count}")

async def import_player_bios(conn, sport_id: int):
    """Import player metadata from MoneyPuck."""
    logger.info("Importing player bios...")
    local_file = DATA_DIR / "player_bios.csv"
    
    if not local_file.exists():
        logger.info(f"Downloading MoneyPuck player bios: {MONEYPUCK_PLAYER_BIOS}")
        try:
            response = requests.get(MONEYPUCK_PLAYER_BIOS, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                local_file.write_bytes(response.content)
                logger.info("Player bios download complete.")
            else:
                logger.error(f"Failed to download player bios: {response.status_code}")
                return
        except Exception as e:
            logger.error(f"Error downloading player bios: {e}")
            return
    
    if not local_file.exists():
        logger.error("Player bios file missing and download failed.")
        return

    df = pd.read_csv(local_file)
    count = 0
    for _, row in df.iterrows():
        name = row.get('name')
        player_id = row.get('playerId')
        if pd.isna(name) or pd.isna(player_id):
            continue
            
        metadata = row.to_dict()
        metadata = {k: (None if pd.isna(v) else v) for k, v in metadata.items()}
        
        player_hash = compute_hash({"sport": "nhl", "player_id": str(player_id)})
        
        await conn.execute(
            """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
               VALUES ($1, $2, 'player', 'nhl', $3, $4)
               ON CONFLICT (content_hash) DO UPDATE SET metadata = EXCLUDED.metadata""",
            sport_id, name, json.dumps(metadata), player_hash
        )
        count += 1
        
    logger.info(f"Imported {count} NHL players.")

async def sync_live_standings(conn, sport_id: int):
    """Fetch current standings from NHL API."""
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"Syncing NHL Standings for {today}...")
    
    url = f"{NHL_API_BASE}/standings/{today}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # In our system, we store the standings as a special 'stats' or 'metadata' blob 
            # for the team entities or a global 'nhl_standings' entry in some tracker table.
            # For simplicity, we'll just log success here as the main goal is historical data for now.
            logger.info(f"Found {len(data.get('standings', []))} teams in standings.")
        else:
            logger.warning(f"NHL API error: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to sync standings: {e}")

async def main():
    logger.info("--- NHL Importer Starting ---")
    conn = None
    try:
        # Use DATABASE_URL from config if possible
        try:
            from src.config import DATABASE_URL as CFG_DB
            url = CFG_DB
        except:
            url = DATABASE_URL
            
        conn = await asyncpg.connect(url)
        
        # 1. Setup
        await ensure_schema(conn)
        sport_id = await ensure_sport_exists(conn)
        
        # 2. Historical Data (MoneyPuck)
        await import_moneypuck_game_data(conn, sport_id, limit=20000)
        await import_player_bios(conn, sport_id)
        
        # 3. Live Data (NHL API)
        await sync_live_standings(conn, sport_id)
        
        logger.info("NHL Import Process Complete.")
        
    except Exception as e:
        logger.error(f"Critical error in importer: {e}", exc_info=True)
    finally:
        if conn:
            await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
