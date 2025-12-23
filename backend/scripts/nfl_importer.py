"""
Downloads ALL nflverse data from GitHub releases and imports to PostgreSQL.
Also imports existing Kaggle data.

Data Sources:
- player_stats: Weekly player stats
- players: Player directory
- schedules: Games + betting lines
- ftn_charting: Advanced charting data
- weekly_rosters: Who played each week
NFL Data Importer
Downloads nflverse data from GitHub releases and imports to PostgreSQL.
Also imports existing Kaggle data.

Usage:
    await import_all_nfl(clear_existing=False)
"""

import asyncio
import logging
import json
import hashlib
import gc  # Garbage collection for memory management
import requests
from pathlib import Path
from datetime import datetime
import pandas as pd
import asyncpg

logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# nflverse GitHub data sources
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_PBP_BASE = "https://github.com/nflverse/nflverse-pbp/releases/download"

# Years to import (2020-2024 for now)
IMPORT_YEARS = list(range(2020, 2025))

# Per-season player stats (season aggregates - cleaner format)
# These files contain full season totals per player
PLAYER_STATS_REG = {
    year: f"{NFLVERSE_BASE}/player_stats/stats_player_reg_{year}.csv"
    for year in IMPORT_YEARS
}

# Supporting data files
NFLVERSE_FILES = {
    "players": f"{NFLVERSE_BASE}/players/players.csv",
    "schedules": f"{NFLVERSE_BASE}/schedules/schedules.csv",
    "rosters": f"{NFLVERSE_BASE}/rosters/roster.csv",
}

# 2025 season data (play-by-play files, per game)
PBP_2025_TAG = "raw_pbp_2025"

# Local data paths
DATA_DIR = Path("/app/data/nfl")
NFLVERSE_DIR = Path("/app/data/nflverse")


def compute_hash(data: dict) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def download_nflverse(progress_callback=None):
    """Download latest nflverse data from GitHub releases."""
    NFLVERSE_DIR.mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    
    # Download per-year player stats (2020-2024)
    for year, url in PLAYER_STATS_REG.items():
        try:
            name = f"stats_player_reg_{year}"
            if progress_callback:
                progress_callback(f"Downloading {name}.csv...")
            
            response = requests.get(url, timeout=120)
            if response.status_code == 200:
                file_path = NFLVERSE_DIR / f"{name}.csv"
                file_path.write_bytes(response.content)
                downloaded.append(name)
                logger.info(f"Downloaded {name}.csv ({len(response.content)} bytes)")
            else:
                logger.warning(f"Failed to download {name}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading stats for {year}: {e}")
    
    # Download supporting files (players, schedules, rosters)
    for name, url in NFLVERSE_FILES.items():
        try:
            if progress_callback:
                progress_callback(f"Downloading {name}.csv...")
            
            response = requests.get(url, timeout=120)
            if response.status_code == 200:
                file_path = NFLVERSE_DIR / f"{name}.csv"
                file_path.write_bytes(response.content)
                downloaded.append(name)
                logger.info(f"Downloaded {name}.csv ({len(response.content)} bytes)")
            else:
                logger.warning(f"Failed to download {name}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {name}: {e}")
    
    return downloaded


async def get_db_connection():
    """Get database connection."""
    return await asyncpg.connect(DATABASE_URL)


async def ensure_schema(conn):
    """Ensure required columns exist in database tables."""
    try:
        await conn.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE stats ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_hash ON entities(content_hash) WHERE content_hash IS NOT NULL")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_results_hash ON results(content_hash) WHERE content_hash IS NOT NULL")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_hash ON stats(content_hash) WHERE content_hash IS NOT NULL")
        logger.info("Schema setup complete - content_hash columns ready")
    except Exception as e:
        logger.warning(f"Schema setup warning: {e}")


