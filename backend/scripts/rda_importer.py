"""
NASCAR RDA Direct Importer
==========================

Reads NASCAR RDA files directly and imports into PostgreSQL.
Computes pre-aggregated stats per driver/season/series.

Features:
- Direct RDA reading (no CSV conversion)
- Dynamic year range (2012 to current year)
- Content hash for incremental updates
- Pre-computed season stats

Usage:
    python -m scripts.rda_importer --series cup
    python -m scripts.rda_importer --series all
"""

import asyncio
import asyncpg
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import pyreadr
try:
    import pyreadr
    HAS_PYREADR = True
except ImportError:
    HAS_PYREADR = False
    logger.warning("pyreadr not installed. Run: pip install pyreadr")

# Database connection string
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"

# Data directory
DATA_DIR = Path("/app/data/nascar/raw")

# Default year range
DEFAULT_YEAR_START = 2012
DEFAULT_YEAR_END = datetime.now().year


def get_series_from_filename(filename: str) -> str:
    """Parse NASCAR series from filename."""
    fname = filename.lower()
    if 'cup' in fname:
        return 'cup'
    elif 'xfinity' in fname:
        return 'xfinity'
    elif 'truck' in fname:
        return 'trucks'
    return 'unknown'


def compute_hash(data: Dict) -> str:
    """Compute content hash for duplicate detection."""
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(content.encode()).hexdigest()


def read_rda_file(filepath: Path) -> Optional[Any]:
    """Read RDA file and return DataFrame."""
    if not HAS_PYREADR:
        logger.error("pyreadr not installed")
        return None
    
    try:
        result = pyreadr.read_r(str(filepath))
        # RDA files can contain multiple objects, get the first one
        if result:
            key = list(result.keys())[0]
            return result[key]
        return None
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return None


async def get_connection():
    """Get async database connection."""
    return await asyncpg.connect(DATABASE_URL)


async def get_or_create_sport(conn, sport_name: str = "nascar") -> int:
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


async def get_or_create_entity(conn, sport_id: int, name: str, entity_type: str, series: str) -> int:
    """Get entity ID, create if not exists."""
    entity_id = await conn.fetchval(
        """SELECT id FROM entities 
           WHERE sport_id = $1 AND name = $2 AND type = $3 AND series = $4""",
        sport_id, name, entity_type, series
    )
    if not entity_id:
        entity_id = await conn.fetchval(
            """INSERT INTO entities (sport_id, name, type, series) 
               VALUES ($1, $2, $3, $4) RETURNING id""",
            sport_id, name, entity_type, series
        )
    return entity_id


def detect_columns(df) -> Dict[str, str]:
    """Detect column names for required fields."""
    columns = {col.lower(): col for col in df.columns}
    
    mapping = {}
    
    # Driver column
    for name in ['driver', 'driver_name']:
        if name in columns:
            mapping['driver'] = columns[name]
            break
    
    # Year/Season column
    for name in ['year', 'season']:
        if name in columns:
            mapping['year'] = columns[name]
            break
    
    # Track column
    for name in ['track', 'track_name']:
        if name in columns:
            mapping['track'] = columns[name]
            break
    
    # Finish position column
    for name in ['finishing_position', 'finish_position', 'finish', 'pos']:
        if name in columns:
            mapping['finish'] = columns[name]
            break
    
    # Start position column
    for name in ['start', 'start_position', 'grid']:
        if name in columns:
            mapping['start'] = columns[name]
            break
    
    # Race number column
    for name in ['race_num', 'race', 'race_number']:
        if name in columns:
            mapping['race_num'] = columns[name]
            break
    
    # Race name column
    for name in ['name', 'race_name', 'event']:
        if name in columns:
            mapping['race_name'] = columns[name]
            break
    
    # Extended columns - direct mapping
    extended_cols = {
        'laps': ['laps', 'laps_completed'],
        'led': ['led', 'laps_led'],
        'pts': ['pts', 'points', 'race_points'],
        'status': ['status', 'finish_status'],
        'team': ['team', 'team_name'],
        'make': ['make', 'manufacturer'],
        'car': ['car', 'car_number', 'car_num'],
        'rating': ['rating', 'driver_rating', 'loop_rating'],
        'win': ['win', 'winner'],
        's1': ['s1', 'stage1', 'stage_1'],
        's2': ['s2', 'stage2', 'stage_2'],
        'seg_points': ['seg points', 'seg_points', 'stage_points'],
        'length': ['length', 'track_length'],
        'surface': ['surface', 'track_surface'],
    }
    
    for key, names in extended_cols.items():
        for name in names:
            if name in columns:
                mapping[key] = columns[name]
                break
    
    return mapping


