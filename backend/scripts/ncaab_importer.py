"""
NCAAB Importer - Historical Data Download
Uses hoopR (via Rscript) to fetch schedule and boxscore data.
"""

import logging
import asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

import subprocess
import os

SCRIPT_DIR = Path(__file__).parent
R_SCRIPT_PATH = SCRIPT_DIR / "ncaab_importer.R"

# Use relative path that works locally, fallback to Docker path
_local_data_dir = SCRIPT_DIR.parent / "data" / "ncaab"
_docker_data_dir = Path("/app/data/ncaab")
DATA_DIR = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

async def import_ncaab_data(start_year: int = 2018, end_year: int = 2025):
    """
    Import NCAAB data using hoopR (R script) to avoid sportsdataverse version crashes.
    """
    logger.info(f"Starting hybrid NCAAB import for {start_year}-{end_year}")
    
    try:
        # Construct command
        cmd = [
            "Rscript",
            str(R_SCRIPT_PATH),
            str(start_year),
            str(end_year),
            str(DATA_DIR)
        ]
        
        logger.info(f"Running R command: {' '.join(cmd)}")
        
        # Run process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if stdout:
            logger.info(f"R Output: {stdout.decode().strip()}")
        if stderr:
             logger.warning(f"R Stderr: {stderr.decode().strip()}")
             
        if process.returncode != 0:
            return {"success": False, "error": f"R script failed with code {process.returncode}"}

        return {
            "success": True,
            "message": f"Imported NCAAB data via hoopR for {start_year}-{end_year}.",
            "data_dir": str(DATA_DIR),
            "games_processed": 1  # Placeholder since R script doesn't output count
        }
        
    except Exception as e:
        logger.error(f"Error in hybrid NCAAB import: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    asyncio.run(import_ncaab_data(2024, 2025))
