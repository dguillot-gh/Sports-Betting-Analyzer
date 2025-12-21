"""
NBA Data Importer
==================
Imports NBA data from hoopR/sportsdataverse and existing Kaggle data.

Usage:
    await import_all_nba(clear_existing=False)
"""

import asyncio
import logging
import json
import hashlib
from pathlib import Path
from datetime import datetime
import pandas as pd
import asyncpg

logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# hoopR data (sportsdataverse GitHub)
HOOPR_BASE = "https://github.com/sportsdataverse/hoopR-data/releases/download"
HOOPR_FILES = {
    "player_box": f"{HOOPR_BASE}/player_box/player_box.parquet",
    "schedules": f"{HOOPR_BASE}/schedules/schedules.parquet",
}

# Local Kaggle data paths
DATA_DIR = Path("/app/data/nba")


def compute_hash(data: dict) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def get_db_connection():
    """Get database connection."""
    return await asyncpg.connect(DATABASE_URL)


async def ensure_sport_exists(conn) -> int:
    """Ensure NBA sport exists and return sport_id."""
    sport_id = await conn.fetchval(
        "SELECT id FROM sports WHERE name = 'nba'"
    )
    if not sport_id:
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) 
               VALUES ('nba', '{}') 
               RETURNING id"""
        )
    return sport_id


async def import_from_kaggle(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA data from existing Kaggle files."""
    results = {"players": 0, "games": 0}
    
    # Check for Player Per Game.csv
    player_file = DATA_DIR / "Player Per Game.csv"
    if player_file.exists():
        if progress_callback:
            progress_callback("Importing Kaggle Player Per Game data...")
        
        try:
            df = pd.read_csv(player_file, low_memory=False)
            logger.info(f"Loaded {len(df)} rows from Player Per Game.csv")
            
            # Import unique players
            player_map = {}
            for _, row in df.iterrows():
                player_id = row.get('player_id')
                if pd.isna(player_id):
                    continue
                
                name = row.get('player') or f"Player {player_id}"
                if pd.isna(name):
                    continue
                
                position = row.get('pos', '')
                team = row.get('team', '')
                season = row.get('season')
                
                metadata = {
                    'position': str(position) if not pd.isna(position) else None,
                    'team': str(team) if not pd.isna(team) else None,
                }
                
                content_hash = compute_hash({'sport': 'nba', 'player_id': str(player_id)})
                
                if str(player_id) not in player_map:
                    try:
                        entity_id = await conn.fetchval(
                            """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                               VALUES ($1, $2, 'player', 'nba', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                               RETURNING id""",
                            sport_id, str(name), json.dumps(metadata), content_hash
                        )
                        if entity_id:
                            player_map[str(player_id)] = entity_id
                            results["players"] += 1
                    except Exception as e:
                        logger.debug(f"Error importing player {name}: {e}")
            
            logger.info(f"Imported {results['players']} unique players")
            
            # Import season stats
            if progress_callback:
                progress_callback("Importing player season stats...")
            
            for _, row in df.iterrows():
                player_id = row.get('player_id')
                season = row.get('season')
                if pd.isna(player_id) or pd.isna(season):
                    continue
                
                entity_id = player_map.get(str(player_id))
                if not entity_id:
                    continue
                
                def safe_float(val):
                    try:
                        return round(float(val), 1) if not pd.isna(val) else None
                    except:
                        return None
                
                def safe_int(val):
                    try:
                        return int(float(val)) if not pd.isna(val) else None
                    except:
                        return None
                
                stats = {
                    'games': safe_int(row.get('g')),
                    'games_started': safe_int(row.get('gs')),
                    'minutes': safe_float(row.get('mp_per_game')),
                    # Scoring
                    'pts': safe_float(row.get('pts_per_game') or row.get('pts')),
                    'fg': safe_float(row.get('fg_per_game')),
                    'fga': safe_float(row.get('fga_per_game')),
                    'fg_pct': safe_float(row.get('fg_percent')),
                    'fg3': safe_float(row.get('x3p_per_game')),
                    'fg3a': safe_float(row.get('x3pa_per_game')),
                    'fg3_pct': safe_float(row.get('x3p_percent')),
                    'ft': safe_float(row.get('ft_per_game')),
                    'fta': safe_float(row.get('fta_per_game')),
                    'ft_pct': safe_float(row.get('ft_percent')),
                    # Rebounds
                    'reb': safe_float(row.get('trb_per_game')),
                    'oreb': safe_float(row.get('orb_per_game')),
                    'dreb': safe_float(row.get('drb_per_game')),
                    # Other
                    'ast': safe_float(row.get('ast_per_game')),
                    'stl': safe_float(row.get('stl_per_game')),
                    'blk': safe_float(row.get('blk_per_game')),
                    'tov': safe_float(row.get('tov_per_game')),
                    'pf': safe_float(row.get('pf_per_game')),
                }
                
                # Clean None values
                stats = {k: v for k, v in stats.items() if v is not None}
                
                stats_hash = compute_hash({
                    'entity_id': entity_id,
                    'season': int(season),
                    'sport': 'nba'
                })
                
                try:
                    await conn.execute(
                        """INSERT INTO stats (entity_id, season, series, stat_type, stats, content_hash)
                           VALUES ($1, $2, 'nba', 'season_per_game', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                           DO UPDATE SET stats = EXCLUDED.stats""",
                        int(entity_id), int(season), json.dumps(stats), stats_hash
                    )
                    results["games"] += 1
                except Exception as e:
                    logger.debug(f"Error importing season stats: {e}")
        
        except Exception as e:
            logger.error(f"Error reading Player Per Game.csv: {e}")
    
    return results


