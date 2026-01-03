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


async def _run_python_fallback_simulation(n_simulations: int) -> Dict:
    """
    Python fallback simulation when R is not available.
    Generates reasonable estimates based on team strength priors.
    """
    import random
    
    # NFL teams with estimated strength tiers (1=best, 4=worst)
    nfl_teams = {
        "AFC": [
            {"team": "KC", "division": "West", "tier": 1},
            {"team": "BUF", "division": "East", "tier": 1},
            {"team": "BAL", "division": "North", "tier": 1},
            {"team": "MIA", "division": "East", "tier": 2},
            {"team": "CLE", "division": "North", "tier": 2},
            {"team": "JAX", "division": "South", "tier": 2},
            {"team": "CIN", "division": "North", "tier": 2},
            {"team": "HOU", "division": "South", "tier": 2},
            {"team": "DEN", "division": "West", "tier": 3},
            {"team": "NYJ", "division": "East", "tier": 3},
            {"team": "LV", "division": "West", "tier": 3},
            {"team": "PIT", "division": "North", "tier": 3},
            {"team": "IND", "division": "South", "tier": 3},
            {"team": "TEN", "division": "South", "tier": 4},
            {"team": "LAC", "division": "West", "tier": 3},
            {"team": "NE", "division": "East", "tier": 4},
        ],
        "NFC": [
            {"team": "SF", "division": "West", "tier": 1},
            {"team": "PHI", "division": "East", "tier": 1},
            {"team": "DAL", "division": "East", "tier": 1},
            {"team": "DET", "division": "North", "tier": 1},
            {"team": "GB", "division": "North", "tier": 2},
            {"team": "SEA", "division": "West", "tier": 2},
            {"team": "TB", "division": "South", "tier": 2},
            {"team": "LAR", "division": "West", "tier": 2},
            {"team": "MIN", "division": "North", "tier": 2},
            {"team": "NO", "division": "South", "tier": 3},
            {"team": "ATL", "division": "South", "tier": 3},
            {"team": "WAS", "division": "East", "tier": 3},
            {"team": "CHI", "division": "North", "tier": 3},
            {"team": "NYG", "division": "East", "tier": 4},
            {"team": "ARI", "division": "West", "tier": 4},
            {"team": "CAR", "division": "South", "tier": 4},
        ]
    }
    
    # Generate probabilistic outcomes based on tier
    def get_probs(tier):
        base = {
            1: {"playoff": 85, "division": 40, "conf": 20, "sb": 10, "wins": 12},
            2: {"playoff": 55, "division": 25, "conf": 10, "sb": 4, "wins": 10},
            3: {"playoff": 30, "division": 15, "conf": 5, "sb": 2, "wins": 8},
            4: {"playoff": 15, "division": 8, "conf": 2, "sb": 0.5, "wins": 5},
        }[tier]
        # Add randomness
        return {
            k: round(max(0, min(100, v + random.uniform(-10, 10))), 1)
            for k, v in base.items()
        }
    
    afc_results = []
    nfc_results = []
    
    for team in nfl_teams["AFC"]:
        probs = get_probs(team["tier"])
        afc_results.append({
            "team": team["team"],
            "conf": "AFC",
            "division": team["division"],
            "wins": round(probs["wins"] + random.uniform(-1, 1)),
            "losses": 17 - round(probs["wins"] + random.uniform(-1, 1)),
            "playoff_pct": probs["playoff"],
            "division_pct": probs["division"],
            "conf_pct": probs["conf"],
            "super_bowl_pct": probs["sb"]
        })
    
    for team in nfl_teams["NFC"]:
        probs = get_probs(team["tier"])
        nfc_results.append({
            "team": team["team"],
            "conf": "NFC",
            "division": team["division"],
            "wins": round(probs["wins"] + random.uniform(-1, 1)),
            "losses": 17 - round(probs["wins"] + random.uniform(-1, 1)),
            "playoff_pct": probs["playoff"],
            "division_pct": probs["division"],
            "conf_pct": probs["conf"],
            "super_bowl_pct": probs["sb"]
        })
    
    # Sort by playoff probability
    afc_results.sort(key=lambda x: x["super_bowl_pct"], reverse=True)
    nfc_results.sort(key=lambda x: x["super_bowl_pct"], reverse=True)
    
    all_teams = afc_results + nfc_results
    all_teams.sort(key=lambda x: x["super_bowl_pct"], reverse=True)
    
    return {
        "simulations": n_simulations,
        "generated_at": datetime.now().isoformat(),
        "season": datetime.now().year if datetime.now().month > 2 else datetime.now().year - 1,
        "afc": afc_results,
        "nfc": nfc_results,
        "all_teams": all_teams,
        "cached": False,
        "python_fallback": True,
        "note": "Generated using Python fallback (R not installed)"
    }


STATUS_FILE = RESULTS_DIR / "simulation_status.json"


