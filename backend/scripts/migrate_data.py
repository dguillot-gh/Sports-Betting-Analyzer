"""
Data Migration Scripts for PostgreSQL
======================================

This module provides functions to migrate CSV data to PostgreSQL.

Usage:
    python -m scripts.migrate_data --sport nascar
    python -m scripts.migrate_data --sport nfl
    python -m scripts.migrate_data --sport nba
    python -m scripts.migrate_data --all
"""

import asyncio
import asyncpg
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection string
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# Data directories
DATA_DIR = Path("/app/data")


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


async def get_or_create_entity(conn, sport_id: int, name: str, entity_type: str, metadata: dict = None) -> int:
    """Get entity ID, create if not exists."""
    entity_id = await conn.fetchval(
        "SELECT id FROM entities WHERE sport_id = $1 AND name = $2 AND type = $3",
        sport_id, name, entity_type
    )
    if not entity_id:
        entity_id = await conn.fetchval(
            """INSERT INTO entities (sport_id, name, type, metadata) 
               VALUES ($1, $2, $3, $4) RETURNING id""",
            sport_id, name, entity_type, json.dumps(metadata or {})
        )
    return entity_id


async def migrate_nascar(conn, data_dir: Path):
    """Migrate NASCAR race data to PostgreSQL."""
    logger.info("Starting NASCAR migration...")
    
    sport_id = await get_or_create_sport(conn, "nascar")
    
    # Find NASCAR CSV files
    nascar_dir = data_dir / "nascar"
    csv_files = list(nascar_dir.glob("*.csv")) if nascar_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NASCAR CSV files found in {nascar_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            
            # Detect column names (handle variations)
            driver_col = next((c for c in df.columns if c.lower() in ['driver', 'driver_name']), None)
            track_col = next((c for c in df.columns if c.lower() in ['track', 'track_name']), None)
            year_col = next((c for c in df.columns if c.lower() in ['year', 'season']), None)
            finish_col = next((c for c in df.columns if c.lower() in ['finish', 'finish_position', 'pos']), None)
            start_col = next((c for c in df.columns if c.lower() in ['start', 'start_position', 'grid']), None)
            
            if not driver_col or not year_col:
                logger.warning(f"Skipping {csv_file.name} - missing required columns")
                continue
            
            # Process each row
            for _, row in df.iterrows():
                driver_name = str(row.get(driver_col, '')).strip()
                if not driver_name or driver_name == 'nan':
                    continue
                
                # Get or create driver entity
                driver_id = await get_or_create_entity(conn, sport_id, driver_name, 'driver')
                
                # Create result record
                result_metadata = {
                    'source_file': csv_file.name,
                    'finish': int(row[finish_col]) if finish_col and pd.notna(row.get(finish_col)) else None,
                    'start': int(row[start_col]) if start_col and pd.notna(row.get(start_col)) else None,
                }
                
                # Add any additional columns as metadata
                for col in df.columns:
                    if col not in [driver_col, year_col, track_col, finish_col, start_col]:
                        val = row.get(col)
                        if pd.notna(val):
                            result_metadata[col] = val if not isinstance(val, float) else float(val)
                
                # Insert result
                await conn.execute(
                    """INSERT INTO results (sport_id, season, track, race_name, metadata)
                       VALUES ($1, $2, $3, $4, $5)""",
                    sport_id,
                    int(row[year_col]) if pd.notna(row.get(year_col)) else None,
                    str(row.get(track_col, '')) if track_col else None,
                    csv_file.stem,
                    json.dumps(result_metadata)
                )
                total_imported += 1
                
                if total_imported % 1000 == 0:
                    logger.info(f"  Imported {total_imported} records...")
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    # Record import
    await conn.execute(
        """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
           VALUES ($1, $2, $3, $4, $5)""",
        sport_id, 'csv', 'nascar_migration', total_imported, 'success'
    )
    
    logger.info(f"NASCAR migration complete: {total_imported} records imported")
    return total_imported


async def migrate_nfl(conn, data_dir: Path):
    """Migrate NFL game data to PostgreSQL."""
    logger.info("Starting NFL migration...")
    
    sport_id = await get_or_create_sport(conn, "nfl")
    
    nfl_dir = data_dir / "nfl"
    csv_files = list(nfl_dir.glob("*.csv")) if nfl_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NFL CSV files found in {nfl_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            
            # Detect columns
            home_col = next((c for c in df.columns if 'home' in c.lower() and 'team' in c.lower()), None)
            away_col = next((c for c in df.columns if 'away' in c.lower() and 'team' in c.lower()), None)
            home_score_col = next((c for c in df.columns if 'home' in c.lower() and 'score' in c.lower()), None)
            away_score_col = next((c for c in df.columns if 'away' in c.lower() and 'score' in c.lower()), None)
            season_col = next((c for c in df.columns if c.lower() in ['season', 'year', 'schedule_season']), None)
            week_col = next((c for c in df.columns if 'week' in c.lower()), None)
            
            if not home_col or not away_col:
                logger.warning(f"Skipping {csv_file.name} - missing team columns")
                continue
            
            for _, row in df.iterrows():
                home_team = str(row.get(home_col, '')).strip()
                away_team = str(row.get(away_col, '')).strip()
                
                if not home_team or home_team == 'nan':
                    continue
                
                # Get or create team entities
                home_id = await get_or_create_entity(conn, sport_id, home_team, 'team')
                away_id = await get_or_create_entity(conn, sport_id, away_team, 'team')
                
                home_score = float(row[home_score_col]) if home_score_col and pd.notna(row.get(home_score_col)) else None
                away_score = float(row[away_score_col]) if away_score_col and pd.notna(row.get(away_score_col)) else None
                
                # Build metadata
                result_metadata = {'source_file': csv_file.name}
                for col in df.columns:
                    if col not in [home_col, away_col, home_score_col, away_score_col, season_col, week_col]:
                        val = row.get(col)
                        if pd.notna(val):
                            result_metadata[col] = str(val) if isinstance(val, str) else float(val) if isinstance(val, float) else val
                
                await conn.execute(
                    """INSERT INTO results (sport_id, season, week, home_entity_id, away_entity_id, 
                       home_score, away_score, metadata)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    sport_id,
                    int(row[season_col]) if season_col and pd.notna(row.get(season_col)) else None,
                    int(row[week_col]) if week_col and pd.notna(row.get(week_col)) else None,
                    home_id, away_id, home_score, away_score,
                    json.dumps(result_metadata)
                )
                total_imported += 1
                
                if total_imported % 1000 == 0:
                    logger.info(f"  Imported {total_imported} records...")
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    await conn.execute(
        """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
           VALUES ($1, $2, $3, $4, $5)""",
        sport_id, 'csv', 'nfl_migration', total_imported, 'success'
    )
    
    logger.info(f"NFL migration complete: {total_imported} records imported")
    return total_imported


async def migrate_nba(conn, data_dir: Path):
    """Migrate NBA game data to PostgreSQL."""
    logger.info("Starting NBA migration...")
    
    sport_id = await get_or_create_sport(conn, "nba")
    
    nba_dir = data_dir / "nba"
    csv_files = list(nba_dir.glob("*.csv")) if nba_dir.exists() else []
    
    if not csv_files:
        logger.warning(f"No NBA CSV files found in {nba_dir}")
        return 0
    
    total_imported = 0
    
    for csv_file in csv_files:
        logger.info(f"Processing {csv_file.name}...")
        
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            
            # Similar to NFL migration
            home_col = next((c for c in df.columns if 'home' in c.lower() and 'team' in c.lower()), None)
            away_col = next((c for c in df.columns if ('away' in c.lower() or 'visitor' in c.lower()) and 'team' in c.lower()), None)
            
            # Handle player-level data
            player_col = next((c for c in df.columns if c.lower() in ['player', 'player_name']), None)
            team_col = next((c for c in df.columns if c.lower() in ['team', 'tm']), None)
            
            if player_col:
                # Player stats file
                for _, row in df.iterrows():
                    player_name = str(row.get(player_col, '')).strip()
                    if not player_name or player_name == 'nan':
                        continue
                    
                    player_id = await get_or_create_entity(conn, sport_id, player_name, 'player')
                    
                    # Store stats
                    stats_data = {}
                    for col in df.columns:
                        if col != player_col:
                            val = row.get(col)
                            if pd.notna(val):
                                stats_data[col] = float(val) if isinstance(val, (int, float)) else str(val)
                    
                    await conn.execute(
                        """INSERT INTO stats (entity_id, stat_type, stats)
                           VALUES ($1, $2, $3)""",
                        player_id, 'season', json.dumps(stats_data)
                    )
                    total_imported += 1
                    
            elif home_col or team_col:
                # Game/team data
                for _, row in df.iterrows():
                    team_name = str(row.get(home_col or team_col, '')).strip()
                    if not team_name or team_name == 'nan':
                        continue
                    
                    team_id = await get_or_create_entity(conn, sport_id, team_name, 'team')
                    
                    result_metadata = {'source_file': csv_file.name}
                    for col in df.columns:
                        val = row.get(col)
                        if pd.notna(val):
                            result_metadata[col] = float(val) if isinstance(val, (int, float)) else str(val)
                    
                    await conn.execute(
                        """INSERT INTO results (sport_id, metadata)
                           VALUES ($1, $2)""",
                        sport_id, json.dumps(result_metadata)
                    )
                    total_imported += 1
                
                if total_imported % 1000 == 0:
                    logger.info(f"  Imported {total_imported} records...")
                    
        except Exception as e:
            logger.error(f"Error processing {csv_file.name}: {e}")
    
    await conn.execute(
        """INSERT INTO import_history (sport_id, source, file_name, rows_imported, status)
           VALUES ($1, $2, $3, $4, $5)""",
        sport_id, 'csv', 'nba_migration', total_imported, 'success'
    )
    
    logger.info(f"NBA migration complete: {total_imported} records imported")
    return total_imported


async def run_migration(sport: Optional[str] = None):
    """Run data migration for specified sport or all sports."""
    conn = await get_connection()
    
    try:
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
