"""
NCAAB Importer - Historical Data Download
Uses sportsdataverse (mbb) to fetch schedule and boxscore data.
"""

import logging
import asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd
import sportsdataverse.mbb as mbb_loaders

logger = logging.getLogger(__name__)

# Use relative path that works locally, fallback to Docker path
SCRIPT_DIR = Path(__file__).parent
_local_data_dir = SCRIPT_DIR.parent / "data" / "ncaab"
_docker_data_dir = Path("/app/data/ncaab")
DATA_DIR = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

async def import_ncaab_data(start_year: int = 2018, end_year: int = 2025):
    """
    Import NCAAB data for a range of years.
    """
    logger.info(f"Starting NCAAB import for {start_year}-{end_year}")
    
    seasons = range(start_year, end_year + 1)
    
    try:
        # 1. Schedule Data
        logger.info("Fetching schedules...")
        df_schedule = mbb_loaders.load_mbb_schedule(seasons=seasons)
        if not df_schedule.empty:
            schedule_path = DATA_DIR / "ncaab_schedule_history.parquet"
            df_schedule.write_parquet(schedule_path)
            logger.info(f"Saved {len(df_schedule)} games to {schedule_path}")
        
        # 2. Team Boxscores (Stats)
        logger.info("Fetching team boxscores...")
        df_box = mbb_loaders.load_mbb_team_boxscore(seasons=seasons)
        if not df_box.empty:
            box_path = DATA_DIR / "ncaab_team_box_history.parquet"
            df_box.write_parquet(box_path)
            logger.info(f"Saved {len(df_box)} boxscores to {box_path}")
            
        return {
            "success": True,
            "message": f"Imported {len(df_schedule)} games and {len(df_box)} boxscores.",
            "seasons": list(seasons)
        }
        
    except Exception as e:
        logger.error(f"Error importing NCAAB data: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    asyncio.run(import_ncaab_data(2024, 2025))
