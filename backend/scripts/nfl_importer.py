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

# Years to import (2020-2024 from pre-computed stats files)
# 2025 season uses PBP aggregation since nflverse hasn't published stats files for ongoing season
IMPORT_YEARS = list(range(2020, 2025))

# Per-season weekly player stats from nflverse-data releases
# These files contain weekly stats per player (we'll aggregate to season totals)
# URL format: https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_YYYY.csv
PLAYER_STATS_WEEKLY = {
    year: f"{NFLVERSE_BASE}/player_stats/player_stats_{year}.csv"
    for year in IMPORT_YEARS
}

# Season-level aggregates (pre-computed by nflverse)
# URL format: https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_season_YYYY.csv  
PLAYER_STATS_SEASON = {
    year: f"{NFLVERSE_BASE}/player_stats/player_stats_season_{year}.csv"
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
    
    # Download per-year season stats (2020-2024 - 2025 uses PBP)
    for year, url in PLAYER_STATS_SEASON.items():
        try:
            name = f"player_stats_season_{year}"
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


async def download_pbp_2025(progress_callback=None) -> list:
    """Download 2025 play-by-play RDS files from nflverse-pbp releases."""
    import gzip
    
    PBP_DIR = NFLVERSE_DIR / "pbp_2025"
    PBP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get list of available files from GitHub API
    api_url = f"https://api.github.com/repos/nflverse/nflverse-pbp/releases/tags/{PBP_2025_TAG}"
    
    try:
        if progress_callback:
            progress_callback("Fetching 2025 PBP file list...")
        
        response = requests.get(api_url, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to get PBP 2025 release info: {response.status_code}")
            return []
        
        release_data = response.json()
        assets = release_data.get("assets", [])
        
        # Filter for .rds files (smaller than .json.gz)
        rds_files = [a for a in assets if a["name"].endswith(".rds")]
        
        if progress_callback:
            progress_callback(f"Found {len(rds_files)} PBP game files for 2025...")
        
        downloaded = []
        for i, asset in enumerate(rds_files):
            name = asset["name"]
            url = asset["browser_download_url"]
            
            file_path = PBP_DIR / name
            
            # Skip if already downloaded
            if file_path.exists():
                downloaded.append(name)
                continue
            
            try:
                if progress_callback and i % 20 == 0:
                    progress_callback(f"Downloading PBP {i+1}/{len(rds_files)}: {name}...")
                
                resp = requests.get(url, timeout=60)
                if resp.status_code == 200:
                    file_path.write_bytes(resp.content)
                    downloaded.append(name)
                    logger.info(f"Downloaded {name}")
            except Exception as e:
                logger.error(f"Error downloading {name}: {e}")
        
        logger.info(f"Downloaded {len(downloaded)} PBP 2025 files")
        return downloaded
    
    except Exception as e:
        logger.error(f"Error fetching PBP 2025 list: {e}")
        return []


async def import_pbp_2025(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import 2025 player stats from play-by-play RDS files.
    
    Args:
        conn: Database connection
        sport_id: NFL sport ID
        player_map: Dict mapping player_id -> entity_id for stats table insertion
        progress_callback: Optional progress callback function
    """
    try:
        import pyreadr
    except ImportError:
        logger.error("pyreadr not installed. Run: pip install pyreadr")
        return {"error": "pyreadr not installed"}
    
    PBP_DIR = NFLVERSE_DIR / "pbp_2025"
    rds_files = sorted(PBP_DIR.glob("*.rds"))
    
    if not rds_files:
        logger.warning("No PBP 2025 RDS files found")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback(f"Processing {len(rds_files)} PBP 2025 game files...")
    
    # Aggregate player stats across all games
    player_stats = {}  # player_id -> cumulative stats
    games_processed = 0
    
    for i, rds_file in enumerate(rds_files):
        try:
            if progress_callback and i % 20 == 0:
                progress_callback(f"Processing game {i+1}/{len(rds_files)}: {rds_file.name}...")
            
            # Read RDS file
            result = pyreadr.read_r(str(rds_file))
            if not result:
                continue
            
            df = list(result.values())[0]
            
            # Aggregate stats by player from play-by-play
            # Common columns: passer_player_id, rusher_player_id, receiver_player_id
            # Stats: passing_yards, rushing_yards, receiving_yards, etc.
            
            for _, play in df.iterrows():
                # Passing stats
                passer_id = play.get('passer_player_id')
                if passer_id and not pd.isna(passer_id):
                    if passer_id not in player_stats:
                        player_stats[passer_id] = {
                            'player_id': str(passer_id),
                            'player_name': play.get('passer_player_name'),
                            'position': 'QB',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[passer_id]['games'].add(play.get('game_id'))
                    if play.get('pass_attempt') == 1:
                        player_stats[passer_id]['pass_att'] += 1
                    if play.get('complete_pass') == 1:
                        player_stats[passer_id]['pass_cmp'] += 1
                    player_stats[passer_id]['pass_yds'] += int(play.get('passing_yards') or 0)
                    if play.get('pass_touchdown') == 1:
                        player_stats[passer_id]['pass_td'] += 1
                    if play.get('interception') == 1:
                        player_stats[passer_id]['pass_int'] += 1
                
                # Rushing stats
                rusher_id = play.get('rusher_player_id')
                if rusher_id and not pd.isna(rusher_id):
                    if rusher_id not in player_stats:
                        player_stats[rusher_id] = {
                            'player_id': str(rusher_id),
                            'player_name': play.get('rusher_player_name'),
                            'position': 'RB',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[rusher_id]['games'].add(play.get('game_id'))
                    if play.get('rush_attempt') == 1:
                        player_stats[rusher_id]['rush_att'] += 1
                    player_stats[rusher_id]['rush_yds'] += int(play.get('rushing_yards') or 0)
                    if play.get('rush_touchdown') == 1:
                        player_stats[rusher_id]['rush_td'] += 1
                
                # Receiving stats
                receiver_id = play.get('receiver_player_id')
                if receiver_id and not pd.isna(receiver_id):
                    if receiver_id not in player_stats:
                        player_stats[receiver_id] = {
                            'player_id': str(receiver_id),
                            'player_name': play.get('receiver_player_name'),
                            'position': 'WR',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[receiver_id]['games'].add(play.get('game_id'))
                    player_stats[receiver_id]['targets'] += 1
                    if play.get('complete_pass') == 1:
                        player_stats[receiver_id]['rec'] += 1
                    player_stats[receiver_id]['rec_yds'] += int(play.get('receiving_yards') or 0)
                    if play.get('pass_touchdown') == 1:
                        player_stats[receiver_id]['rec_td'] += 1
            
            games_processed += 1
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error processing {rds_file.name}: {e}")
    
    # Insert aggregated stats into database
    if progress_callback:
        progress_callback(f"Inserting {len(player_stats)} player season stats for 2025...")
    
    imported = 0
    for player_id, stats in player_stats.items():
        # Convert games set to count
        stats['games'] = len(stats['games'])
        
        # Clean metadata
        metadata = {k: v for k, v in stats.items() if v is not None and v != 0}
        
        content_hash = compute_hash({
            'sport': 'nfl',
            'player_id': str(player_id),
            'season': 2025,
            'type': 'season_stats'
        })
        
        try:
            # Insert into results table (for game history queries)
            await conn.execute(
                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                   VALUES ($1, $2, 'nfl', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                sport_id, 2025, json.dumps(metadata), content_hash
            )
            
            # ALSO insert into stats table (for profile queries)
            # First try to look up entity_id from player_map
            entity_id = player_map.get(str(player_id))
            
            # If not in player_map, try to find by searching entities table
            if not entity_id:
                player_name = stats.get('player_name', '')
                if player_name:
                    entity_id = await conn.fetchval(
                        """SELECT id FROM entities 
                           WHERE sport_id = $1 AND name ILIKE $2
                           LIMIT 1""",
                        sport_id, f"%{player_name}%"
                    )
            
            if entity_id:
                # Build stats dict (exclude identifier fields)
                stats_dict = {k: v for k, v in metadata.items() 
                             if k not in ['player_id', 'player_name', 'games'] and v is not None}
                stats_dict['games'] = metadata.get('games', 0)  # Keep games count
                
                stats_hash = compute_hash({
                    'entity_id': entity_id,
                    'season': 2025,
                    'sport': 'nfl',
                    'stat_type': 'season'
                })
                
                await conn.execute(
                    """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                       VALUES ($1, $2, 'season', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET stats = EXCLUDED.stats""",
                    entity_id, 2025, json.dumps(stats_dict), stats_hash
                )
            
            imported += 1
        except Exception as e:
            logger.debug(f"Error inserting player {player_id}: {e}")
    
    logger.info(f"Processed {games_processed} games, imported {imported} player 2025 stats to results AND stats tables")
    return {"games_processed": games_processed, "imported": imported}


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
    """Import player season stats from nflverse player_stats_season_YYYY.csv files."""
    
    # Find all player_stats_season_YYYY.csv files (2020-2024)
    stats_files = sorted(NFLVERSE_DIR.glob("player_stats_season_*.csv"))
    
    if not stats_files:
        logger.warning("No player_stats_season_*.csv files found")
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
                    
                    # Create unique hash for this player-season (for results table)
                    content_hash = compute_hash({
                        'sport': 'nfl',
                        'player_id': str(player_id),
                        'season': season,
                        'type': 'season_stats'
                    })
                    
                    try:
                        # Insert into results table (for game history queries)
                        await conn.execute(
                            """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                               VALUES ($1, $2, 'nfl', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET metadata = EXCLUDED.metadata""",
                            sport_id, int(season), json.dumps(metadata), content_hash
                        )
                        
                        # ALSO insert into stats table (for profile queries)
                        # Look up entity_id from player_map
                        entity_id = player_map.get(str(player_id))
                        if entity_id:
                            # Build stats dict (exclude identifier fields)
                            stats_dict = {k: v for k, v in metadata.items() 
                                         if k not in ['player_id', 'player_name', 'player_display_name']}
                            
                            stats_hash = compute_hash({
                                'entity_id': entity_id,
                                'season': int(season),
                                'sport': 'nfl',
                                'stat_type': 'season'
                            })
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                                   VALUES ($1, $2, 'season', $3, $4)
                                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                                   DO UPDATE SET stats = EXCLUDED.stats""",
                                entity_id, int(season), json.dumps(stats_dict), stats_hash
                            )
                        
                        imported += 1
                    except Exception as e:
                        logger.debug(f"Error importing stat row: {e}")
                
                # Memory cleanup after each chunk
                gc.collect()
        
        except Exception as e:
            logger.error(f"Error processing {stats_file.name}: {e}")
    
    logger.info(f"Imported {imported} player season stats to results AND stats tables")
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
        
        # Step 5: Import player stats (2020-2024 from pre-computed season files)
        stats_result = await import_player_stats(conn, sport_id, player_map, progress_callback)
        results["games_imported"] = stats_result.get("imported", 0)
        results["stats_computed"] = stats_result.get("stats_computed", 0)
        
        # Step 6: Download and import 2025 PBP data (since nflverse doesn't publish season stats for ongoing season)
        if progress_callback:
            progress_callback("Downloading 2025 play-by-play data...")
        
        pbp_downloaded = await download_pbp_2025(progress_callback)
        results["pbp_2025_downloaded"] = len(pbp_downloaded)
        
        if pbp_downloaded:
            pbp_result = await import_pbp_2025(conn, sport_id, player_map, progress_callback)
            results["pbp_2025_imported"] = pbp_result.get("imported", 0)
            results["pbp_2025_games"] = pbp_result.get("games_processed", 0)
        
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
