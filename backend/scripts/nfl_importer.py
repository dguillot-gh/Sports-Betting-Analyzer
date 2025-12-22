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

# nflverse GitHub releases
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# Get current year for dynamic file downloads
from datetime import datetime
CURRENT_YEAR = datetime.now().year

# nflverse files to download - includes year-specific player stats
NFLVERSE_FILES = {
    "players": f"{NFLVERSE_BASE}/players/players.csv",
    "schedules": f"{NFLVERSE_BASE}/schedules/schedules.csv",
}

# Add year-specific player stats files (recent years + current)
# nflverse stores weekly stats as stats_player_week_YYYY.csv
for year in range(2020, CURRENT_YEAR + 1):
    NFLVERSE_FILES[f"player_stats_{year}"] = f"{NFLVERSE_BASE}/player_stats/player_stats_{year}.csv"

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
    """Import player weekly stats from nflverse year-specific player_stats files with batching."""
    
    # Find all player_stats_YYYY.csv files
    stats_files = sorted(NFLVERSE_DIR.glob("player_stats_*.csv"))
    
    if not stats_files:
        # Fallback to old single file
        single_file = NFLVERSE_DIR / "player_stats.csv"
        if single_file.exists():
            stats_files = [single_file]
        else:
            logger.warning("No player_stats files found")
            return {"imported": 0, "stats_computed": 0}
    
    if progress_callback:
        progress_callback(f"Found {len(stats_files)} player stats files to import...")
    
    # Group by player + season for aggregation
    player_season_data = {}
    games_imported = 0
    batch_count = 0
    
    for stats_file in stats_files:
        if progress_callback:
            progress_callback(f"Processing {stats_file.name}...")
        
        for chunk in pd.read_csv(stats_file, low_memory=False, chunksize=BATCH_SIZE):
            batch_count += 1
            if progress_callback and batch_count % 10 == 0:
                progress_callback(f"Processing stats batch {batch_count} ({games_imported} games imported)...")
            
            for _, row in chunk.iterrows():
                player_id = row.get('player_id')
                if pd.isna(player_id):
                    continue
                
                entity_id = player_map.get(str(player_id))
                if not entity_id:
                    continue
                
                season = row.get('season')
                week = row.get('week')
                if pd.isna(season):
                    continue
                
                # Build game result metadata
                def safe_int(val):
                    try:
                        return int(float(val)) if not pd.isna(val) else None
                    except:
                        return None
                
                def safe_float(val):
                    try:
                        return round(float(val), 1) if not pd.isna(val) else None
                    except:
                        return None
                
                metadata = {
                    'player_id': str(player_id),
                    'player_name': row.get('player_name') or row.get('player_display_name'),
                    'season': safe_int(season),
                    'week': safe_int(week),
                    'opponent': row.get('opponent_team') or row.get('recent_team'),
                    'position': row.get('position'),
                    # Passing
                    'pass_att': safe_int(row.get('attempts') or row.get('passing_att')),
                    'pass_cmp': safe_int(row.get('completions') or row.get('passing_cmp')),
                    'pass_yds': safe_int(row.get('passing_yards') or row.get('passing_yds')),
                    'pass_td': safe_int(row.get('passing_tds') or row.get('passing_td')),
                    'pass_int': safe_int(row.get('interceptions') or row.get('passing_int')),
                    # Rushing
                    'rush_att': safe_int(row.get('carries') or row.get('rushing_att')),
                    'rush_yds': safe_int(row.get('rushing_yards') or row.get('rushing_yds')),
                    'rush_td': safe_int(row.get('rushing_tds') or row.get('rushing_td')),
                    # Receiving
                    'rec': safe_int(row.get('receptions')),
                    'rec_yds': safe_int(row.get('receiving_yards') or row.get('receiving_yds')),
                    'rec_td': safe_int(row.get('receiving_tds') or row.get('receiving_td')),
                    'targets': safe_int(row.get('targets')),
                    # Defense
                    'tackles': safe_int(row.get('tackles')),
                    'sacks': safe_float(row.get('sacks')),
                    'def_int': safe_int(row.get('def_interceptions') or row.get('interceptions')),
                }
                
                # Clean None values
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                # Insert as result
                content_hash = compute_hash({
                    'sport': 'nfl',
                    'player_id': str(player_id),
                    'season': season,
                    'week': week
                })
                
                try:
                    await conn.execute(
                        """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                           VALUES ($1, $2, 'nfl', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                           DO UPDATE SET metadata = EXCLUDED.metadata""",
                        sport_id, int(season), json.dumps(metadata), content_hash
                    )
                    games_imported += 1
                except Exception as e:
                    logger.debug(f"Error importing stat row: {e}")
                
                # Track for season aggregation
                key = (str(entity_id), int(season))
                if key not in player_season_data:
                    player_season_data[key] = []
                player_season_data[key].append(metadata)
    
    if progress_callback:
        progress_callback(f"Imported {games_imported} game stat rows. Computing season stats...")
    
    # Compute season stats
    stats_computed = 0
    for (entity_id, season), games in player_season_data.items():
        stats = compute_season_stats(games)
        
        stats_hash = compute_hash({
            'entity_id': entity_id,
            'season': season,
            'sport': 'nfl'
        })
        
        try:
            await conn.execute(
                """INSERT INTO stats (entity_id, season, series, stat_type, stats, content_hash)
                   VALUES ($1, $2, 'nfl', 'season_summary', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET stats = EXCLUDED.stats""",
                int(entity_id), season, json.dumps(stats), stats_hash
            )
            stats_computed += 1
        except Exception as e:
            logger.debug(f"Error computing stats for entity {entity_id}: {e}")
    
    logger.info(f"Imported {games_imported} game stats, computed {stats_computed} season summaries")
    return {"imported": games_imported, "stats_computed": stats_computed}


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
