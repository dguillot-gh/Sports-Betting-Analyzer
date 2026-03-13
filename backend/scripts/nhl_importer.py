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

async def import_moneypuck_game_data(conn, sport_id: int, limit: int = None, start_year: int = 2023, progress_callback=None) -> dict:
    """Import team game-by-game data from MoneyPuck."""
    logger.info("Starting MoneyPuck game-level import...")
    
    # Download file (always re-download to ensure fresh data)
    local_file = DATA_DIR / "all_teams_games.csv"
    logger.info(f"Downloading MoneyPuck dataset: {MONEYPUCK_ALL_TEAMS_GAME_BY_GAME}")
    try:
        response = requests.get(MONEYPUCK_ALL_TEAMS_GAME_BY_GAME, headers=HEADERS, stream=True, timeout=120)
        if response.status_code == 200:
            local_file.write_bytes(response.content)
            logger.info(f"Download complete ({len(response.content)} bytes).")
        else:
            if local_file.exists():
                logger.warning(f"Failed to download fresh MoneyPuck data (HTTP {response.status_code}), using cached file")
            else:
                logger.error(f"Failed to download MoneyPuck data: {response.status_code}")
                return
    except Exception as e:
        if local_file.exists():
            logger.warning(f"MoneyPuck download failed ({e}), using cached file")
        else:
            logger.error(f"MoneyPuck download failed and no cached file: {e}")
            return

    # Process CSV in chunks to save memory
    count = 0
    inserted_count = 0
    updated_count = 0
    error_count = 0
    skipped_count = 0
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
                skipped_count += 1
                continue
            
            # Skip seasons before start_year
            try:
                parsed_season = int(season.split('-')[0]) if isinstance(season, str) and '-' in season else int(float(season))
            except:
                parsed_season = 0
            if parsed_season < start_year:
                skipped_count += 1
                continue
                
            # Create Team Entity if not exists (using content hash for uniqueness)
            if team_name not in team_map:
                team_hash = compute_hash({"sport": "nhl", "team_name": team_name})
                try:
                    ent_id = await conn.fetchval(
                        """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                           VALUES ($1, $2, 'team', 'nhl', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL DO UPDATE SET name = EXCLUDED.name
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
            # Clean up NaN and convert numpy types for JSON serialization
            clean = {}
            for k, v in metadata.items():
                if pd.isna(v):
                    clean[k] = None
                elif hasattr(v, 'item'):  # numpy int64, float64, etc.
                    clean[k] = v.item()
                else:
                    clean[k] = v
            metadata = clean
            
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

            # Results: Track new vs updated
            try:
                # Use RETURNING (xmax = 0) to distinguish INSERT vs UPDATE
                is_insert = await conn.fetchval(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nhl', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
                       DO UPDATE SET metadata = EXCLUDED.metadata
                       RETURNING (xmax = 0) AS is_insert""",
                    sport_id, clean_season, json.dumps(metadata), result_hash
                )
                if is_insert:
                    inserted_count += 1
                else:
                    updated_count += 1
                count += 1
            except Exception as e:
                error_count += 1
                if error_count <= 3:
                    logger.error(f"Row skip error for game {game_id} (Team: {team_name}): {e}")
                elif error_count == 4:
                    logger.error("Suppressing further per-row errors...")

        if limit and count >= limit:
            break
            
        if progress_callback:
            progress_callback(f"Imported {count} games (skipped: {skipped_count}, errors: {error_count})...")
        elif count > 0 and count % 5000 == 0:
            logger.info(f"Progress: {count} results imported.")

    if count == 0:
        logger.warning(f"NHL import produced 0 results. Skipped: {skipped_count}, Errors: {error_count}. Check season filter (start_year={start_year}) and data format.")
    logger.info(f"Finished MoneyPuck import. Total: {count} (New: {inserted_count}, Updated: {updated_count}, Errors: {error_count})")
    return {"total": count, "new": inserted_count, "updated": updated_count}

