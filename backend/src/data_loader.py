"""
Unified data loading utilities for all sports.

Supports hybrid loading: Database first, CSV fallback.
"""
from pathlib import Path
from typing import Optional
import pandas as pd
import logging
from sports.base import BaseSport

logger = logging.getLogger(__name__)

# Database configuration
USE_DATABASE = True  # Set to False to force CSV loading
DATABASE_URL = "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"


def load_sport_data(sport: BaseSport) -> pd.DataFrame:
    """
    Load data for a given sport implementation.
    
    Priority:
    1. PostgreSQL database (if available and has data)
    2. CSV files (fallback)
    """
    if USE_DATABASE:
        try:
            df = load_from_database(sport.name)
            if df is not None and not df.empty:
                logger.info(f"Loaded {len(df)} rows for {sport.name} from database")
                return df
        except Exception as e:
            logger.warning(f"Database load failed for {sport.name}, falling back to CSV: {e}")
    
    # Fallback to CSV
    logger.info(f"Loading {sport.name} from CSV files")
    return sport.load_data()


def load_from_database(sport_name: str) -> Optional[pd.DataFrame]:
    """
    Load sport data from PostgreSQL database.
    
    Returns DataFrame or None if database unavailable.
    """
    try:
        import asyncpg
        import asyncio
        import json
        
        async def fetch_data():
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # Get sport ID
                sport_id = await conn.fetchval(
                    "SELECT id FROM sports WHERE name = $1", sport_name
                )
                if not sport_id:
                    return None
                
                # Fetch results with expanded metadata
                rows = await conn.fetch("""
                    SELECT r.*, 
                           h.name as home_team, 
                           a.name as away_team,
                           t.name as track_name
                    FROM results r
                    LEFT JOIN entities h ON h.id = r.home_entity_id
                    LEFT JOIN entities a ON a.id = r.away_entity_id
                    LEFT JOIN entities t ON t.id = r.home_entity_id AND t.type = 'track'
                    WHERE r.sport_id = $1
                    ORDER BY r.season, r.game_date, r.id
                    LIMIT 500000
                """, sport_id)
                
                if not rows:
                    return None
                
                # Convert to DataFrame
                df = pd.DataFrame([dict(row) for row in rows])
                
                # Expand metadata JSON into columns
                if 'metadata' in df.columns:
                    def safe_json_parse(x):
                        if x is None:
                            return {}
                        if isinstance(x, dict):
                            return x
                        try:
                            return json.loads(x)
                        except:
                            return {}
                    
                    metadata_df = pd.json_normalize(df['metadata'].apply(safe_json_parse))
                    
                    # Don't duplicate columns that already exist
                    for col in metadata_df.columns:
                        if col not in df.columns:
                            df[col] = metadata_df[col]
                    
                    df = df.drop('metadata', axis=1)
                
                return df
                
            finally:
                await conn.close()
        
        # Run async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(fetch_data())
        finally:
            loop.close()
            
    except ImportError:
        logger.warning("asyncpg not installed, using CSV fallback")
        return None
    except Exception as e:
        logger.warning(f"Database query failed: {e}")
        return None


def chronological_split(df: pd.DataFrame, test_start_season: Optional[int] = None,
                       time_column: str = 'schedule_season') -> tuple:
    """
    Split dataframe chronologically by season.

    Args:
        df: DataFrame to split
        test_start_season: Season year where test set starts
        time_column: Column name containing season/year information

    Returns:
        Tuple of (train_df, test_df, test_start_season)
    """
    # Try multiple possible time column names
    possible_columns = [time_column, 'season', 'year', 'schedule_season']
    actual_column = None
    
    for col in possible_columns:
        if col in df.columns:
            actual_column = col
            break
    
    if actual_column is None:
        raise ValueError(f'No time column found. Tried: {possible_columns}')
    
    seasons = sorted(df[actual_column].dropna().unique())
    if not seasons:
        raise ValueError(f'No seasons available in column {actual_column}')

    if test_start_season is None:
        # Use the last 10 seasons for testing if available, else last 20% of seasons
        if len(seasons) > 15:
            test_start_season = seasons[-10]
        else:
            k = max(1, int(len(seasons) * 0.2))
            test_start_season = seasons[-k]

    train = df[df[actual_column] < test_start_season].copy()
    test = df[df[actual_column] >= test_start_season].copy()

    return train, test, test_start_season