def _update_status(message: str, progress: int = 0, is_error: bool = False):
    """Write status to JSON file for UI polling."""
    try:
        status_data = {
            "status": "error" if is_error else "running",
            "message": message,
            "progress": progress,
            "timestamp": datetime.now().isoformat()
        }
        with open(STATUS_FILE, 'w') as f:
            json.dump(status_data, f)
    except Exception as e:
        logger.error(f"Failed to update status: {e}")


def _ensure_schedules_exist() -> bool:
    """Download schedules.csv if it doesn't exist."""
    schedules_path = Path("/app/data/nflverse/schedules.csv")
    
    if schedules_path.exists():
        logger.info("schedules.csv already exists")
        return True
    
    logger.info("schedules.csv not found, downloading...")
    _update_status("Downloading NFL schedule data...", 2)
    
    try:
        import nfl_data_py as nfl
        from datetime import datetime
        
        # Determine current season
        now = datetime.now()
        current_year = now.year if now.month > 2 else now.year - 1
        years = list(range(2020, current_year + 1))
        
        # Download schedules
        df = nfl.import_schedules(years)
        
        # Ensure directory exists
        schedules_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save to CSV
        df.to_csv(schedules_path, index=False)
        logger.info(f"Downloaded {len(df)} games to {schedules_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to download schedules: {e}")
        _update_status(f"Failed to download schedules: {e}", 0, True)
        return False


def _run_r_simulation_process(n_simulations: int) -> Dict:
    """Run R script via Popen and monitor output for progress."""
    import re
    
    # Ensure data exists before starting
    if not _ensure_schedules_exist():
        return {"error": True, "message": "Could not download NFL schedule data"}
    
    _update_status("Starting R process...", 5)
    
    try:
        process = subprocess.Popen(
            [
                "Rscript",
                str(R_SCRIPT_PATH),
                str(n_simulations),
                str(RESULTS_FILE)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(SCRIPT_DIR),
            bufsize=1
        )
        
        stdout_lines = []
        stderr_lines = []
        
        # Read stdout line by line
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
                
            if line:
                stdout_lines.append(line)
                # Parse progress
                # "Simulating Week 5 (14 games)..."
                match = re.search(r"Simulating Week (\d+)", line)
                if match:
                    week = int(match.group(1))
                    # Rough progress estimation (Weeks 1-18 + Playoffs ~22 weeks)
                    progress = int(10 + (week / 22 * 80))
                    _update_status(f"Simulating Week {week} logic...", progress)
                elif "Running" in line:
                    _update_status("Initializing nflseedR...", 10)
                elif "Writing" in line or "Success" in line:
                    _update_status("Finalizing results...", 95)
        
        # Capture remaining stderr
        stderr_output = process.stderr.read()
        if stderr_output:
            logger.warning(f"R Stderr: {stderr_output}")
            
        return_code = process.wait()
        
        if return_code != 0:
            error_msg = f"R script failed with code {return_code}"
            logger.error(f"{error_msg}\nStderr: {stderr_output}")
            _update_status(error_msg, 0, True)
            return {"error": True, "message": f"{error_msg}: {stderr_output}"}
            
        # Success
        _update_status("Simulation complete!", 100)
        
        if RESULTS_FILE.exists():
            with open(RESULTS_FILE) as f:
                results = json.load(f)
            logger.info("Simulation success, results loaded.")
            return results
        else:
            return {"error": True, "message": "Results file missing after success"}
            
    except Exception as e:
        logger.error(f"Exception running R script: {e}")
        _update_status(f"Error: {str(e)}", 0, True)
        return {"error": True, "message": str(e)}



def get_cached_simulation() -> Optional[Dict]:
    """Get cached simulation results without running new simulation."""
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


async def run_nfl_simulation(
    n_simulations: int = 1000,
    force_refresh: bool = False
) -> Dict:
    """
    Run NFL season simulation using nflseedR.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check cache
    if not force_refresh and RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                cached = json.load(f)
            generated = datetime.fromisoformat(cached.get("generated_at", "2000-01-01"))
            if (datetime.now() - generated).total_seconds() / 3600 < 6:
                logger.info("Using cached results")
                cached["cached"] = True
                return cached
        except:
            pass
    
    if not check_r_installed():
        _update_status("R not found, using fallback...", 0)
        return await _run_python_fallback_simulation(n_simulations)
    
    # Run in thread executor to allow event loop to serve status updates
    import asyncio
    logger.info("Starting simulation thread...")
    return await asyncio.to_thread(_run_r_simulation_process, n_simulations)


def get_simulation_status() -> Dict:
    """Get current status from file."""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"status": "idle", "message": "Ready to simulate", "progress": 0}


# For testing
if __name__ == "__main__":
    import asyncio
    async def test():
        # Start status watcher
        async def watch():
            while True:
                print(get_simulation_status())
                await asyncio.sleep(1)
                
        task = asyncio.create_task(watch())
        res = await run_nfl_simulation(10, force_refresh=True)
        print("Done")
        task.cancel()
    
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        pass

