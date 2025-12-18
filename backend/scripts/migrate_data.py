"""
Data Migration Scripts for PostgreSQL (Optimized)
==================================================

OPTIMIZATIONS:
- Batch commits every 1000 records (less memory, better performance)
- Transaction-based inserts
- Progress logging
- Skip already-imported files

Usage:
    python -m scripts.migrate_data --sport nascar
    python -m scripts.migrate_data --sport nfl
    python -m scripts.migrate_data --sport nba
    python -m scripts.migrate_data --sport all
"""

import asyncio
import asyncpg
import pandas as pd
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
import gc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection string
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# Data directories
DATA_DIR = Path("/app/data")

# Batch size for commits
BATCH_SIZE = 5000


def compute_content_hash(data: dict) -> str:
    """Compute MD5 hash of content for duplicate detection."""
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(content.encode()).hexdigest()


async def setup_duplicate_protection(conn):
    """Add content_hash columns if they don't exist."""
    try:
        await conn.execute("ALTER TABLE results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE stats ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_results_hash ON results(content_hash) WHERE content_hash IS NOT NULL")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_hash ON stats(content_hash) WHERE content_hash IS NOT NULL")
        # Also fix NULL season constraint
        await conn.execute("ALTER TABLE results ALTER COLUMN season DROP NOT NULL")
        logger.info("Duplicate protection setup complete")
    except Exception as e:
        logger.warning(f"Duplicate protection setup: {e}")


async def get_connection():
    """Get async database connection."""
    return await asyncpg.connect(DATABASE_URL)


async def get_or_create_sport(conn, sport_name: str) -> int:
    """Get sport ID, create if not exists."""
    sport_id = await conn.fetchval(
        "SELECT id FROM sports WHERE name = $1", sport_name
    )
    if not sport_id:
        sport_id = await conn.fetchval(
            "INSERT INTO sports (name, display_name) VALUES ($1, $2) RETURNING id",
            sport_name, sport_name.upper()
        )
    return sport_id


