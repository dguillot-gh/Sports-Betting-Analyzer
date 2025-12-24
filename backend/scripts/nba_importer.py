"""
Downloads hoopR data + imports Kaggle data to PostgreSQL.

Data Sources:
- sportsdataverse: espn_nba_player_box (game-by-game stats)
- Kaggle: Player Per Game, Player Totals, Advanced (fallback)
NBA Data Importer
Imports NBA data from hoopR/sportsdataverse and existing Kaggle data.

Usage:
    await import_all_nba(clear_existing=False)
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

# NOTE: hoopR-nba-data repository does NOT have GitHub releases.
# The sportsdataverse Python package accesses data via internal APIs.
# We'll skip direct parquet downloads and rely on:
# 1. sportsdataverse Python API (if XGBoost compatible)
# 2. Basketball Reference (primary - season stats + advanced)
# 3. Kaggle fallback (historical data)

# Parquet download is deprecated - no release assets available
HOOPDATA_FILES = {}

# Local data paths
DATA_DIR = Path("/app/data/nba")
HOOPDATA_DIR = Path("/app/data/hoopdata")



async def download_hoopdata(progress_callback=None):
    """Download latest hoopR/sportsdataverse NBA data."""
    HOOPDATA_DIR.mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    for name, url in HOOPDATA_FILES.items():
        try:
            if progress_callback:
                progress_callback(f"Downloading {name}...")
            
            response = requests.get(url, timeout=120)
            if response.status_code == 200:
                file_path = HOOPDATA_DIR / f"{name}.parquet"
                file_path.write_bytes(response.content)
                downloaded.append(name)
                logger.info(f"Downloaded {name} ({len(response.content)} bytes)")
            else:
                logger.warning(f"Failed to download {name}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {name}: {e}")
    
    return downloaded


async def import_via_sportsdataverse_api(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA data using sportsdataverse Python API directly."""
    try:
        from sportsdataverse.nba import load_nba_player_boxscore
    except ImportError:
        logger.warning("sportsdataverse not installed - skipping API import")
        return {"players": 0, "games": 0}
    except Exception as e:
        # Handle XGBoost model loading errors from sportsdataverse
        if "XGBoost" in str(e) or "Failed to load model" in str(e):
            logger.warning(f"sportsdataverse has XGBoost compatibility issues - using parquet fallback: {e}")
            return {"players": 0, "games": 0}
        raise
    
    if progress_callback:
        progress_callback("Loading NBA data via sportsdataverse API...")
    
    results = {"players": 0, "games": 0}
    player_map = {}
    
    try:
        # Load player boxscores for recent seasons
        years_to_load = [2023, 2024, 2025]
        
        for year in years_to_load:
            try:
                if progress_callback:
                    progress_callback(f"Loading {year} NBA boxscores via sportsdataverse...")
                
                df = load_nba_player_boxscore(seasons=[year], return_as_pandas=True)
                
                if df is None or len(df) == 0:
                    logger.warning(f"No sportsdataverse data for {year}")
                    continue
                
                if progress_callback:
                    progress_callback(f"Processing {len(df)} boxscore entries from {year}...")
                
                logger.info(f"Loaded {len(df)} boxscores for {year} via sportsdataverse API")
                
                # Process in batches
                batch_size = 100
                for start_idx in range(0, len(df), batch_size):
                    batch = df.iloc[start_idx:start_idx + batch_size]
                    
                    for _, row in batch.iterrows():
                        # Get player info
                        player_id = row.get('athlete_id') or row.get('player_id')
                        player_name = row.get('athlete_display_name') or row.get('athlete_name')
                        
                        if pd.isna(player_id) or pd.isna(player_name):
                            continue
                        
                        # Create/update player entity if not seen
                        if str(player_id) not in player_map:
                            position = row.get('athlete_position_name', '')
                            team = row.get('team_short_display_name') or row.get('team_abbreviation', '')
                            
                            metadata = {
                                'position': str(position) if not pd.isna(position) else None,
                                'team': str(team) if not pd.isna(team) else None,
                            }
                            
                            content_hash = compute_hash({'sport': 'nba', 'player_id': str(player_id)})
                            
                            try:
                                entity_id = await conn.fetchval(
                                    """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                                       VALUES ($1, $2, 'player', 'nba', $3, $4)
                                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                                       DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                                       RETURNING id""",
                                    sport_id, str(player_name), json.dumps(metadata), content_hash
                                )
                                if entity_id:
                                    player_map[str(player_id)] = entity_id
                                    results["players"] += 1
                            except Exception as e:
                                logger.debug(f"Error importing player {player_name}: {e}")
                        
                        # Import game result
                        def safe_int(val):
                            try:
                                return int(float(val)) if not pd.isna(val) else None
                            except:
                                return None
                        
                        game_id = row.get('game_id')
                        game_date = row.get('game_date') or row.get('game_date_time')
                        
                        game_metadata = {
                            'player_name': str(player_name),
                            'game_id': str(game_id) if not pd.isna(game_id) else None,
                            'game_date': str(game_date) if not pd.isna(game_date) else None,
                            'team': str(row.get('team_short_display_name', '')) if not pd.isna(row.get('team_short_display_name')) else None,
                            'opponent': str(row.get('opponent_team_short_display_name', '')) if not pd.isna(row.get('opponent_team_short_display_name')) else None,
                            'minutes': safe_int(row.get('minutes')),
                            'pts': safe_int(row.get('points')),
                            'reb': safe_int(row.get('rebounds')),
                            'ast': safe_int(row.get('assists')),
                            'stl': safe_int(row.get('steals')),
                            'blk': safe_int(row.get('blocks')),
                            'fg': safe_int(row.get('field_goals_made')),
                            'fga': safe_int(row.get('field_goals_attempted')),
                            'fg3': safe_int(row.get('three_point_field_goals_made')),
                            'fg3a': safe_int(row.get('three_point_field_goals_attempted')),
                            'ft': safe_int(row.get('free_throws_made')),
                            'fta': safe_int(row.get('free_throws_attempted')),
                            'tov': safe_int(row.get('turnovers')),
                            'source': 'sportsdataverse'
                        }
                        
                        game_metadata = {k: v for k, v in game_metadata.items() if v is not None}
                        
                        game_hash = compute_hash({
                            'sport': 'nba',
                            'player_id': str(player_id),
                            'game_id': str(game_id) if game_id else str(game_date)
                        })
                        
                        try:
                            await conn.execute(
                                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                                   VALUES ($1, $2, 'nba', $3, $4)
                                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                                sport_id, year, json.dumps(game_metadata), game_hash
                            )
                            results["games"] += 1
                        except Exception as e:
                            logger.debug(f"Error importing game: {e}")
                    
                    gc.collect()
                    
            except Exception as e:
                logger.warning(f"Error loading {year} from sportsdataverse: {e}")
                continue
        
        logger.info(f"Imported {results['players']} players, {results['games']} games via sportsdataverse API")
        return results
        
    except Exception as e:
        logger.error(f"Error in sportsdataverse API import: {e}")
        return results