async def import_player_bios(conn, sport_id: int) -> dict:
    """Import player metadata from MoneyPuck."""
    logger.info("Importing player bios...")
    local_file = DATA_DIR / "player_bios.csv"
    
    # Always re-download to ensure fresh data
    logger.info(f"Downloading MoneyPuck player bios: {MONEYPUCK_PLAYER_BIOS}")
    try:
        response = requests.get(MONEYPUCK_PLAYER_BIOS, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            local_file.write_bytes(response.content)
            logger.info(f"Player bios download complete ({len(response.content)} bytes).")
        else:
            if local_file.exists():
                logger.warning(f"Failed to download fresh player bios (HTTP {response.status_code}), using cached")
            else:
                logger.error(f"Failed to download player bios: {response.status_code}")
                return
    except Exception as e:
        if local_file.exists():
            logger.warning(f"Player bios download failed ({e}), using cached")
        else:
            logger.error(f"Player bios download failed and no cached file: {e}")
            return
    
    df = pd.read_csv(local_file)
    count = 0
    inserted_count = 0
    updated_count = 0
    for _, row in df.iterrows():
        name = row.get('name')
        player_id = row.get('playerId')
        if pd.isna(name) or pd.isna(player_id):
            continue
            
        metadata = row.to_dict()
        metadata = {k: (None if pd.isna(v) else v) for k, v in metadata.items()}
        
        player_hash = compute_hash({"sport": "nhl", "player_id": str(player_id)})
        
        # Use RETURNING (xmax = 0) to distinguish INSERT vs UPDATE
        is_insert = await conn.fetchval(
            """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
               VALUES ($1, $2, 'player', 'nhl', $3, $4)
               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
               DO UPDATE SET metadata = EXCLUDED.metadata
               RETURNING (xmax = 0) AS is_insert""",
            sport_id, name, json.dumps(metadata), player_hash
        )
        if is_insert:
            inserted_count += 1
        else:
            updated_count += 1
        count += 1
        
    logger.info(f"Imported {count} NHL players (New: {inserted_count}, Updated: {updated_count}).")
    return {"total": count, "new": inserted_count, "updated": updated_count}

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

async def import_all_nhl(clear_existing: bool = False, start_year: int = 2023, progress_callback=None) -> dict:
    """
    Standardized entry point for NHL import (used by scheduler).
    Downloads fresh data from MoneyPuck + NHL API and imports to DB.
    
    Returns:
        dict with import results
    """
    results = {
        "status": "success",
        "games_imported": 0,
        "games_new": 0,
        "games_updated": 0,
        "players_imported": 0,
        "players_new": 0,
        "players_updated": 0,
        "errors": []
    }
    
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        await ensure_schema(conn)
        sport_id = await ensure_sport_exists(conn)
        
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NHL data...")
            await conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
            await conn.execute(
                "DELETE FROM entities WHERE sport_id = $1",
                sport_id
            )
        
        # 1. MoneyPuck game data (always fresh download)
        if progress_callback:
            progress_callback("Downloading MoneyPuck game data...")
        game_res = await import_moneypuck_game_data(conn, sport_id, start_year=start_year, progress_callback=progress_callback)
        results["games_imported"] = game_res.get("total", 0)
        results["games_new"] = game_res.get("new", 0)
        results["games_updated"] = game_res.get("updated", 0)
        
        # 2. Player bios
        if progress_callback:
            progress_callback("Importing player bios...")
        player_res = await import_player_bios(conn, sport_id)
        results["players_imported"] = player_res.get("total", 0)
        results["players_new"] = player_res.get("new", 0)
        results["players_updated"] = player_res.get("updated", 0)
        
        # 3. Live standings
        if progress_callback:
            progress_callback("Syncing live standings...")
        await sync_live_standings(conn, sport_id)
        
        if progress_callback:
            progress_callback("NHL import complete!")
        
        logger.info(f"NHL import complete: {results['games_imported']} games, {results['players_imported']} players")
        
    except Exception as e:
        logger.error(f"NHL import failed: {e}", exc_info=True)
        results["status"] = "failed"
        results["errors"].append(str(e))
    finally:
        if conn:
            await conn.close()
    
    return results


async def main():
    """CLI entry point."""
    result = await import_all_nhl()
    logger.info(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