async def was_file_imported(conn, sport_id: int, filename: str) -> bool:
    """Check if a file was already imported."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM import_history WHERE sport_id = $1 AND file_name = $2 AND status = 'success'",
        sport_id, filename
    )
    return count > 0


async def get_or_create_entity(conn, sport_id: int, name: str, entity_type: str) -> int:
    """Get entity ID, create if not exists."""
    entity_id = await conn.fetchval(
        "SELECT id FROM entities WHERE sport_id = $1 AND name = $2 AND type = $3",
        sport_id, name, entity_type
    )
    if not entity_id:
        entity_id = await conn.fetchval(
            """INSERT INTO entities (sport_id, name, type) 
               VALUES ($1, $2, $3) RETURNING id""",
            sport_id, name, entity_type
        )
    return entity_id


async def migrate_nascar(conn, data_dir: Path):
    """Migrate NASCAR race data to PostgreSQL with batching."""
    logger.info("Starting NASCAR migration (batched)...")
    
    sport_id = await get_or_create_sport(conn, "nascar")
    
    nascar_dir = data_dir / "nascar"
    csv_files = list(nascar_dir.glob("*.csv")) if nascar_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NASCAR CSV files found in {nascar_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        # Skip already imported files
        if await was_file_imported(conn, sport_id, csv_file.name):
            logger.info(f"Skipping {csv_file.name} - already imported")
            continue
            
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            # Read CSV in chunks to save memory
            chunk_size = 5000
            file_imported = 0
            
            for chunk_num, chunk in enumerate(pd.read_csv(csv_file, low_memory=False, chunksize=chunk_size)):
                logger.info(f"  Processing chunk {chunk_num + 1}...")
                
                # Detect columns
                driver_col = next((c for c in chunk.columns if c.lower() in ['driver', 'driver_name']), None)
                track_col = next((c for c in chunk.columns if c.lower() in ['track', 'track_name']), None)
                year_col = next((c for c in chunk.columns if c.lower() in ['year', 'season']), None)
                finish_col = next((c for c in chunk.columns if c.lower() in ['finish', 'finish_position', 'pos']), None)
                start_col = next((c for c in chunk.columns if c.lower() in ['start', 'start_position', 'grid']), None)
                
                if not driver_col or not year_col:
                    logger.warning(f"Skipping {csv_file.name} - missing required columns")
                    break
                
                # Start transaction for this batch
                async with conn.transaction():
                    batch_count = 0
                    
                    for _, row in chunk.iterrows():
                        driver_name = str(row.get(driver_col, '')).strip()
                        if not driver_name or driver_name == 'nan':
                            continue
                        
                        # Get or create driver
                        driver_id = await get_or_create_entity(conn, sport_id, driver_name, 'driver')
                        
                        # Build metadata
                        result_metadata = {
                            'source_file': csv_file.name,
                            'driver_id': driver_id,
                        }
                        
                        if finish_col and pd.notna(row.get(finish_col)):
                            try:
                                result_metadata['finish'] = int(float(row[finish_col]))
                            except:
                                pass
                        
                        if start_col and pd.notna(row.get(start_col)):
                            try:
                                result_metadata['start'] = int(float(row[start_col]))
                            except:
                                pass
                        
                        # Get season
                        season = None
                        if year_col and pd.notna(row.get(year_col)):
                            try:
                                season = int(float(row[year_col]))
                            except:
                                pass
                        
                        # Compute content hash for duplicate detection
                        hash_data = {
                            'sport': 'nascar',
                            'driver': driver_name,
                            'season': season,
                            'track': str(row.get(track_col, '')) if track_col else '',
                            'finish': result_metadata.get('finish'),
                            'start': result_metadata.get('start'),
                        }
                        content_hash = compute_content_hash(hash_data)
                        
                        # Insert/Update result with UPSERT
                        try:
                            await conn.execute(
                                """INSERT INTO results (sport_id, season, track, metadata, content_hash)
                                   VALUES ($1, $2, $3, $4, $5)
                                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
                                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                                sport_id,
                                season,
                                str(row.get(track_col, ''))[:255] if track_col else None,
                                json.dumps(result_metadata),
                                content_hash
                            )
                            batch_count += 1
                            file_imported += 1
                            total_imported += 1
                        except asyncpg.UniqueViolationError:
                            pass  # Unexpected, but handle gracefully
                    
                    logger.info(f"    Committed {batch_count} records")
                
                # Force garbage collection between chunks
                gc.collect()
            
            # Record successful import
            await conn.execute(
                """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
                   VALUES ($1, $2, $3, $4, $5)""",
                sport_id, 'csv', csv_file.name, file_imported, 'success'
            )
            logger.info(f"  Completed {csv_file.name}: {file_imported} records")
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
            # Record failed import
            await conn.execute(
                """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status, error_message)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                sport_id, 'csv', csv_file.name, 0, 'failed', str(e)
            )
    
    logger.info(f"NASCAR migration complete: {total_imported} records imported")
    return total_imported


async def migrate_nfl(conn, data_dir: Path):
    """Migrate NFL game data to PostgreSQL with batching."""
    logger.info("Starting NFL migration (batched)...")
    
    sport_id = await get_or_create_sport(conn, "nfl")
    
    nfl_dir = data_dir / "nfl"
    csv_files = list(nfl_dir.glob("*.csv")) if nfl_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NFL CSV files found in {nfl_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        if await was_file_imported(conn, sport_id, csv_file.name):
            logger.info(f"Skipping {csv_file.name} - already imported")
            continue
            
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            chunk_size = 5000
            file_imported = 0
            
            for chunk_num, chunk in enumerate(pd.read_csv(csv_file, low_memory=False, chunksize=chunk_size)):
                # Look for various column patterns
                home_col = next((c for c in chunk.columns if 'home' in c.lower() and 'team' in c.lower()), None)
                away_col = next((c for c in chunk.columns if 'away' in c.lower() and 'team' in c.lower()), None)
                
                # Alternative: team column for player stats
                team_col = next((c for c in chunk.columns if c.lower() in ['team', 'tm']), None)
                player_col = next((c for c in chunk.columns if c.lower() in ['player', 'player_name', 'name']), None)
                
                season_col = next((c for c in chunk.columns if c.lower() in ['season', 'year', 'schedule_season']), None)
                
                if player_col:
                    # Player stats file
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            player_name = str(row.get(player_col, '')).strip()
                            if not player_name or player_name == 'nan':
                                continue
                            
                            player_id = await get_or_create_entity(conn, sport_id, player_name, 'player')
                            
                            stats_data = {'source_file': csv_file.name}
                            for col in chunk.columns:
                                val = row.get(col)
                                if pd.notna(val):
                                    try:
                                        stats_data[col] = float(val) if isinstance(val, (int, float)) else str(val)[:500]
                                    except:
                                        stats_data[col] = str(val)[:500]
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, stat_type, stats)
                                   VALUES ($1, $2, $3)""",
                                player_id, 'season', json.dumps(stats_data)
                            )
                            file_imported += 1
                            total_imported += 1
                        
                        logger.info(f"    Committed {file_imported} player stats")
                
                elif home_col and away_col:
                    # Game results file
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            home_team = str(row.get(home_col, '')).strip()
                            away_team = str(row.get(away_col, '')).strip()
                            
                            if not home_team or home_team == 'nan':
                                continue
                            
                            home_id = await get_or_create_entity(conn, sport_id, home_team, 'team')
                            away_id = await get_or_create_entity(conn, sport_id, away_team, 'team')
                            
                            season = None
                            if season_col and pd.notna(row.get(season_col)):
                                try:
                                    season = int(float(row[season_col]))
                                except:
                                    pass
                            
                            result_metadata = {'source_file': csv_file.name}
                            
                            await conn.execute(
                                """INSERT INTO results (sport_id, season, home_entity_id, away_entity_id, metadata)
                                   VALUES ($1, $2, $3, $4, $5)""",
                                sport_id, season, home_id, away_id, json.dumps(result_metadata)
                            )
                            file_imported += 1
                            total_imported += 1
                        
                        logger.info(f"    Committed {file_imported} game results")
                
                elif team_col:
                    # Team stats file
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            team_name = str(row.get(team_col, '')).strip()
                            if not team_name or team_name == 'nan':
                                continue
                            
                            team_id = await get_or_create_entity(conn, sport_id, team_name, 'team')
                            
                            stats_data = {'source_file': csv_file.name}
                            for col in chunk.columns:
                                val = row.get(col)
                                if pd.notna(val):
                                    try:
                                        stats_data[col] = float(val) if isinstance(val, (int, float)) else str(val)[:500]
                                    except:
                                        stats_data[col] = str(val)[:500]
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, stat_type, stats)
                                   VALUES ($1, $2, $3)""",
                                team_id, 'team_season', json.dumps(stats_data)
                            )
                            file_imported += 1
                            total_imported += 1
                        
                        logger.info(f"    Committed {file_imported} team stats")
                else:
                    logger.warning(f"Skipping {csv_file.name} - no recognizable columns")
                    break
                
                gc.collect()
            
            if file_imported > 0:
                await conn.execute(
                    """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
                       VALUES ($1, $2, $3, $4, $5)""",
                    sport_id, 'csv', csv_file.name, file_imported, 'success'
                )
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    logger.info(f"NFL migration complete: {total_imported} records imported")
    return total_imported


async def migrate_nba(conn, data_dir: Path):
    """Migrate NBA data to PostgreSQL with batching."""
    logger.info("Starting NBA migration (batched)...")
    
    sport_id = await get_or_create_sport(conn, "nba")
    
    nba_dir = data_dir / "nba"
    csv_files = list(nba_dir.glob("**/*.csv")) if nba_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NBA CSV files found in {nba_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        if await was_file_imported(conn, sport_id, csv_file.name):
            logger.info(f"Skipping {csv_file.name} - already imported")
            continue
            
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            chunk_size = 5000
            file_imported = 0
            
            for chunk_num, chunk in enumerate(pd.read_csv(csv_file, low_memory=False, chunksize=chunk_size)):
                # Detect file type by columns - expanded patterns
                player_col = next((c for c in chunk.columns if c.lower() in ['player', 'player_name', 'playername', 'player_id']), None)
                team_col = next((c for c in chunk.columns if c.lower() in ['team', 'tm', 'teamname', 'team_name', 'hometeamname', 'abbreviation']), None)
                home_team_col = next((c for c in chunk.columns if c.lower() in ['hometeamname', 'home_team', 'hometeam']), None)
                away_team_col = next((c for c in chunk.columns if c.lower() in ['awayteamname', 'away_team', 'awayteam', 'visitorteamname']), None)
                
                if player_col:
                    # Player data
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            player_name = str(row.get(player_col, '')).strip()
                            if not player_name or player_name == 'nan':
                                continue
                            
                            player_id = await get_or_create_entity(conn, sport_id, player_name, 'player')
                            
                            stats_data = {'source_file': csv_file.name}
                            for col in chunk.columns:
                                val = row.get(col)
                                if pd.notna(val):
                                    try:
                                        stats_data[col] = float(val) if isinstance(val, (int, float)) else str(val)[:500]
                                    except:
                                        stats_data[col] = str(val)[:500]
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, stat_type, stats)
                                   VALUES ($1, $2, $3)""",
                                player_id, 'season', json.dumps(stats_data)
                            )
                            file_imported += 1
                            total_imported += 1
                        
                        logger.info(f"    Chunk {chunk_num + 1}: {file_imported} records")
                
                elif team_col:
                    # Team data
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            team_name = str(row.get(team_col, '')).strip()
                            if not team_name or team_name == 'nan':
                                continue
                            
                            team_id = await get_or_create_entity(conn, sport_id, team_name, 'team')
                            
                            stats_data = {'source_file': csv_file.name}
                            for col in chunk.columns:
                                val = row.get(col)
                                if pd.notna(val):
                                    try:
                                        stats_data[col] = float(val) if isinstance(val, (int, float)) else str(val)[:500]
                                    except:
                                        stats_data[col] = str(val)[:500]
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, stat_type, stats)
                                   VALUES ($1, $2, $3)""",
                                team_id, 'team_season', json.dumps(stats_data)
                            )
                            file_imported += 1
                            total_imported += 1
                        
                        logger.info(f"    Chunk {chunk_num + 1}: {file_imported} records")
                
                elif home_team_col and away_team_col:
                    # Game data with home/away teams
                    async with conn.transaction():
                        for _, row in chunk.iterrows():
                            home_team = str(row.get(home_team_col, '')).strip()
                            away_team = str(row.get(away_team_col, '')).strip()
                            
                            if not home_team or home_team == 'nan':
                                continue
                            
                            home_id = await get_or_create_entity(conn, sport_id, home_team, 'team')
                            away_id = await get_or_create_entity(conn, sport_id, away_team, 'team') if away_team and away_team != 'nan' else None
                            
                            game_data = {'source_file': csv_file.name}
                            for col in chunk.columns:
                                val = row.get(col)
                                if pd.notna(val):
                                    try:
                                        game_data[col] = float(val) if isinstance(val, (int, float)) else str(val)[:500]
                                    except:
                                        game_data[col] = str(val)[:500]
                            
                            # Compute hash for duplicate detection
                            hash_data = {'sport': 'nba', 'home': home_team, 'away': away_team, 'game': game_data.get('gameId', '')}
                            content_hash = compute_content_hash(hash_data)
                            
                            try:
                                await conn.execute(
                                    """INSERT INTO results (sport_id, home_entity_id, away_entity_id, metadata, content_hash)
                                       VALUES ($1, $2, $3, $4, $5)
                                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
                                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                                    sport_id, home_id, away_id, json.dumps(game_data), content_hash
                                )
                                file_imported += 1
                                total_imported += 1
                            except asyncpg.UniqueViolationError:
                                pass
                        
                        logger.info(f"    Chunk {chunk_num + 1}: {file_imported} game records")
                
                else:
                    logger.warning(f"Skipping {csv_file.name} - no player/team columns found")
                    break
                
                gc.collect()
            
            if file_imported > 0:
                await conn.execute(
                    """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
                       VALUES ($1, $2, $3, $4, $5)""",
                    sport_id, 'csv', csv_file.name, file_imported, 'success'
                )
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    logger.info(f"NBA migration complete: {total_imported} records imported")
    return total_imported