async def ensure_sport_exists(conn) -> int:
    """Ensure NFL sport exists and return sport_id."""
    sport_id = await conn.fetchval(
        "SELECT id FROM sports WHERE name = 'nfl'"
    )
    if not sport_id:
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) 
               VALUES ('nfl', '{}') 
               RETURNING id"""
        )
    return sport_id


# Batch size for commits to prevent memory issues
BATCH_SIZE = 1000


async def import_players(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL players from nflverse players.csv with batching."""
    players_file = NFLVERSE_DIR / "players.csv"
    if not players_file.exists():
        logger.warning("players.csv not found")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Importing players...")
    
    # Map player_id -> entity_id
    player_map = {}
    imported = 0
    batch_count = 0
    
    for chunk in pd.read_csv(players_file, low_memory=False, chunksize=BATCH_SIZE):
        batch_count += 1
        if progress_callback and batch_count % 5 == 0:
            progress_callback(f"Processing player batch {batch_count} ({imported} players imported)...")
        
        for _, row in chunk.iterrows():
            player_id = row.get('gsis_id') or row.get('player_id')
            if not player_id or pd.isna(player_id):
                continue
            
            name = row.get('display_name') or row.get('name') or f"Player {player_id}"
            if pd.isna(name):
                continue
                
            position = row.get('position') or row.get('position_group', '')
            team = row.get('team_abbr') or row.get('current_team_id', '')
            
            metadata = {
                'position': str(position) if not pd.isna(position) else None,
                'team': str(team) if not pd.isna(team) else None,
                'height': row.get('height') if not pd.isna(row.get('height', None)) else None,
                'weight': row.get('weight') if not pd.isna(row.get('weight', None)) else None,
            }
            
            content_hash = compute_hash({'sport': 'nfl', 'player_id': str(player_id)})
            
            try:
                entity_id = await conn.fetchval(
                    """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                       VALUES ($1, $2, 'player', 'nfl', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                       RETURNING id""",
                    sport_id, str(name), json.dumps(metadata), content_hash
                )
                if entity_id:
                    player_map[str(player_id)] = entity_id
                    imported += 1
            except Exception as e:
                logger.debug(f"Error importing player {name}: {e}")
    
    logger.info(f"Imported {imported} players")
    return {"imported": imported, "player_map": player_map}


