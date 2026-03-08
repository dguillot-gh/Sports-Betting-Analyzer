
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

async def import_parquet(conn, sport_id: int, series: str, file_path: Path):
    logger.info(f"Importing {series} from {file_path}...")
    df = pd.read_parquet(file_path)
    logger.info(f"Loaded {len(df)} rows")
    
    # Standardize columns (based on typical nascaR.data format)
    # The search results said columns might be 'Season', 'Race', 'Track', 'Driver', etc.
    # We need to map them to what our system expects or just store in metadata.
    
    imported = 0
    # Process in batches
    batch_size = 1000
    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i+batch_size]
        for _, row in batch.iterrows():
            try:
                # Season is the year
                season = int(row.get('Season') or row.get('season') or 2026)
                
                # Check for 2026 specifically if we want just recent
                # But usually we import everything and let the DB upsert handle it
                
                driver = row.get('Driver') or row.get('driver') or "Unknown"
                track = row.get('Track') or row.get('track') or "Unknown"
                race_num = row.get('Race') or row.get('race')
                
                metadata = row.to_dict()
                # Clean NaNs for JSON
                metadata = {k: v for k, v in metadata.items() if not pd.isna(v)}
                
                content_hash = compute_hash({
                    'sport': 'nascar',
                    'series': series,
                    'season': season,
                    'driver': driver,
                    'track': track,
                    'race_num': race_num
                })
                
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, track, metadata, content_hash)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, season, series, track, json.dumps(metadata), content_hash
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Error importing row: {e}")
        
        logger.info(f"Progress: {i + len(batch)}/{len(df)}")
        
    return imported

async def run_import():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        if not sport_id:
            sport_id = await conn.fetchval("INSERT INTO sports (name) VALUES ('nascar') RETURNING id")
            
        for series, url in PARQUET_URLS.items():
            filename = f"{series}_series.parquet"
            path = await download_file(url, filename)
            if path:
                count = await import_parquet(conn, sport_id, series, path)
                logger.info(f"Imported {count} results for {series}")
                
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_import())