async def run_migration(sport: Optional[str] = None):
    """Run data migration for specified sport or all sports."""
    logger.info("=" * 50)
    logger.info("STARTING DATA MIGRATION (OPTIMIZED)")
    logger.info("=" * 50)
    
    conn = await get_connection()
    
    try:
        # Setup duplicate protection (add columns/indexes if needed)
        await setup_duplicate_protection(conn)
        
        results = {}
        
        if sport is None or sport == 'all':
            results['nascar'] = await migrate_nascar(conn, DATA_DIR)
            results['nfl'] = await migrate_nfl(conn, DATA_DIR)
            results['nba'] = await migrate_nba(conn, DATA_DIR)
        elif sport == 'nascar':
            results['nascar'] = await migrate_nascar(conn, DATA_DIR)
        elif sport == 'nfl':
            results['nfl'] = await migrate_nfl(conn, DATA_DIR)
        elif sport == 'nba':
            results['nba'] = await migrate_nba(conn, DATA_DIR)
        else:
            logger.error(f"Unknown sport: {sport}")
            return
        
        logger.info("=" * 50)
        logger.info("MIGRATION COMPLETE")
        logger.info("=" * 50)
        for sport_name, count in results.items():
            logger.info(f"  {sport_name.upper()}: {count} records")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate CSV data to PostgreSQL")
    parser.add_argument("--sport", choices=['nascar', 'nfl', 'nba', 'all'], default='all',
                        help="Sport to migrate (default: all)")
    args = parser.parse_args()
    
    asyncio.run(run_migration(args.sport if args.sport != 'all' else None))