async def import_player_stats(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import player season stats from nflverse stats_player_reg_YYYY.csv files."""
    
    # Find all stats_player_reg_YYYY.csv files
    stats_files = sorted(NFLVERSE_DIR.glob("stats_player_reg_*.csv"))
    
    if not stats_files:
        logger.warning("No stats_player_reg_*.csv files found")
        return {"imported": 0, "stats_computed": 0}
    
    if progress_callback:
        progress_callback(f"Found {len(stats_files)} season stats files to process...")
    
    def safe_int(val):
        try:
            return int(float(val)) if not pd.isna(val) else None
        except:
            return None
    
    def safe_float(val):
        try:
            return round(float(val), 2) if not pd.isna(val) else None
        except:
            return None
    
    imported = 0
    
    for stats_file in stats_files:
        if progress_callback:
            progress_callback(f"Processing {stats_file.name}...")
        
        try:
            # Read CSV in chunks for memory efficiency
            for chunk in pd.read_csv(stats_file, low_memory=False, chunksize=500):
                for _, row in chunk.iterrows():
                    player_id = row.get('player_id')
                    if pd.isna(player_id):
                        continue
                    
                    season = row.get('season')
                    if pd.isna(season):
                        continue
                    
                    # Build metadata with season totals
                    metadata = {
                        'player_id': str(player_id),
                        'player_name': row.get('player_display_name') or row.get('player_name'),
                        'position': row.get('position'),
                        'team': row.get('recent_team'),
                        'season': safe_int(season),
                        'games': safe_int(row.get('games')),
                        # Passing
                        'pass_att': safe_int(row.get('attempts')),
                        'pass_cmp': safe_int(row.get('completions')),
                        'pass_yds': safe_int(row.get('passing_yards')),
                        'pass_td': safe_int(row.get('passing_tds')),
                        'pass_int': safe_int(row.get('passing_interceptions')),
                        'pass_epa': safe_float(row.get('passing_epa')),
                        # Rushing
                        'rush_att': safe_int(row.get('carries')),
                        'rush_yds': safe_int(row.get('rushing_yards')),
                        'rush_td': safe_int(row.get('rushing_tds')),
                        'rush_epa': safe_float(row.get('rushing_epa')),
                        # Receiving
                        'rec': safe_int(row.get('receptions')),
                        'targets': safe_int(row.get('targets')),
                        'rec_yds': safe_int(row.get('receiving_yards')),
                        'rec_td': safe_int(row.get('receiving_tds')),
                        'rec_epa': safe_float(row.get('receiving_epa')),
                        # Defense
                        'tackles': safe_int(row.get('def_tackles_solo')),
                        'sacks': safe_float(row.get('def_sacks')),
                        'def_int': safe_int(row.get('def_interceptions')),
                        # Fantasy
                        'fantasy_pts': safe_float(row.get('fantasy_points')),
                        'fantasy_pts_ppr': safe_float(row.get('fantasy_points_ppr')),
                    }
                    
                    # Clean None values
                    metadata = {k: v for k, v in metadata.items() if v is not None}
                    
                    # Create unique hash for this player-season
                    content_hash = compute_hash({
                        'sport': 'nfl',
                        'player_id': str(player_id),
                        'season': season,
                        'type': 'season_stats'
                    })
                    
                    try:
                        await conn.execute(
                            """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                               VALUES ($1, $2, 'nfl', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET metadata = EXCLUDED.metadata""",
                            sport_id, int(season), json.dumps(metadata), content_hash
                        )
                        imported += 1
                    except Exception as e:
                        logger.debug(f"Error importing stat row: {e}")
                
                # Memory cleanup after each chunk
                gc.collect()
        
        except Exception as e:
            logger.error(f"Error processing {stats_file.name}: {e}")
    
    logger.info(f"Imported {imported} player season stats")
    return {"imported": imported, "stats_computed": imported}


def compute_season_stats(games: list) -> dict:
    """Compute season aggregates from list of game stats."""
    stats = {
        'games': len(games),
        # Passing
        'pass_att': sum(g.get('pass_att', 0) or 0 for g in games),
        'pass_cmp': sum(g.get('pass_cmp', 0) or 0 for g in games),
        'pass_yds': sum(g.get('pass_yds', 0) or 0 for g in games),
        'pass_td': sum(g.get('pass_td', 0) or 0 for g in games),
        'pass_int': sum(g.get('pass_int', 0) or 0 for g in games),
        # Rushing
        'rush_att': sum(g.get('rush_att', 0) or 0 for g in games),
        'rush_yds': sum(g.get('rush_yds', 0) or 0 for g in games),
        'rush_td': sum(g.get('rush_td', 0) or 0 for g in games),
        # Receiving
        'rec': sum(g.get('rec', 0) or 0 for g in games),
        'rec_yds': sum(g.get('rec_yds', 0) or 0 for g in games),
        'rec_td': sum(g.get('rec_td', 0) or 0 for g in games),
        'targets': sum(g.get('targets', 0) or 0 for g in games),
        # Defense
        'tackles': sum(g.get('tackles', 0) or 0 for g in games),
        'sacks': round(sum(g.get('sacks', 0) or 0 for g in games), 1),
        'def_int': sum(g.get('def_int', 0) or 0 for g in games),
    }
    
    # Per-game averages
    if stats['games'] > 0:
        stats['pass_yds_per_game'] = round(stats['pass_yds'] / stats['games'], 1)
        stats['rush_yds_per_game'] = round(stats['rush_yds'] / stats['games'], 1)
        stats['rec_yds_per_game'] = round(stats['rec_yds'] / stats['games'], 1)
    
    # Completion percentage
    if stats['pass_att'] > 0:
        stats['comp_pct'] = round(100 * stats['pass_cmp'] / stats['pass_att'], 1)
    
    # Yards per carry
    if stats['rush_att'] > 0:
        stats['rush_ypc'] = round(stats['rush_yds'] / stats['rush_att'], 1)
    
    return stats


async def import_all_nfl(clear_existing: bool = False, progress_callback=None) -> dict:
    """
    Main entry point: Download nflverse data and import to PostgreSQL.
    
    Args:
        clear_existing: If True, delete existing NFL data first
        progress_callback: Optional function to report progress
    
    Returns:
        dict with import results
    """
    results = {
        "status": "success",
        "downloaded": [],
        "players_imported": 0,
        "games_imported": 0,
        "stats_computed": 0,
        "errors": []
    }
    
    conn = None
    try:
        # Step 1: Download nflverse data
        if progress_callback:
            progress_callback("Starting NFL data import...")
        
        downloaded = await download_nflverse(progress_callback)
        results["downloaded"] = downloaded
        
        # Step 2: Connect to database
        if progress_callback:
            progress_callback("Connecting to database...")
        
        conn = await get_db_connection()
        
        # Ensure schema has required columns
        await ensure_schema(conn)
        
        sport_id = await ensure_sport_exists(conn)
        
        # Step 3: Clear existing if requested
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NFL data...")
            
            await conn.execute(
                "DELETE FROM results WHERE sport_id = $1",
                sport_id
            )
            await conn.execute(
                "DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)",
                sport_id
            )
            await conn.execute(
                "DELETE FROM entities WHERE sport_id = $1",
                sport_id
            )
        
        # Step 4: Import players
        player_result = await import_players(conn, sport_id, progress_callback)
        results["players_imported"] = player_result.get("imported", 0)
        player_map = player_result.get("player_map", {})
        
        # Step 5: Import player stats
        stats_result = await import_player_stats(conn, sport_id, player_map, progress_callback)
        results["games_imported"] = stats_result.get("imported", 0)
        results["stats_computed"] = stats_result.get("stats_computed", 0)
        
        if progress_callback:
            progress_callback("NFL import complete!")
        
    except Exception as e:
        logger.error(f"NFL import failed: {e}")
        results["status"] = "failed"
        results["errors"].append(str(e))
        if progress_callback:
            progress_callback(f"❌ Error: {e}")
    finally:
        if conn:
            await conn.close()
    
    return results


if __name__ == "__main__":
    # For testing
    async def test_import():
        def log_progress(msg):
            print(f"[PROGRESS] {msg}")
        
        result = await import_all_nfl(clear_existing=True, progress_callback=log_progress)
        print(f"Result: {result}")
    
    asyncio.run(test_import())
