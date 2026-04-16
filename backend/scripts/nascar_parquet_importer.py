
import asyncio
import pandas as pd
import requests
import json
import hashlib
import os
from pathlib import Path
import asyncpg
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database URL
from src.config import DATABASE_URL

DATA_DIR = Path("/app/data/nascar/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PARQUET_URLS = {
    "cup": "https://nascar.kylegrealis.com/cup_series.parquet",
    "xfinity": "https://nascar.kylegrealis.com/nxs_series.parquet",
    "trucks": "https://nascar.kylegrealis.com/truck_series.parquet"
}

def compute_hash(data: dict) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

async def download_file(url: str, filename: str):
    logger.info(f"Downloading {url}...")
    response = requests.get(url, timeout=300)
    if response.status_code == 200:
        path = DATA_DIR / filename
        path.write_bytes(response.content)
        logger.info(f"Saved to {path}")
        return path
    else:
        logger.error(f"Failed to download {url}: {response.status_code}")
        return None

async def import_parquet(conn, sport_id: int, series: str, file_path: Path, min_year: int = 2012):
    logger.info(f"Importing {series} from {file_path} (min_year={min_year})...")
    df = pd.read_parquet(file_path)
    
    # Filter by year early to save processing time
    if 'Season' in df.columns:
        df = df[df['Season'] >= min_year]
    elif 'season' in df.columns:
        df = df[df['season'] >= min_year]
        
    logger.info(f"Loaded {len(df)} rows after year filtering")
    
    new_count = 0
    updated_count = 0
    
    # Process in batches
    batch_size = 1000
    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i+batch_size]
        for _, row in batch.iterrows():
            try:
                # Mapping from Parquet/nascaR.data format to our DB metadata format
                mapping = {
                    'Season': 'season',
                    'Driver': 'driver_name',
                    'Finish': 'finish',
                    'Start': 'start',
                    'Track': 'track',
                    'Race': 'race_num',
                    'Laps': 'laps',
                    'Led': 'led',
                    'Pts': 'pts',
                    'Status': 'status',
                    'Team': 'team',
                    'Manufacturer': 'make',
                    'Rating': 'rating',
                    'Series': 'series_label'
                }

                # Extract standardized values
                season = int(row.get('Season') or row.get('season') or 2026)
                
                # Double check year filter in row loop just in case
                if season < min_year:
                    continue

                driver = row.get('Driver') or row.get('driver') or "Unknown"
                track = row.get('Track') or row.get('track') or "Unknown"
                race_num = row.get('Race') or row.get('race')
                
                # Build metadata with both standardized and original keys for compatibility
                metadata = {}
                row_dict = row.to_dict()
                for raw_key, val in row_dict.items():
                    if pd.isna(val):
                        continue
                    
                    # Store original
                    metadata[raw_key] = val
                    # Store standardized if mapped
                    if raw_key in mapping:
                        metadata[mapping[raw_key]] = val

                # Ensure critical fields aren't missing
                if 'driver_name' not in metadata and 'Driver' in metadata:
                    metadata['driver_name'] = metadata['Driver']
                if 'finish' not in metadata and 'Finish' in metadata:
                    metadata['finish'] = metadata['Finish']
                
                content_hash = compute_hash({
                    'sport': 'nascar',
                    'series': series,
                    'season': season,
                    'driver': driver,
                    'track': track,
                    'race_num': race_num
                })
                
                is_new = await conn.fetchval(
                    """INSERT INTO results (sport_id, season, series, track, metadata, content_hash)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (content_hash)
                       DO UPDATE SET metadata = EXCLUDED.metadata
                       RETURNING (xmax = 0)""",
                    sport_id, season, series, track, json.dumps(metadata), content_hash
                )
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                logger.error(f"Error importing row: {e}")
        
        logger.info(f"Progress: {min(i + batch_size, len(df))}/{len(df)}")
        
    return {"total": new_count + updated_count, "new": new_count, "updated": updated_count}

async def run_import(min_year: int = 2012):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        if not sport_id:
            sport_id = await conn.fetchval("INSERT INTO sports (name) VALUES ('nascar') RETURNING id")
            
        summary = {"rows": 0, "new": 0, "updated": 0}
        for series, url in PARQUET_URLS.items():
            filename = f"{series}_series.parquet"
            path = await download_file(url, filename)
            if path:
                res = await import_parquet(conn, sport_id, series, path, min_year=min_year)
                logger.info(f"Imported {res['total']} results for {series} ({res['new']} new, {res['updated']} updated)")
                summary["rows"] += res["total"]
                summary["new"] += res["new"]
                summary["updated"] += res["updated"]
        return summary
                
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_import())
