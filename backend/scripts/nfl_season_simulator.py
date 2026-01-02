"""
NFL Season Simulator - Python wrapper for nflseedR
Calls R script to run simulations and returns results.
"""

import json
import subprocess
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
R_SCRIPT_PATH = SCRIPT_DIR / "nfl_season_simulator.R"
RESULTS_DIR = Path("/app/data/nfl")
RESULTS_FILE = RESULTS_DIR / "season_simulation.json"


def check_r_installed() -> bool:
    """Check if R is installed and available."""
    try:
        result = subprocess.run(
            ["Rscript", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def run_nfl_simulation(
    n_simulations: int = 1000,
    force_refresh: bool = False
) -> Dict:
    """
    Run NFL season simulation using nflseedR.
    
    Args:
        n_simulations: Number of simulations to run (default 1000)
        force_refresh: Force re-run even if recent results exist
        
    Returns:
        Dictionary with simulation results or cached results
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if we have recent results (less than 6 hours old)
    if not force_refresh and RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                cached = json.load(f)
            
            generated_at = datetime.fromisoformat(cached.get("generated_at", "2000-01-01"))
            age_hours = (datetime.now() - generated_at).total_seconds() / 3600
            
            if age_hours < 6:
                logger.info(f"Using cached simulation results ({age_hours:.1f} hours old)")
                cached["cached"] = True
                return cached
        except Exception as e:
            logger.warning(f"Error reading cached results: {e}")
    
    # Check R is installed
    if not check_r_installed():
        logger.error("R is not installed or not in PATH")
        return {
            "error": True,
            "message": "R is not installed. Install R and nflseedR package to run simulations.",
            "install_instructions": "Install R from https://cran.r-project.org/ then run: install.packages('nflseedR')"
        }
    
    # Run R script
    logger.info(f"Running NFL simulation with {n_simulations} iterations...")
    
    try:
        result = subprocess.run(
            [
                "Rscript",
                str(R_SCRIPT_PATH),
                str(n_simulations),
                str(RESULTS_FILE)
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(SCRIPT_DIR)
        )
        
        if result.returncode != 0:
            logger.error(f"R script error: {result.stderr}")
            return {
                "error": True,
                "message": f"R script failed: {result.stderr}"
            }
        
        # Read results
        if RESULTS_FILE.exists():
            with open(RESULTS_FILE) as f:
                results = json.load(f)
            
            if results.get("error"):
                return results
            
            results["cached"] = False
            logger.info(f"Simulation complete: {len(results.get('all_teams', []))} teams")
            return results
        else:
            return {
                "error": True,
                "message": "Results file not generated"
            }
            
    except subprocess.TimeoutExpired:
        return {
            "error": True,
            "message": "Simulation timed out after 5 minutes"
        }
    except Exception as e:
        logger.error(f"Error running simulation: {e}")
        return {
            "error": True,
            "message": str(e)
        }


def get_cached_simulation() -> Optional[Dict]:
    """Get cached simulation results without running new simulation."""
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


# For testing
if __name__ == "__main__":
    import asyncio
    
    async def test():
        result = await run_nfl_simulation(n_simulations=100)
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
