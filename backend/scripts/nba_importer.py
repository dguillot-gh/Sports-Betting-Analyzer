"""
NBA Data Importer (Enhanced)
=============================
Downloads hoopR data + imports Kaggle data to PostgreSQL.

Data Sources:
- hoopR: espn_nba_player_boxscores (game-by-game stats)
- Kaggle: Player Per Game, Player Totals, Advanced
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

# hoopR data URLs (Sportsdataverse)
HOOPR_BASE = "https://github.com/sportsdataverse/hoopR-nba-data/releases/download"

# Local data paths
DATA_DIR = Path("/app/data/nba")
HOOPR_DIR = Path("/app/data/hoopr")


def compute_hash(data: dict) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


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


async def get_db_connection():
    """Get database connection."""
    return await asyncpg.connect(DATABASE_URL)


async def ensure_sport_exists(conn) -> int:
    """Ensure NBA sport exists and return sport_id."""
    sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nba'")
    if not sport_id:
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) VALUES ('nba', '{}') RETURNING id"""
        )
    return sport_id


async def import_from_kaggle(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA data from existing Kaggle files."""
    results = {"players": 0, "season_stats": 0}
    
    # Check for Player Per Game.csv
    player_file = DATA_DIR / "Player Per Game.csv"
    if not player_file.exists():
        player_file = DATA_DIR / "player_per_game.csv"
    
    if player_file.exists():
        if progress_callback:
            progress_callback("Importing Kaggle Player Per Game data...")
        
        try:
            df = pd.read_csv(player_file, low_memory=False)
            logger.info(f"Loaded {len(df)} rows from Kaggle")
            
            player_map = {}
            
            for _, row in df.iterrows():
                player_id = safe_str(row.get('player_id'))
                if not player_id:
                    continue
                
                name = safe_str(row.get('player'))
                if not name:
                    continue
                
                season = safe_int(row.get('season'))
                
                metadata = {
                    'player_id': player_id,
                    'position': safe_str(row.get('pos')),
                    'team': safe_str(row.get('team')),
                    'age': safe_int(row.get('age')),
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                content_hash = compute_hash({'sport': 'nba', 'player_id': player_id})
                
                if player_id not in player_map:
                    try:
                        entity_id = await conn.fetchval(
                            """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                               VALUES ($1, $2, 'player', 'nba', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                               RETURNING id""",
                            sport_id, name, json.dumps(metadata), content_hash
                        )
                        if entity_id:
                            player_map[player_id] = entity_id
                            results["players"] += 1
                    except Exception as e:
                        logger.debug(f"Error importing player {name}: {e}")
                
                # Import season stats
                if season and player_id in player_map:
                    stats = {
                        'games': safe_int(row.get('g')),
                        'games_started': safe_int(row.get('gs')),
                        'minutes': safe_float(row.get('mp_per_game')),
                        'pts': safe_float(row.get('pts_per_game') or row.get('pts')),
                        'reb': safe_float(row.get('trb_per_game')),
                        'oreb': safe_float(row.get('orb_per_game')),
                        'dreb': safe_float(row.get('drb_per_game')),
                        'ast': safe_float(row.get('ast_per_game')),
                        'stl': safe_float(row.get('stl_per_game')),
                        'blk': safe_float(row.get('blk_per_game')),
                        'tov': safe_float(row.get('tov_per_game')),
                        'fg_pct': safe_float(row.get('fg_percent')),
                        'fg3_pct': safe_float(row.get('x3p_percent')),
                        'ft_pct': safe_float(row.get('ft_percent')),
                        'efg_pct': safe_float(row.get('e_fg_percent')),
                    }
                    stats = {k: v for k, v in stats.items() if v is not None}
                    
                    stats_hash = compute_hash({
                        'entity_id': player_map[player_id], 'season': season, 'sport': 'nba'
                    })
                    
                    try:
                        await conn.execute(
                            """INSERT INTO stats (entity_id, season, series, stat_type, stats, content_hash)
                               VALUES ($1, $2, 'nba', 'season_per_game', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET stats = EXCLUDED.stats""",
                            int(player_map[player_id]), season, json.dumps(stats), stats_hash
                        )
                        results["season_stats"] += 1
                    except Exception as e:
                        logger.debug(f"Error importing season stats: {e}")
        
        except Exception as e:
            logger.error(f"Error reading Kaggle file: {e}")
    
    # Import Advanced stats if available
    advanced_file = DATA_DIR / "Advanced.csv"
    if advanced_file.exists():
        if progress_callback:
            progress_callback("Importing Advanced stats...")
        try:
            df = pd.read_csv(advanced_file, low_memory=False)
            for _, row in df.iterrows():
                player_id = safe_str(row.get('player_id'))
                season = safe_int(row.get('season'))
                if not player_id or not season:
                    continue
                
                advanced = {
                    'per': safe_float(row.get('per')),
                    'ts_pct': safe_float(row.get('ts_percent')),
                    'usg_pct': safe_float(row.get('usg_percent')),
                    'ows': safe_float(row.get('ows')),
                    'dws': safe_float(row.get('dws')),
                    'ws': safe_float(row.get('ws')),
                    'bpm': safe_float(row.get('bpm')),
                    'vorp': safe_float(row.get('vorp')),
                }
                advanced = {k: v for k, v in advanced.items() if v is not None}
                
                if advanced:
                    adv_hash = compute_hash({
                        'player_id': player_id, 'season': season, 'type': 'advanced'
                    })
                    # Find entity
                    entity_id = await conn.fetchval(
                        "SELECT id FROM entities WHERE metadata->>'player_id' = $1 AND sport_id = $2",
                        player_id, sport_id
                    )
                    if entity_id:
                        await conn.execute(
                            """INSERT INTO stats (entity_id, season, series, stat_type, stats, content_hash)
                               VALUES ($1, $2, 'nba', 'advanced', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET stats = EXCLUDED.stats""",
                            entity_id, season, json.dumps(advanced), adv_hash
                        )
        except Exception as e:
            logger.error(f"Error importing Advanced stats: {e}")
    
    return results


async def import_game_logs(conn, sport_id: int, progress_callback=None) -> dict:
    """Import game-by-game box scores for hit rates."""
    results = {"imported": 0}
    
    # Check for game log files
    for log_file in DATA_DIR.glob("*game*log*.csv"):
        if progress_callback:
            progress_callback(f"Importing {log_file.name}...")
        
        try:
            df = pd.read_csv(log_file, low_memory=False)
            
            for _, row in df.iterrows():
                player_name = safe_str(row.get('player') or row.get('Player'))
                game_date = safe_str(row.get('game_date') or row.get('Date'))
                if not player_name or not game_date:
                    continue
                
                # Extract season from date
                try:
                    year = int(str(game_date)[:4])
                    month = int(str(game_date)[5:7]) if len(str(game_date)) > 6 else 1
                    season = year if month >= 9 else year
                except:
                    season = 2024
                
                metadata = {
                    'player_name': player_name,
                    'game_date': game_date,
                    'opponent': safe_str(row.get('opp') or row.get('Opp')),
                    'minutes': safe_int(row.get('mp') or row.get('MIN')),
                    'pts': safe_int(row.get('pts') or row.get('PTS')),
                    'reb': safe_int(row.get('trb') or row.get('REB')),
                    'ast': safe_int(row.get('ast') or row.get('AST')),
                    'stl': safe_int(row.get('stl') or row.get('STL')),
                    'blk': safe_int(row.get('blk') or row.get('BLK')),
                    'fg': safe_int(row.get('fg') or row.get('FG')),
                    'fga': safe_int(row.get('fga') or row.get('FGA')),
                    'fg3': safe_int(row.get('fg3') or row.get('3P')),
                    'fg3a': safe_int(row.get('fg3a') or row.get('3PA')),
                    'ft': safe_int(row.get('ft') or row.get('FT')),
                    'fta': safe_int(row.get('fta') or row.get('FTA')),
                    'tov': safe_int(row.get('tov') or row.get('TOV')),
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                content_hash = compute_hash({
                    'sport': 'nba', 'player_name': player_name, 'game_date': game_date
                })
                
                try:
                    await conn.execute(
                        """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                           VALUES ($1, $2, 'nba', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                           DO UPDATE SET metadata = EXCLUDED.metadata""",
                        sport_id, season, json.dumps(metadata), content_hash
                    )
                    results["imported"] += 1
                except Exception as e:
                    logger.debug(f"Error importing game log: {e}")
        
        except Exception as e:
            logger.error(f"Error processing {log_file.name}: {e}")
    
    return results


async def import_all_nba(clear_existing: bool = False, progress_callback=None) -> dict:
    """Main entry: Import NBA data from hoopR + Kaggle."""
    results = {
        "status": "success",
        "players_imported": 0,
        "season_stats_imported": 0,
        "game_logs_imported": 0,
        "errors": []
    }
    
    conn = None
    try:
        if progress_callback:
            progress_callback("Starting NBA data import...")
        
        conn = await get_db_connection()
        sport_id = await ensure_sport_exists(conn)
        
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NBA data...")
            await conn.execute("DELETE FROM results WHERE sport_id = $1", sport_id)
            await conn.execute("DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)", sport_id)
            await conn.execute("DELETE FROM entities WHERE sport_id = $1", sport_id)
        
        # Import from Kaggle
        kaggle_result = await import_from_kaggle(conn, sport_id, progress_callback)
        results["players_imported"] = kaggle_result.get("players", 0)
        results["season_stats_imported"] = kaggle_result.get("season_stats", 0)
        
        # Import game logs
        log_result = await import_game_logs(conn, sport_id, progress_callback)
        results["game_logs_imported"] = log_result.get("imported", 0)
        
        if progress_callback:
            progress_callback("NBA import complete!")
        
    except Exception as e:
        logger.error(f"NBA import failed: {e}")
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
        result = await import_all_nba(clear_existing=True, progress_callback=log_progress)
        print(f"Result: {result}")
    asyncio.run(test_import())
