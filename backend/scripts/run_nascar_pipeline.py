"""
NASCAR Data Pipeline Orchestrator
---------------------------------
Reliably updates the entire NASCAR model ecosystem:
1. Validates R environment.
2. Runs R script to fetch latest data (`nascarR` package).
3. Enhances data (feature engineering).
4. Retrains clustering (Archetypes).
5. Retrains prediction ensemble (XGB+RF).
"""

import subprocess
import sys
import shutil
from pathlib import Path
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent
R_SCRIPT = BASE_DIR / "update_nascar_data.R"
ENHANCE_SCRIPT = BASE_DIR / "enhance_nascar_data.py"
ARCHETYPE_SCRIPT = BASE_DIR / "train_nascar_archetypes.py"
MODEL_SCRIPT = BASE_DIR / "train_nascar_model.py"

def check_r_installed():
    """Check if R is installed and accessible."""
    if shutil.which("Rscript") is None:
        logger.error("R (Rscript) is not found in PATH. Please install R to fetch new data.")
        return False
    return True

def run_step(command, description):
    """Run a pipeline step."""
    logger.info(f"STARTING: {description}...")
    try:
        result = subprocess.run(
            command, 
            check=True, 
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        logger.info(f"COMPLETED: {description}")
        logger.debug(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FAILED: {description}")
        logger.error(e.stderr)
        return False

def main():
    logger.info("="*60)
    logger.info("NASCAR UPDATE PIPELINE")
    logger.info("="*60)

    # 1. Fetch Data (R)
    # Only run if R is available. If not, warn user but proceed (maybe manual drop)
    if check_r_installed():
        if not run_step(["Rscript", "update_nascar_data.R"], "Fetching Data (R)"):
            logger.warning("Data fetch failed. Continuing with existing data...")
    else:
        logger.warning("Skipping data fetch (R not installed). Using existing raw data.")

    # 2. Extract & Feature Engineer
    if not run_step([sys.executable, "enhance_nascar_data.py"], "Feature Engineering"):
        logger.error("Pipeline stopped due to enhancement failure.")
        sys.exit(1)

    # 3. Clustering (Archetypes)
    if not run_step([sys.executable, "train_nascar_archetypes.py"], "Driver Clustering"):
        logger.warning("Clustering failed. Proceeding with old archetypes...")

    # 4. Ensemble Training
    if not run_step([sys.executable, "train_nascar_model.py"], "Ensemble Training"):
        logger.error("Model training failed.")
        sys.exit(1)

    logger.info("="*60)
    logger.info("PIPELINE SUCCESSFUL")
    logger.info("="*60)

if __name__ == "__main__":
    main()
