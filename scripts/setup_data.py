#!/usr/bin/env python3
"""
Setup script for downloading and validating Sports ML Service datasets.

This script automates the process of downloading required CSV data files
from Kaggle for training ML models.

Usage:
    python scripts/setup_data.py      # Setup all sports
    python scripts/setup_data.py --sport nba        # Setup only NBA
    python scripts/setup_data.py --sport nfl        # Setup only NFL
    python scripts/setup_data.py --sport nascar     # Setup only NASCAR
    python scripts/setup_data.py --verify-only      # Only verify existing files
"""

import os
import sys
import subprocess
import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Dataset configurations
DATASETS = {
    "nba": {
        "description": "NBA Box Score Statistics",
   "files": {
 "PlayerStatistics.csv": {
    "kaggle_dataset": "vivozhang/nba-player-statistics",  # Example - update with actual
   "size_mb": 303,
 "required": True,
      "path": "data/nba/box_scores/"
            },
  "TeamStatistics.csv": {
   "kaggle_dataset": "vivozhang/nba-player-statistics",
     "size_mb": 32,
  "required": True,
       "path": "data/nba/box_scores/"
      },
   "Games.csv": {
         "kaggle_dataset": "vivozhang/nba-player-statistics",
     "size_mb": 9.5,
            "required": True,
    "path": "data/nba/box_scores/"
     },
    "Players.csv": {
                "kaggle_dataset": "vivozhang/nba-player-statistics",
            "size_mb": 0.5,
      "required": False,
     "path": "data/nba/box_scores/"
            },
            "LeagueSchedule24_25.csv": {
                "kaggle_dataset": "vivozhang/nba-player-statistics",
              "size_mb": 0.14,
        "required": False,
       "path": "data/nba/box_scores/"
       },
     "LeagueSchedule25_26.csv": {
"kaggle_dataset": "vivozhang/nba-player-statistics",
   "size_mb": 0.17,
    "required": False,
       "path": "data/nba/box_scores/"
   }
        }
    },
    "nfl": {
  "description": "NFL Team Statistics",
      "files": {
         "nfl_team_stats_2002-2024.csv": {
     "kaggle_dataset": "cfb-events/nfl-team-stats",  # Example - update with actual
         "size_mb": 1.16,
          "required": True,
           "path": "data/nfl/team_stats/"
            }
        }
    },
    "nascar": {
        "description": "NASCAR Race Data",
        "note": "NASCAR data is updated via GitHub Actions. Manual setup not required.",
  "files": {}
    }
}


def check_kaggle_installed() -> bool:
    """Check if Kaggle CLI is installed."""
    try:
        import kaggle
        return True
    except ImportError:
        return False


def check_kaggle_credentials() -> bool:
    """Check if Kaggle API credentials exist."""
    kaggle_dir = Path.home() / ".kaggle" / "kaggle.json"
    return kaggle_dir.exists()


def install_kaggle() -> bool:
    """Install Kaggle CLI."""
    logger.info("Installing Kaggle CLI...")
    try:
 subprocess.check_call([sys.executable, "-m", "pip", "install", "kaggle"])
        logger.info("? Kaggle CLI installed successfully")
        return True
    except subprocess.CalledProcessError:
        logger.error("? Failed to install Kaggle CLI")
        return False


def create_kaggle_credentials_instruction() -> str:
 """Create instruction text for setting up Kaggle credentials."""
    instruction = """
??????????????????????????????????????????????????????????????????????????????????
?       KAGGLE API CREDENTIALS REQUIRED       ?
??????????????????????????????????????????????????????????????????????????????????

To download datasets from Kaggle, you need to set up your API credentials:

1. Go to https://www.kaggle.com/account
2. Scroll to "API" section and click "Create New Token"
3. This downloads kaggle.json

4. Place the file in the correct location:
   - Linux/Mac: ~/.kaggle/kaggle.json
   - Windows: C:\\Users\\<YourUsername>\\.kaggle\\kaggle.json

5. Set permissions (Linux/Mac only):
   chmod 600 ~/.kaggle/kaggle.json

6. Run this script again!

More info: https://www.kaggle.com/settings/account
"""
    return instruction


def check_file_exists(filepath: Path) -> bool:
    """Check if a file exists."""
    return filepath.exists()


def get_file_size_mb(filepath: Path) -> float:
    """Get file size in MB."""
    return filepath.stat().st_size / (1024 * 1024)


def verify_csv_integrity(filepath: Path) -> bool:
    """Verify CSV file can be parsed."""
    try:
        import pandas as pd
   df = pd.read_csv(filepath, nrows=5)
        return True
    except Exception as e:
   logger.warning(f"  CSV integrity check failed: {e}")
        return False