async def import_box_scores(conn, sport_id: int, progress_callback=None) -> dict:
    """Import game-by-game box scores for recent games display."""
    results = {"imported": 0}
    
    # Check for box_scores directory
    box_scores_dir = DATA_DIR / "box_scores"
    if not box_scores_dir.exists():
        logger.info("No box_scores directory found")
        return results
    
    if progress_callback:
        progress_callback("Importing box score data...")
    
    # Get player entities for mapping
    player_rows = await conn.fetch(
        "SELECT id, name FROM entities WHERE sport_id = $1 AND type = 'player'",
        sport_id
    )
    player_name_to_id = {row['name']: row['id'] for row in player_rows}
    
    # Process CSV files
    for csv_file in box_scores_dir.glob("*.csv"):
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            logger.info(f"Processing {csv_file.name} with {len(df)} rows")
            
            for _, row in df.iterrows():
                player_name = row.get('player') or row.get('Player')
                if pd.isna(player_name):
                    continue
                
                entity_id = player_name_to_id.get(str(player_name))
                if not entity_id:
                    continue
                
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
                
                game_date = row.get('game_date') or row.get('Date')
                opponent = row.get('opp') or row.get('Opp')
                
                metadata = {
                    'player_name': str(player_name),
                    'game_date': str(game_date) if not pd.isna(game_date) else None,
                    'opponent': str(opponent) if not pd.isna(opponent) else None,
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
                    'pf': safe_int(row.get('pf') or row.get('PF')),
                }
                
                # Clean None values
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                # Extract season from game date
                season = None
                if game_date and not pd.isna(game_date):
                    try:
                        year = int(str(game_date)[:4])
                        # NBA season spans two years
                        month = int(str(game_date)[5:7]) if len(str(game_date)) > 6 else 1
                        season = year if month >= 9 else year
                    except:
                        pass
                
                if not season:
                    continue
                
                content_hash = compute_hash({
                    'sport': 'nba',
                    'player_name': str(player_name),
                    'game_date': str(game_date)
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
                    logger.debug(f"Error importing box score: {e}")
        
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    logger.info(f"Imported {results['imported']} box score records")
    return results


async def import_all_nba(clear_existing: bool = False, progress_callback=None) -> dict:
    """
    Main entry point: Import NBA data from Kaggle and hoopR.
    
    Args:
        clear_existing: If True, delete existing NBA data first
        progress_callback: Optional function to report progress
    
    Returns:
        dict with import results
    """
    results = {
        "status": "success",
        "players_imported": 0,
        "season_stats_imported": 0,
        "box_scores_imported": 0,
        "errors": []
    }
    
    conn = None
    try:
        if progress_callback:
            progress_callback("Starting NBA data import...")
        
        # Connect to database
        conn = await get_db_connection()
        sport_id = await ensure_sport_exists(conn)
        
        # Clear existing if requested
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NBA data...")
            
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
        
        # Import from Kaggle files
        kaggle_result = await import_from_kaggle(conn, sport_id, progress_callback)
        results["players_imported"] = kaggle_result.get("players", 0)
        results["season_stats_imported"] = kaggle_result.get("games", 0)
        
        # Import box scores
        box_result = await import_box_scores(conn, sport_id, progress_callback)
        results["box_scores_imported"] = box_result.get("imported", 0)
        
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
