"""
NFL Data Importer (Enhanced)
=============================
Downloads ALL nflverse data from GitHub releases and imports to PostgreSQL.
Also imports existing Kaggle data.

Data Sources:
- player_stats: Weekly player stats
- players: Player directory
- schedules: Games + betting lines
- ftn_charting: Advanced charting data
- weekly_rosters: Who played each week
"""

import asyncio
import logging
import json
import hashlib
import requests
from pathlib import Path
from datetime import datetime
import pandas as pd
import asyncpg

logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# nflverse GitHub releases - ALL available data
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_FILES = {
    "player_stats": f"{NFLVERSE_BASE}/player_stats/player_stats.csv",
    "players": f"{NFLVERSE_BASE}/players/players.csv",
    "schedules": f"{NFLVERSE_BASE}/schedules/schedules.csv",
    "rosters": f"{NFLVERSE_BASE}/weekly_rosters/roster_weekly_2024.csv",
}

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


async def ensure_sport_exists(conn) -> int:
    """Ensure NFL sport exists and return sport_id."""
    sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nfl'")
    if not sport_id:
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) VALUES ('nfl', '{}') RETURNING id"""
        )
    return sport_id


def safe_int(val):
    try:
        return int(float(val)) if pd.notna(val) else None
    except:
        return None


def safe_float(val):
    try:
        return round(float(val), 2) if pd.notna(val) else None
    except:
        return None


def safe_str(val):
    return str(val) if pd.notna(val) else None


async def import_players(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL players from nflverse players.csv."""
    players_file = NFLVERSE_DIR / "players.csv"
    if not players_file.exists():
        logger.warning("players.csv not found")
        return {"imported": 0, "player_map": {}}
    
    if progress_callback:
        progress_callback("Importing players...")
    
    df = pd.read_csv(players_file, low_memory=False)
    logger.info(f"Loaded {len(df)} players from nflverse")
    
    player_map = {}
    imported = 0
    
    for _, row in df.iterrows():
        player_id = safe_str(row.get('gsis_id') or row.get('player_id'))
        if not player_id:
            continue
        
        name = safe_str(row.get('display_name') or row.get('name'))
        if not name:
            continue
        
        metadata = {
            'player_id': player_id,
            'position': safe_str(row.get('position')),
            'team': safe_str(row.get('team_abbr')),
            'height': safe_str(row.get('height')),
            'weight': safe_int(row.get('weight')),
            'college': safe_str(row.get('college')),
            'draft_year': safe_int(row.get('draft_year')),
            'draft_round': safe_int(row.get('draft_round')),
            'draft_pick': safe_int(row.get('draft_pick')),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        content_hash = compute_hash({'sport': 'nfl', 'player_id': player_id})
        
        try:
            entity_id = await conn.fetchval(
                """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                   VALUES ($1, $2, 'player', 'nfl', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                   RETURNING id""",
                sport_id, name, json.dumps(metadata), content_hash
            )
            if entity_id:
                player_map[player_id] = entity_id
                imported += 1
        except Exception as e:
            logger.debug(f"Error importing player {name}: {e}")
    
    logger.info(f"Imported {imported} players")
    return {"imported": imported, "player_map": player_map}


async def import_schedules(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL schedules with betting lines."""
    schedules_file = NFLVERSE_DIR / "schedules.csv"
    if not schedules_file.exists():
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Importing schedules with betting lines...")
    
    df = pd.read_csv(schedules_file, low_memory=False)
    logger.info(f"Loaded {len(df)} games from schedules")
    
    imported = 0
    for _, row in df.iterrows():
        game_id = safe_str(row.get('game_id'))
        season = safe_int(row.get('season'))
        if not game_id or not season:
            continue
        
        metadata = {
            'game_id': game_id,
            'game_type': safe_str(row.get('game_type')),
            'week': safe_int(row.get('week')),
            'home_team': safe_str(row.get('home_team')),
            'away_team': safe_str(row.get('away_team')),
            'home_score': safe_int(row.get('home_score')),
            'away_score': safe_int(row.get('away_score')),
            'spread_line': safe_float(row.get('spread_line')),
            'total_line': safe_float(row.get('total_line')),
            'home_spread_odds': safe_int(row.get('home_spread_odds')),
            'away_spread_odds': safe_int(row.get('away_spread_odds')),
            'over_odds': safe_int(row.get('over_odds')),
            'under_odds': safe_int(row.get('under_odds')),
            'gameday': safe_str(row.get('gameday')),
            'stadium': safe_str(row.get('stadium')),
            'result': safe_int(row.get('result')),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        content_hash = compute_hash({'sport': 'nfl', 'game_id': game_id})
        
        try:
            await conn.execute(
                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                   VALUES ($1, $2, 'nfl_game', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                sport_id, season, json.dumps(metadata), content_hash
            )
            imported += 1
        except Exception as e:
            logger.debug(f"Error importing game {game_id}: {e}")
    
    logger.info(f"Imported {imported} games with betting lines")
    return {"imported": imported}


async def import_player_stats(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import weekly player stats from nflverse."""
    stats_file = NFLVERSE_DIR / "player_stats.csv"
    if not stats_file.exists():
        return {"imported": 0, "stats_computed": 0}
    
    if progress_callback:
        progress_callback("Importing player game stats...")
    
    df = pd.read_csv(stats_file, low_memory=False)
    logger.info(f"Loaded {len(df)} stat rows from nflverse")
    
    player_season_data = {}
    games_imported = 0
    
    for _, row in df.iterrows():
        player_id = safe_str(row.get('player_id'))
        if not player_id:
            continue
        
        season = safe_int(row.get('season'))
        week = safe_int(row.get('week'))
        if not season:
            continue
        
        player_name = safe_str(row.get('player_name') or row.get('player_display_name'))
        
        metadata = {
            'player_id': player_id,
            'player_name': player_name,
            'season': season,
            'week': week,
            'opponent': safe_str(row.get('opponent_team') or row.get('recent_team')),
            'position': safe_str(row.get('position')),
            'position_group': safe_str(row.get('position_group')),
            # Passing
            'pass_att': safe_int(row.get('attempts') or row.get('passing_att')),
            'pass_cmp': safe_int(row.get('completions') or row.get('passing_cmp')),
            'pass_yds': safe_int(row.get('passing_yards') or row.get('passing_yds')),
            'pass_td': safe_int(row.get('passing_tds') or row.get('passing_td')),
            'pass_int': safe_int(row.get('interceptions') or row.get('passing_int')),
            'passer_rating': safe_float(row.get('passer_rating')),
            # Rushing
            'rush_att': safe_int(row.get('carries') or row.get('rushing_att')),
            'rush_yds': safe_int(row.get('rushing_yards') or row.get('rushing_yds')),
            'rush_td': safe_int(row.get('rushing_tds') or row.get('rushing_td')),
            # Receiving
            'rec': safe_int(row.get('receptions')),
            'rec_yds': safe_int(row.get('receiving_yards') or row.get('receiving_yds')),
            'rec_td': safe_int(row.get('receiving_tds') or row.get('receiving_td')),
            'targets': safe_int(row.get('targets')),
            # Fantasy
            'fantasy_pts': safe_float(row.get('fantasy_points') or row.get('fantasy_points_ppr')),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        content_hash = compute_hash({
            'sport': 'nfl', 'player_id': player_id, 'season': season, 'week': week
        })
        
        try:
            await conn.execute(
                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                   VALUES ($1, $2, 'nfl', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                sport_id, season, json.dumps(metadata), content_hash
            )
            games_imported += 1
        except Exception as e:
            logger.debug(f"Error importing stat row: {e}")
        
        # Track for season aggregation
        entity_id = player_map.get(player_id)
        if entity_id:
            key = (entity_id, season)
            if key not in player_season_data:
                player_season_data[key] = []
            player_season_data[key].append(metadata)
    
    if progress_callback:
        progress_callback(f"Imported {games_imported} game stats. Computing season stats...")
    
    # Compute season stats
    stats_computed = 0
    for (entity_id, season), games in player_season_data.items():
        stats = compute_season_stats(games)
        stats_hash = compute_hash({'entity_id': entity_id, 'season': season, 'sport': 'nfl'})
        
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
            logger.debug(f"Error computing stats: {e}")
    
    return {"imported": games_imported, "stats_computed": stats_computed}


def compute_season_stats(games: list) -> dict:
    """Compute season aggregates from list of game stats."""
    stats = {
        'games': len(games),
        'pass_att': sum(g.get('pass_att') or 0 for g in games),
        'pass_cmp': sum(g.get('pass_cmp') or 0 for g in games),
        'pass_yds': sum(g.get('pass_yds') or 0 for g in games),
        'pass_td': sum(g.get('pass_td') or 0 for g in games),
        'pass_int': sum(g.get('pass_int') or 0 for g in games),
        'rush_att': sum(g.get('rush_att') or 0 for g in games),
        'rush_yds': sum(g.get('rush_yds') or 0 for g in games),
        'rush_td': sum(g.get('rush_td') or 0 for g in games),
        'rec': sum(g.get('rec') or 0 for g in games),
        'rec_yds': sum(g.get('rec_yds') or 0 for g in games),
        'rec_td': sum(g.get('rec_td') or 0 for g in games),
        'targets': sum(g.get('targets') or 0 for g in games),
        'fantasy_pts': round(sum(g.get('fantasy_pts') or 0 for g in games), 1),
    }
    
    # Per-game averages
    if stats['games'] > 0:
        stats['pass_yds_pg'] = round(stats['pass_yds'] / stats['games'], 1)
        stats['rush_yds_pg'] = round(stats['rush_yds'] / stats['games'], 1)
        stats['rec_yds_pg'] = round(stats['rec_yds'] / stats['games'], 1)
        stats['fantasy_pts_pg'] = round(stats['fantasy_pts'] / stats['games'], 1)
    
    if stats['pass_att'] > 0:
        stats['comp_pct'] = round(100 * stats['pass_cmp'] / stats['pass_att'], 1)
    
    if stats['rush_att'] > 0:
        stats['rush_ypc'] = round(stats['rush_yds'] / stats['rush_att'], 1)
    
    return stats


async def import_all_nfl(clear_existing: bool = False, progress_callback=None) -> dict:
    """Main entry: Download nflverse + import to PostgreSQL."""
    results = {
        "status": "success",
        "downloaded": [],
        "players_imported": 0,
        "games_imported": 0,
        "stats_computed": 0,
        "schedules_imported": 0,
        "errors": []
    }
    
    conn = None
    try:
        if progress_callback:
            progress_callback("Starting NFL data import...")
        
        downloaded = await download_nflverse(progress_callback)
        results["downloaded"] = downloaded
        
        if progress_callback:
            progress_callback("Connecting to database...")
        
        conn = await get_db_connection()
        sport_id = await ensure_sport_exists(conn)
        
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NFL data...")
            await conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
            await conn.execute("DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)", sport_id)
            await conn.execute("DELETE FROM entities WHERE sport_id = $1", sport_id)
        
        # Import players
        player_result = await import_players(conn, sport_id, progress_callback)
        results["players_imported"] = player_result.get("imported", 0)
        player_map = player_result.get("player_map", {})
        
        # Import schedules (with betting lines)
        schedule_result = await import_schedules(conn, sport_id, progress_callback)
        results["schedules_imported"] = schedule_result.get("imported", 0)
        
        # Import player stats
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
    async def test_import():
        def log_progress(msg):
            print(f"[PROGRESS] {msg}")
        result = await import_all_nfl(clear_existing=True, progress_callback=log_progress)
        print(f"Result: {result}")
    asyncio.run(test_import())