def compute_hash(data: dict) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def import_season_stats_via_basketball_reference(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import NBA season stats + advanced stats from Basketball Reference."""
    try:
        from basketball_reference_web_scraper import client
    except ImportError:
        logger.warning("basketball_reference_web_scraper not installed - skipping BR import")
        return {"imported": 0, "stats_computed": 0}
    
    if progress_callback:
        progress_callback("Loading NBA season stats from Basketball Reference...")
    
    imported = 0
    stats_computed = 0
    
    # Years to import from Basketball Reference
    years_to_import = [2021, 2022, 2023, 2024, 2025]
    
    for year in years_to_import:
        try:
            if progress_callback:
                progress_callback(f"Fetching {year} season stats from Basketball Reference...")
            
            # Get basic season totals
            try:
                season_totals = client.players_season_totals(season_end_year=year)
            except Exception as e:
                logger.warning(f"Could not fetch {year} season totals: {e}")
                continue
            
            # Try to get advanced stats too
            advanced_by_slug = {}
            try:
                advanced_stats = client.players_advanced_season_totals(season_end_year=year)
                advanced_by_slug = {p.get('slug', p.get('name', '').lower().replace(' ', '-')): p for p in advanced_stats}
                logger.info(f"Loaded {len(advanced_stats)} advanced stats for {year}")
            except Exception as e:
                logger.warning(f"Could not fetch advanced stats for {year}: {e}")
            
            for player in season_totals:
                player_name = player.get('name', '')
                slug = player.get('slug', player_name.lower().replace(' ', '-'))
                
                if not player_name:
                    continue
                
                # Build stats metadata
                def safe_val(val):
                    if val is None:
                        return None
                    if hasattr(val, 'value'):
                        return str(val.value)
                    if isinstance(val, float):
                        return int(val) if val == int(val) else round(val, 2)
                    return val
                
                metadata = {
                    'player_name': player_name,
                    'slug': slug,
                    'season': year,
                    'source': 'basketball_reference',
                    'team': safe_val(player.get('team')),
                    'games_played': safe_val(player.get('games_played')),
                    'games_started': safe_val(player.get('games_started')),
                    'minutes_played': safe_val(player.get('minutes_played')),
                    # Scoring
                    'points': safe_val(player.get('points')),
                    'field_goals_made': safe_val(player.get('made_field_goals')),
                    'field_goals_attempted': safe_val(player.get('attempted_field_goals')),
                    'three_pointers_made': safe_val(player.get('made_three_point_field_goals')),
                    'three_pointers_attempted': safe_val(player.get('attempted_three_point_field_goals')),
                    'free_throws_made': safe_val(player.get('made_free_throws')),
                    'free_throws_attempted': safe_val(player.get('attempted_free_throws')),
                    # Rebounds
                    'offensive_rebounds': safe_val(player.get('offensive_rebounds')),
                    'defensive_rebounds': safe_val(player.get('defensive_rebounds')),
                    # Other
                    'assists': safe_val(player.get('assists')),
                    'steals': safe_val(player.get('steals')),
                    'blocks': safe_val(player.get('blocks')),
                    'turnovers': safe_val(player.get('turnovers')),
                    'personal_fouls': safe_val(player.get('personal_fouls')),
                }
                
                # Add advanced stats if available (PER, TS%, etc.)
                adv = advanced_by_slug.get(slug, {})
                if adv:
                    metadata.update({
                        'player_efficiency_rating': safe_val(adv.get('player_efficiency_rating')),
                        'true_shooting_percentage': safe_val(adv.get('true_shooting_percentage')),
                        'usage_percentage': safe_val(adv.get('usage_percentage')),
                        'offensive_win_shares': safe_val(adv.get('offensive_win_shares')),
                        'defensive_win_shares': safe_val(adv.get('defensive_win_shares')),
                        'win_shares': safe_val(adv.get('win_shares')),
                        'box_plus_minus': safe_val(adv.get('box_plus_minus')),
                        'value_over_replacement_player': safe_val(adv.get('value_over_replacement_player')),
                    })
                
                # Remove None values
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                content_hash = compute_hash({
                    'sport': 'nba',
                    'player_slug': slug,
                    'season': year,
                    'type': 'br_season_stats'
                })
                
                try:
                    # Insert into results table
                    await conn.execute(
                        """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                           VALUES ($1, $2, 'nba', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                           DO UPDATE SET metadata = EXCLUDED.metadata""",
                        sport_id, year, json.dumps(metadata), content_hash
                    )
                    
                    # Also insert into stats table for profile queries
                    entity_id = player_map.get(slug) or player_map.get(player_name)
                    
                    if not entity_id:
                        entity_id = await conn.fetchval(
                            """SELECT id FROM entities 
                               WHERE sport_id = $1 AND name ILIKE $2
                               LIMIT 1""",
                            sport_id, f"%{player_name}%"
                        )
                    
                    if entity_id:
                        stats_dict = {k: v for k, v in metadata.items() 
                                     if k not in ['player_name', 'slug', 'source']}
                        
                        stats_hash = compute_hash({
                            'entity_id': entity_id,
                            'season': year,
                            'sport': 'nba',
                            'stat_type': 'br_season'
                        })
                        
                        await conn.execute(
                            """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                               VALUES ($1, $2, 'season', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET stats = EXCLUDED.stats""",
                            entity_id, year, json.dumps(stats_dict), stats_hash
                        )
                        stats_computed += 1
                    
                    imported += 1
                    
                except Exception as e:
                    logger.debug(f"Error importing BR stats for {player_name}: {e}")
            
            # Be nice to Basketball Reference - add delay between years
            await asyncio.sleep(2)
            gc.collect()
            
        except Exception as e:
            logger.warning(f"Error fetching {year} stats from BR: {e}")
            continue
    
    logger.info(f"Imported {imported} NBA season stats from Basketball Reference, {stats_computed} stats table entries")
    return {"imported": imported, "stats_computed": stats_computed}


async def import_from_hoopdata(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA data from downloaded sportsdataverse parquet files."""
    results = {"players": 0, "games": 0}
    
    # Find all player_box_YYYY.parquet files
    parquet_files = sorted(HOOPDATA_DIR.glob("player_box_*.parquet"))
    
    if not parquet_files:
        logger.info("No hoopdata parquet files found, will use Kaggle fallback")
        return results
    
    if progress_callback:
        progress_callback(f"Found {len(parquet_files)} hoopdata files to import...")
    
    # Track unique players
    player_map = {}
    
    for pq_file in parquet_files:
        try:
            if progress_callback:
                progress_callback(f"Processing {pq_file.name}...")
            
            # Read parquet file
            df = pd.read_parquet(pq_file)
            logger.info(f"Loaded {len(df)} rows from {pq_file.name}")
            
            # Process in batches
            batch_size = 100
            for start_idx in range(0, len(df), batch_size):
                batch = df.iloc[start_idx:start_idx + batch_size]
                
                for _, row in batch.iterrows():
                    # Get player info
                    player_id = row.get('athlete_id') or row.get('player_id')
                    player_name = row.get('athlete_display_name') or row.get('player_name')
                    
                    if pd.isna(player_id) or pd.isna(player_name):
                        continue
                    
                    # Create/update player entity if not seen
                    if str(player_id) not in player_map:
                        position = row.get('athlete_position_name', '')
                        team = row.get('team_short_display_name') or row.get('team_abbreviation', '')
                        
                        metadata = {
                            'position': str(position) if not pd.isna(position) else None,
                            'team': str(team) if not pd.isna(team) else None,
                        }
                        
                        content_hash = compute_hash({'sport': 'nba', 'player_id': str(player_id)})
                        
                        try:
                            entity_id = await conn.fetchval(
                                """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                                   VALUES ($1, $2, 'player', 'nba', $3, $4)
                                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                                   DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                                   RETURNING id""",
                                sport_id, str(player_name), json.dumps(metadata), content_hash
                            )
                            if entity_id:
                                player_map[str(player_id)] = entity_id
                                results["players"] += 1
                        except Exception as e:
                            logger.debug(f"Error importing player {player_name}: {e}")
                    
                    # Import game result
                    def safe_int(val):
                        try:
                            return int(float(val)) if not pd.isna(val) else None
                        except:
                            return None
                    
                    game_date = row.get('game_date') or row.get('game_date_time')
                    season = row.get('season') or row.get('season_type')
                    
                    # Extract season year from game date if needed
                    if pd.isna(season) and not pd.isna(game_date):
                        try:
                            year = int(str(game_date)[:4])
                            month = int(str(game_date)[5:7]) if len(str(game_date)) > 6 else 1
                            season = year if month >= 9 else year
                        except:
                            continue
                    
                    if pd.isna(season):
                        continue
                    
                    opponent = row.get('opponent_team_short_display_name') or row.get('opponent_abbreviation', '')
                    
                    game_metadata = {
                        'player_name': str(player_name),
                        'game_date': str(game_date) if not pd.isna(game_date) else None,
                        'opponent': str(opponent) if not pd.isna(opponent) else None,
                        'minutes': safe_int(row.get('minutes') or row.get('min')),
                        'pts': safe_int(row.get('points') or row.get('pts')),
                        'reb': safe_int(row.get('rebounds') or row.get('reb')),
                        'ast': safe_int(row.get('assists') or row.get('ast')),
                        'stl': safe_int(row.get('steals') or row.get('stl')),
                        'blk': safe_int(row.get('blocks') or row.get('blk')),
                        'fg': safe_int(row.get('field_goals_made') or row.get('fg')),
                        'fga': safe_int(row.get('field_goals_attempted') or row.get('fga')),
                        'fg3': safe_int(row.get('three_point_field_goals_made') or row.get('fg3')),
                        'fg3a': safe_int(row.get('three_point_field_goals_attempted') or row.get('fg3a')),
                        'ft': safe_int(row.get('free_throws_made') or row.get('ft')),
                        'fta': safe_int(row.get('free_throws_attempted') or row.get('fta')),
                        'tov': safe_int(row.get('turnovers') or row.get('to')),
                    }
                    
                    # Clean None values
                    game_metadata = {k: v for k, v in game_metadata.items() if v is not None}
                    
                    game_hash = compute_hash({
                        'sport': 'nba',
                        'player_id': str(player_id),
                        'game_date': str(game_date)
                    })
                    
                    try:
                        await conn.execute(
                            """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                               VALUES ($1, $2, 'nba', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET metadata = EXCLUDED.metadata""",
                            sport_id, int(season), json.dumps(game_metadata), game_hash
                        )
                        results["games"] += 1
                    except Exception as e:
                        logger.debug(f"Error importing game: {e}")
                
                # Free memory periodically
                gc.collect()
                
        except Exception as e:
            logger.error(f"Error processing {pq_file.name}: {e}")
    
    logger.info(f"Imported {results['players']} players, {results['games']} games from hoopdata")
    return results


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


# Batch size - REDUCED for low memory servers (2GB RAM)
# Process 50 rows at a time to prevent memory crashes
BATCH_SIZE = 50


async def import_from_kaggle(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA data from existing Kaggle files with batching."""
    results = {"players": 0, "games": 0}
    
    # Check for Player Per Game.csv
    player_file = DATA_DIR / "Player Per Game.csv"
    if player_file.exists():
        if progress_callback:
            progress_callback("Importing Kaggle Player Per Game data...")
        
        try:
            # Read in chunks to save memory
            player_map = {}
            batch_count = 0
            
            for chunk in pd.read_csv(player_file, low_memory=False, chunksize=BATCH_SIZE):
                batch_count += 1
                if progress_callback and batch_count % 5 == 0:
                    progress_callback(f"Processing player batch {batch_count} ({results['players']} players imported)...")
                
                for _, row in chunk.iterrows():
                    player_id = row.get('player_id')
                    if pd.isna(player_id):
                        continue
                    
                    name = row.get('player') or f"Player {player_id}"
                    if pd.isna(name):
                        continue
                    
                    position = row.get('pos', '')
                    team = row.get('team', '')
                    
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
                
                # Free memory after each batch
                gc.collect()
            
            logger.info(f"Imported {results['players']} unique players")
            
            # Import season stats (second pass with chunked reading)
            if progress_callback:
                progress_callback("Importing player season stats...")
            
            stats_batch_count = 0
            for chunk in pd.read_csv(player_file, low_memory=False, chunksize=BATCH_SIZE):
                stats_batch_count += 1
                if progress_callback and stats_batch_count % 10 == 0:
                    progress_callback(f"Processing stats batch {stats_batch_count} ({results['games']} stats imported)...")
                
                for _, row in chunk.iterrows():
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
                
                # Free memory after each batch
                gc.collect()
        
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
    
    # Process CSV files with chunked reading
    for csv_file in box_scores_dir.glob("*.csv"):
        try:
            logger.info(f"Processing {csv_file.name} in chunks...")
            chunk_count = 0
            
            for chunk in pd.read_csv(csv_file, low_memory=False, chunksize=BATCH_SIZE):
                chunk_count += 1
                
                for _, row in chunk.iterrows():
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
                
                # Free memory after each chunk
                gc.collect()
        
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    logger.info(f"Imported {results['imported']} box score records")
    return results


async def import_all_nba(clear_existing: bool = False, progress_callback=None) -> dict:
    """
    Main entry point: Import NBA data from sportsdataverse and Kaggle.
    
    Data flow:
    1. Download latest data from sportsdataverse (hoopR releases)
    2. Import players and game stats from parquet files
    3. Fallback to Kaggle files if sportsdataverse download fails
    
    Args:
        clear_existing: If True, delete existing NBA data first
        progress_callback: Optional function to report progress
    
    Returns:
        dict with import results
    """
    results = {
        "status": "success",
        "downloaded": [],
        "players_imported": 0,
        "games_imported": 0,
        "season_stats_imported": 0,
        "box_scores_imported": 0,
        "br_stats_imported": 0,
        "br_stats_computed": 0,
        "errors": []
    }
    
    conn = None
    try:
        if progress_callback:
            progress_callback("Starting NBA data import...")
        
        # Step 1: Download latest data from sportsdataverse
        if progress_callback:
            progress_callback("Downloading latest NBA data from sportsdataverse...")
        
        downloaded = await download_hoopdata(progress_callback)
        results["downloaded"] = downloaded
        
        if progress_callback:
            progress_callback(f"Downloaded {len(downloaded)} files from sportsdataverse")
        
        # Connect to database
        conn = await get_db_connection()
        
        # Ensure schema has required columns
        await ensure_schema(conn)
        
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
        
        # Step 2: Import via sportsdataverse Python API (preferred method)
        player_map = {}
        sdv_result = await import_via_sportsdataverse_api(conn, sport_id, progress_callback)
        results["players_imported"] = sdv_result.get("players", 0)
        results["games_imported"] = sdv_result.get("games", 0)
        
        # Step 3: Fallback to downloaded parquet files if API didn't return data
        if results["games_imported"] == 0 and downloaded:
            hoopdata_result = await import_from_hoopdata(conn, sport_id, progress_callback)
            results["players_imported"] += hoopdata_result.get("players", 0)
            results["games_imported"] += hoopdata_result.get("games", 0)
        
        # Step 4: Fallback/supplement with Kaggle files
        kaggle_result = await import_from_kaggle(conn, sport_id, progress_callback)
        results["season_stats_imported"] = kaggle_result.get("games", 0)
        
        # If no sportsdataverse players, count Kaggle players
        if results["players_imported"] == 0:
            results["players_imported"] = kaggle_result.get("players", 0)
        
        # Import box scores from local files if available
        box_result = await import_box_scores(conn, sport_id, progress_callback)
        results["box_scores_imported"] = box_result.get("imported", 0)
        
        # Step 6: Import from Basketball Reference (season totals + advanced stats)
        # Build player_map from entities table for stats linking
        player_rows = await conn.fetch(
            "SELECT id, name, metadata FROM entities WHERE sport_id = $1 AND type = 'player'",
            sport_id
        )
        for row in player_rows:
            player_map[row['name']] = row['id']
            if row['metadata']:
                try:
                    meta = json.loads(row['metadata'])
                    if meta.get('slug'):
                        player_map[meta['slug']] = row['id']
                except:
                    pass
        
        br_result = await import_season_stats_via_basketball_reference(conn, sport_id, player_map, progress_callback)
        results["br_stats_imported"] = br_result.get("imported", 0)
        results["br_stats_computed"] = br_result.get("stats_computed", 0)
        
        # Step 7: Import game schedules using nba_api
        schedule_result = await import_schedules_via_nba_api(conn, sport_id, progress_callback)
        results["schedules_imported"] = schedule_result.get("imported", 0)
        
        # Step 8: Import player game logs for hit rate calculations
        game_log_result = await import_game_logs_via_nba_api(conn, sport_id, progress_callback)
        results["game_logs_imported"] = game_log_result.get("imported", 0)
        
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


async def import_schedules_via_nba_api(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA game schedules using nba_api's LeagueGameFinder."""
    try:
        from nba_api.stats.endpoints import leaguegamefinder
        import time
    except ImportError:
        logger.warning("nba_api not installed - skipping schedule import")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Loading NBA schedules via nba_api...")
    
    imported = 0
    
    try:
        # Format seasons for nba_api (e.g., "2024-25")
        seasons_to_load = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]
        
        all_games = []
        
        for season in seasons_to_load:
            try:
                if progress_callback:
                    progress_callback(f"Loading NBA games for {season}...")
                
                # LeagueGameFinder returns games with scores
                gamefinder = leaguegamefinder.LeagueGameFinder(
                    season_nullable=season,
                    league_id_nullable='00'  # NBA
                )
                games_df = gamefinder.get_data_frames()[0]
                
                if games_df is not None and len(games_df) > 0:
                    all_games.append(games_df)
                    logger.info(f"Loaded {len(games_df)} game records for {season}")
                
                # Rate limit to avoid API throttling
                time.sleep(1)
                
            except Exception as e:
                logger.warning(f"Error loading {season} schedule: {e}")
                continue
        
        if not all_games:
            logger.warning("No NBA games loaded from nba_api")
            return {"imported": 0}
        
        # Combine all seasons
        games_df = pd.concat(all_games, ignore_index=True)
        
        # Group by game_id to get home/away pairs
        # Each game appears twice (once per team)
        game_ids = games_df['GAME_ID'].unique()
        
        if progress_callback:
            progress_callback(f"Processing {len(game_ids)} unique NBA games...")
        
        for i, game_id in enumerate(game_ids):
            if progress_callback and i % 100 == 0:
                progress_callback(f"Importing NBA schedule {i}/{len(game_ids)}...")
            
            game_rows = games_df[games_df['GAME_ID'] == game_id]
            if len(game_rows) < 2:
                continue
            
            # Determine home (@) vs away
            home_row = game_rows[game_rows['MATCHUP'].str.contains(' vs. ', na=False)]
            away_row = game_rows[game_rows['MATCHUP'].str.contains(' @ ', na=False)]
            
            if home_row.empty or away_row.empty:
                continue
            
            home_row = home_row.iloc[0]
            away_row = away_row.iloc[0]
            
            # Extract season year from season string
            season_str = home_row.get('SEASON_ID', '')
            season_year = int(season_str[1:5]) if len(season_str) >= 5 else 2024
            
            def safe_val(val):
                if pd.isna(val):
                    return None
                if isinstance(val, float):
                    return int(val) if val == int(val) else round(val, 2)
                return val
            
            metadata = {
                'game_id': str(game_id),
                'season': season_year,
                'game_date': safe_val(home_row.get('GAME_DATE')),
                'home_team': safe_val(home_row.get('TEAM_ABBREVIATION')),
                'away_team': safe_val(away_row.get('TEAM_ABBREVIATION')),
                'home_score': safe_val(home_row.get('PTS')),
                'away_score': safe_val(away_row.get('PTS')),
                'home_team_name': safe_val(home_row.get('TEAM_NAME')),
                'away_team_name': safe_val(away_row.get('TEAM_NAME')),
                'wl_home': safe_val(home_row.get('WL')),
                'wl_away': safe_val(away_row.get('WL')),
            }
            
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({'sport': 'nba', 'game_id': str(game_id)})
            
            try:
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nba_schedule', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, season_year, json.dumps(metadata), content_hash
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Error importing NBA schedule: {e}")
        
        gc.collect()
        
    except Exception as e:
        logger.error(f"Error in NBA schedule import: {e}")
        return {"imported": imported, "error": str(e)}
    
    logger.info(f"Imported {imported} NBA game schedules")
    return {"imported": imported}


async def import_game_logs_via_nba_api(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NBA player game logs for hit rate calculations."""
    try:
        from nba_api.stats.endpoints import leaguegamelog
        import time
    except ImportError:
        logger.warning("nba_api not installed - skipping game logs")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Loading NBA player game logs for hit rates...")
    
    imported = 0
    
    try:
        # Load game logs by season
        seasons = ["2023-24", "2024-25"]
        
        all_logs = []
        for season in seasons:
            try:
                if progress_callback:
                    progress_callback(f"Loading NBA game logs for {season}...")
                
                # Get player game logs for the season
                game_log = leaguegamelog.LeagueGameLog(
                    season=season,
                    player_or_team_abbreviation='P',  # Player logs
                    season_type_all_star='Regular Season'
                )
                logs_df = game_log.get_data_frames()[0]
                
                if logs_df is not None and len(logs_df) > 0:
                    all_logs.append(logs_df)
                    logger.info(f"Loaded {len(logs_df)} game logs for {season}")
                
                time.sleep(1)  # Rate limit
                
            except Exception as e:
                logger.warning(f"Error loading {season} game logs: {e}")
                continue
        
        if not all_logs:
            logger.warning("No NBA game logs loaded")
            return {"imported": 0}
        
        logs_df = pd.concat(all_logs, ignore_index=True)
        
        if progress_callback:
            progress_callback(f"Processing {len(logs_df)} NBA game log records...")
        
        for i, (_, row) in enumerate(logs_df.iterrows()):
            if progress_callback and i % 500 == 0:
                progress_callback(f"Importing NBA game logs {i}/{len(logs_df)}...")
            
            player_id = row.get('PLAYER_ID')
            game_id = row.get('GAME_ID')
            if pd.isna(player_id) or pd.isna(game_id):
                continue
            
            def safe_val(val):
                if pd.isna(val):
                    return None
                if isinstance(val, float):
                    return int(val) if val == int(val) else round(val, 2)
                return val
            
            # Extract season year
            season_id = row.get('SEASON_ID', '')
            season_year = int(season_id[1:5]) if len(str(season_id)) >= 5 else 2024
            
            metadata = {
                'player_id': str(player_id),
                'game_id': str(game_id),
                'player_name': safe_val(row.get('PLAYER_NAME')),
                'team': safe_val(row.get('TEAM_ABBREVIATION')),
                'game_date': safe_val(row.get('GAME_DATE')),
                'matchup': safe_val(row.get('MATCHUP')),
                'wl': safe_val(row.get('WL')),
                'min': safe_val(row.get('MIN')),
                'pts': safe_val(row.get('PTS')),
                'reb': safe_val(row.get('REB')),
                'ast': safe_val(row.get('AST')),
                'stl': safe_val(row.get('STL')),
                'blk': safe_val(row.get('BLK')),
                'tov': safe_val(row.get('TOV')),
                'fgm': safe_val(row.get('FGM')),
                'fga': safe_val(row.get('FGA')),
                'fg3m': safe_val(row.get('FG3M')),
                'fg3a': safe_val(row.get('FG3A')),
                'ftm': safe_val(row.get('FTM')),
                'fta': safe_val(row.get('FTA')),
                'plus_minus': safe_val(row.get('PLUS_MINUS')),
            }
            
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({
                'sport': 'nba',
                'player_id': str(player_id),
                'game_id': str(game_id),
                'type': 'game_log'
            })
            
            try:
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nba_game_log', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, season_year, json.dumps(metadata), content_hash
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Error importing NBA game log: {e}")
            
            if i % 1000 == 0:
                gc.collect()
        
        logger.info(f"Imported {imported} NBA game logs")
        return {"imported": imported}
        
    except Exception as e:
        logger.error(f"Error importing NBA game logs: {e}")
        return {"imported": 0, "error": str(e)}


if __name__ == "__main__":
    async def test_import():
        def log_progress(msg):
            print(f"[PROGRESS] {msg}")
        
        result = await import_all_nba(clear_existing=True, progress_callback=log_progress)
        print(f"Result: {result}")
    
    asyncio.run(test_import())