async def import_rda_series(
    conn,
    filepath: Path,
    sport_id: int,
    series: str,
    year_start: int = DEFAULT_YEAR_START,
    year_end: int = DEFAULT_YEAR_END
) -> Dict[str, int]:
    """Import a single RDA file for a series."""
    
    logger.info(f"Reading {filepath.name}...")
    df = read_rda_file(filepath)
    
    if df is None:
        return {"error": f"Failed to read {filepath.name}"}
    
    logger.info(f"  Loaded {len(df)} rows, {len(df.columns)} columns")
    logger.info(f"  Columns: {list(df.columns)}")
    
    # Detect columns
    col_map = detect_columns(df)
    logger.info(f"  Column mapping: {col_map}")
    
    if 'driver' not in col_map or 'year' not in col_map:
        return {"error": f"Missing required columns in {filepath.name}"}
    
    # Track stats for computation
    driver_season_data: Dict[str, Dict[str, List]] = {}  # driver_id -> season -> [races]
    
    total_imported = 0
    skipped = 0
    
    # Process in batches
    batch_size = 1000
    total_rows = len(df)
    
    for batch_start in range(0, total_rows, batch_size):
        batch_end = min(batch_start + batch_size, total_rows)
        batch = df.iloc[batch_start:batch_end]
        
        async with conn.transaction():
            for _, row in batch.iterrows():
                # Get year and filter
                try:
                    year = int(float(row[col_map['year']]))
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                
                if year < year_start or year > year_end:
                    skipped += 1
                    continue
                
                # Get driver name
                driver_name = str(row[col_map['driver']]).strip()
                if not driver_name or driver_name == 'nan':
                    skipped += 1
                    continue
                
                # Get or create driver entity
                driver_id = await get_or_create_entity(
                    conn, sport_id, driver_name, 'driver', series
                )
                
                # Get track
                track = str(row.get(col_map.get('track', 'track'), '')).strip() if 'track' in col_map else None
                
                # Get finish and start
                finish = None
                if 'finish' in col_map:
                    try:
                        finish = int(float(row[col_map['finish']]))
                    except (ValueError, TypeError):
                        pass
                
                start = None
                if 'start' in col_map:
                    try:
                        start = int(float(row[col_map['start']]))
                    except (ValueError, TypeError):
                        pass
                
                # Get race number for unique identification
                race_num = None
                if 'race_num' in col_map:
                    try:
                        race_num = int(float(row[col_map['race_num']]))
                    except (ValueError, TypeError):
                        pass
                
                # Get race name
                race_name = None
                if 'race_name' in col_map:
                    race_name = str(row[col_map['race_name']]).strip()
                    if race_name == 'nan':
                        race_name = None
                
                # Extract extended columns
                def safe_int(col_key):
                    if col_key in col_map:
                        try:
                            val = row[col_map[col_key]]
                            return int(float(val)) if val is not None and str(val) != 'nan' else None
                        except (ValueError, TypeError):
                            pass
                    return None
                
                def safe_float(col_key):
                    if col_key in col_map:
                        try:
                            val = row[col_map[col_key]]
                            return round(float(val), 1) if val is not None and str(val) != 'nan' else None
                        except (ValueError, TypeError):
                            pass
                    return None
                
                def safe_str(col_key):
                    if col_key in col_map:
                        val = str(row[col_map[col_key]]).strip()
                        return val if val and val != 'nan' else None
                    return None
                
                laps = safe_int('laps')
                led = safe_int('led')
                pts = safe_int('pts')
                status = safe_str('status')
                team = safe_str('team')
                make = safe_str('make')
                car = safe_str('car')
                rating = safe_float('rating')
                win = safe_int('win')
                s1 = safe_int('s1')
                s2 = safe_int('s2')
                seg_points = safe_int('seg_points')
                
                # Build metadata with all available fields
                metadata = {
                    'driver_id': driver_id,
                    'driver_name': driver_name,
                    'series': series,
                }
                if finish is not None:
                    metadata['finish'] = finish
                if start is not None:
                    metadata['start'] = start
                if race_num is not None:
                    metadata['race_num'] = race_num
                if race_name:
                    metadata['race_name'] = race_name
                if laps is not None:
                    metadata['laps'] = laps
                if led is not None:
                    metadata['led'] = led
                if pts is not None:
                    metadata['pts'] = pts
                if status:
                    metadata['status'] = status
                if team:
                    metadata['team'] = team
                if make:
                    metadata['make'] = make
                if car:
                    metadata['car'] = car
                if rating is not None:
                    metadata['rating'] = rating
                if win is not None:
                    metadata['win'] = win
                if s1 is not None:
                    metadata['s1'] = s1
                if s2 is not None:
                    metadata['s2'] = s2
                if seg_points is not None:
                    metadata['seg_points'] = seg_points
                
                # Compute content hash (include race_num for uniqueness)
                hash_data = {
                    'sport': 'nascar',
                    'driver': driver_name,
                    'season': year,
                    'series': series,
                    'track': track or '',
                    'race_num': race_num,
                    'finish': finish,
                }
                content_hash = compute_hash(hash_data)
                
                # Upsert result
                try:
                    await conn.execute(
                        """INSERT INTO results (sport_id, season, series, track, metadata, content_hash)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
                           DO UPDATE SET metadata = EXCLUDED.metadata""",
                        sport_id, year, series, track[:255] if track else None,
                        json.dumps(metadata), content_hash
                    )
                    total_imported += 1
                except asyncpg.UniqueViolationError:
                    pass
                
                # Track for stats computation
                if finish is not None:
                    season_key = str(year)
                    driver_key = str(driver_id)
                    
                    if driver_key not in driver_season_data:
                        driver_season_data[driver_key] = {}
                    if season_key not in driver_season_data[driver_key]:
                        driver_season_data[driver_key][season_key] = []
                    
                    driver_season_data[driver_key][season_key].append({
                        'finish': finish,
                        'start': start,
                        'led': led or 0,
                        'pts': pts or 0,
                        'status': status,
                        'rating': rating,
                        's1': s1,
                        's2': s2,
                        'seg_points': seg_points or 0,
                    })
        
        logger.info(f"  Processed {batch_end}/{total_rows} rows...")
    
    # Compute and store stats
    logger.info(f"  Computing stats for {len(driver_season_data)} drivers...")
    stats_computed = 0
    
    for driver_id, seasons in driver_season_data.items():
        for season, races in seasons.items():
            finishes = [r['finish'] for r in races if r['finish'] is not None]
            starts = [r['start'] for r in races if r['start'] is not None]
            
            if not finishes:
                continue
            
            # Extended stats
            laps_led = sum(r.get('led', 0) or 0 for r in races)
            total_pts = sum(r.get('pts', 0) or 0 for r in races)
            dnf_count = sum(1 for r in races if r.get('status') and r['status'].lower() not in ['running', 'finished', ''])
            ratings = [r.get('rating') for r in races if r.get('rating') is not None]
            stage_wins = sum(1 for r in races if (r.get('s1') == 1 or r.get('s2') == 1))
            total_stage_points = sum(r.get('seg_points', 0) or 0 for r in races)
            
            stats = {
                # Basic stats
                'races': len(finishes),
                'wins': sum(1 for f in finishes if f == 1),
                'top_5': sum(1 for f in finishes if f <= 5),
                'top_10': sum(1 for f in finishes if f <= 10),
                'avg_finish': round(sum(finishes) / len(finishes), 1),
                'best_finish': min(finishes),
                'poles': sum(1 for s in starts if s == 1) if starts else 0,
                'avg_start': round(sum(starts) / len(starts), 1) if starts else None,
                # Extended stats
                'laps_led': laps_led,
                'total_pts': total_pts,
                'dnf_count': dnf_count,
                'avg_rating': round(sum(ratings) / len(ratings), 1) if ratings else None,
                'stage_wins': stage_wins,
                'stage_points': total_stage_points,
            }
            
            # Upsert stats
            stats_hash = compute_hash({
                'entity_id': driver_id,
                'season': season,
                'series': series,
            })
            
            await conn.execute(
                """INSERT INTO stats (entity_id, season, series, stat_type, stats, content_hash)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL 
                   DO UPDATE SET stats = EXCLUDED.stats""",
                int(driver_id), int(season), series, 'season_summary',
                json.dumps(stats), stats_hash
            )
            stats_computed += 1
    
    return {
        'series': series,
        'file': filepath.name,
        'results_imported': total_imported,
        'stats_computed': stats_computed,
        'skipped': skipped,
    }