def verify_files(sport: Optional[str] = None) -> Dict[str, bool]:
    """Verify all required files exist and are valid."""
    logger.info("\n" + "="*80)
    logger.info("VERIFYING DATA FILES")
    logger.info("="*80)
    
    sports_to_check = [sport] if sport else list(DATASETS.keys())
    all_valid = True
    results = {}
    
    for sport_name in sports_to_check:
        if sport_name not in DATASETS:
          logger.warning(f"Unknown sport: {sport_name}")
    continue
        
        logger.info(f"\n?? {sport_name.upper()}: {DATASETS[sport_name]['description']}")
        
        files = DATASETS[sport_name].get("files", {})
        if not files:
   logger.info(f"  ??  {DATASETS[sport_name].get('note', 'No files to verify')}")
       results[sport_name] = True
            continue
        
        sport_valid = True
        for filename, config in files.items():
         filepath = DATA_DIR / config["path"] / filename
    exists = check_file_exists(filepath)
            
            if exists:
             size_mb = get_file_size_mb(filepath)
                expected_size = config["size_mb"]
    size_ok = abs(size_mb - expected_size) / expected_size < 0.1  # 10% tolerance
           integrity_ok = verify_csv_integrity(filepath)
         
 status = "?" if (size_ok and integrity_ok) else "?"
        logger.info(f"  {status} {filename}")
           logger.info(f"     Size: {size_mb:.2f} MB (expected ~{expected_size} MB)")
   
            if not (size_ok and integrity_ok):
  sport_valid = False
      if not size_ok:
        logger.warning(f"     ? Size mismatch! File may be corrupted.")
        if not integrity_ok:
   logger.warning(f"     ? CSV integrity check failed!")
  else:
                status = "?" if config["required"] else "?"
   msg = "MISSING (required)" if config["required"] else "MISSING (optional)"
    logger.info(f"  {status} {filename}")
         logger.info(f"   {msg}")
            
     if config["required"]:
   sport_valid = False
        
        results[sport_name] = sport_valid
        all_valid = all_valid and sport_valid
    
    logger.info("\n" + "="*80)
    if all_valid:
        logger.info("? All required files verified successfully!")
    else:
    logger.info("? Some files are missing or invalid. Run setup to download.")
    logger.info("="*80 + "\n")
    
    return results


def download_dataset(sport: str) -> bool:
    """Download dataset for a sport from Kaggle."""
    if sport not in DATASETS:
   logger.error(f"Unknown sport: {sport}")
        return False
    
    dataset_config = DATASETS[sport]
    files = dataset_config.get("files", {})
    
    if not files:
        logger.info(f"No files to download for {sport}")
     return True
    
    logger.info(f"\n?? Downloading {sport.upper()} data...")
    
    for filename, config in files.items():
        filepath = DATA_DIR / config["path"] / filename
        
        if check_file_exists(filepath):
         logger.info(f"  ? {filename} already exists, skipping...")
            continue
        
 # Create directory if it doesn't exist
      filepath.parent.mkdir(parents=True, exist_ok=True)
     
        logger.info(f"  Downloading {filename}...")
        try:
            subprocess.check_call([
"kaggle", "datasets", "download",
     "-d", config["kaggle_dataset"],
           "-p", str(filepath.parent),
          "--unzip"
         ])
 logger.info(f"  ? Downloaded {filename}")
        except subprocess.CalledProcessError as e:
   logger.error(f"  ? Failed to download {filename}: {e}")
      if not config["required"]:
              logger.warning(f"     (This is optional, continuing...)")
         continue
       return False
    
    return True


def setup_all(sport: Optional[str] = None) -> bool:
    """Main setup function."""
    logger.info("\n" + "="*80)
    logger.info("SPORTS ML SERVICE - DATA SETUP")
    logger.info("="*80)
    
    # Check Kaggle installation
    if not check_kaggle_installed():
        logger.info("\nKaggle CLI not installed. Installing...")
     if not install_kaggle():
            logger.error("Failed to install Kaggle CLI")
          return False
    
    # Check Kaggle credentials
    if not check_kaggle_credentials():
   logger.error("\n? Kaggle API credentials not found!")
        logger.error(create_kaggle_credentials_instruction())
return False
    
    # Download datasets
    sports_to_download = [sport] if sport else [s for s in DATASETS.keys() if DATASETS[s].get("files")]
    
    all_success = True
    for s in sports_to_download:
      if not download_dataset(s):
            all_success = False
    
    # Verify all files
    verify_files(sport)
    
    if all_success:
     logger.info("\n? Setup completed successfully!")
logger.info("You can now run the ML service with your data.")
        return True
  else:
        logger.error("\n? Setup completed with errors. Check logs above.")
    return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup script for Sports ML Service datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/setup_data.py     # Setup all sports
  python scripts/setup_data.py --sport nba # Setup only NBA
  python scripts/setup_data.py --verify-only  # Only verify existing files
        """
    )
  
    parser.add_argument(
   "--sport",
        choices=["nba", "nfl", "nascar"],
        help="Specific sport to setup (default: all)"
    )
parser.add_argument(
        "--verify-only",
        action="store_true",
     help="Only verify existing files, don't download"
    )
    parser.add_argument(
 "--install-kaggle",
        action="store_true",
        help="Install Kaggle CLI and exit"
    )
    
    args = parser.parse_args()
    
    # Handle special cases
    if args.install_kaggle:
 success = install_kaggle() if not check_kaggle_installed() else True
        sys.exit(0 if success else 1)
    
    if args.verify_only:
        results = verify_files(args.sport)
 all_ok = all(results.values())
        sys.exit(0 if all_ok else 1)
    
    # Main setup
    success = setup_all(args.sport)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