async def import_nascar_rda(
    series: Optional[str] = None,
    year_start: int = DEFAULT_YEAR_START,
    year_end: int = DEFAULT_YEAR_END,
    data_dir: Path = DATA_DIR
) -> Dict[str, Any]:
    """Import NASCAR data from RDA files."""
    
    if not HAS_PYREADR:
        return {"error": "pyreadr not installed. Run: pip install pyreadr"}
    
    logger.info("=" * 50)
    logger.info("NASCAR RDA IMPORT")
    logger.info(f"Year range: {year_start} - {year_end}")
    logger.info(f"Data dir: {data_dir}")
    logger.info("=" * 50)
    
    conn = await get_connection()
    
    try:
        sport_id = await get_or_create_sport(conn, "nascar")
        
        # Find RDA files
        rda_files = list(data_dir.glob("*.rda"))
        if not rda_files:
            return {"error": f"No RDA files found in {data_dir}"}
        
        logger.info(f"Found {len(rda_files)} RDA files")
        
        results = []
        
        for rda_file in rda_files:
            file_series = get_series_from_filename(rda_file.name)
            
            # Filter by series if specified
            if series and series != 'all' and file_series != series:
                continue
            
            result = await import_rda_series(
                conn, rda_file, sport_id, file_series, year_start, year_end
            )
            results.append(result)
        
        logger.info("=" * 50)
        logger.info("IMPORT COMPLETE")
        for r in results:
            logger.info(f"  {r.get('series', 'unknown')}: {r.get('results_imported', 0)} results, {r.get('stats_computed', 0)} stats")
        logger.info("=" * 50)
        
        return {
            "success": True,
            "year_range": f"{year_start}-{year_end}",
            "series_results": results,
        }
    
    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Import NASCAR RDA files to PostgreSQL")
    parser.add_argument("--series", choices=['cup', 'xfinity', 'trucks', 'all'], default='all',
                        help="Series to import (default: all)")
    parser.add_argument("--year-start", type=int, default=DEFAULT_YEAR_START,
                        help=f"Start year (default: {DEFAULT_YEAR_START})")
    parser.add_argument("--year-end", type=int, default=DEFAULT_YEAR_END,
                        help=f"End year (default: {DEFAULT_YEAR_END})")
    args = parser.parse_args()
    
    asyncio.run(import_nascar_rda(
        series=args.series if args.series != 'all' else None,
        year_start=args.year_start,
        year_end=args.year_end
    ))
