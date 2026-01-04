"""
College Baseball Importer - Python wrapper for baseballr R script
"""

import json
import subprocess
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
R_SCRIPT_PATH = SCRIPT_DIR / "college_baseball_importer.R"
DATA_DIR = Path("/app/data/baseball")
STATUS_FILE = DATA_DIR / "import_status.json"


def _update_status(message: str, progress: int = 0, is_error: bool = False, division: int = 1):
    """Write status to JSON file for UI polling."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        status_data = {
            "status": "error" if is_error else "running",
            "message": message,
            "progress": progress,
            "division": division,
            "timestamp": datetime.now().isoformat()
        }
        with open(STATUS_FILE, 'w') as f:
            json.dump(status_data, f)
    except Exception as e:
        logger.error(f"Failed to update status: {e}")


def get_import_status() -> Dict:
    """Get current import status."""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"status": "idle", "message": "Ready to import", "progress": 0}


def get_teams(division: int = 1) -> List[Dict]:
    """Get list of teams for a division."""
    teams_file = DATA_DIR / f"teams_d{division}.json"
    if teams_file.exists():
        try:
            with open(teams_file) as f:
                return json.load(f)
        except:
            pass
    return []


def get_team_stats(team_id: int, stat_type: str = "batting") -> Optional[Dict]:
    """Get team stats (batting or pitching)."""
    import pandas as pd
    stats_file = DATA_DIR / "stats" / f"{team_id}_{stat_type}.csv"
    if stats_file.exists():
        try:
            df = pd.read_csv(stats_file)
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(f"Error reading stats: {e}")
    return None


def get_team_schedule(team_id: int) -> Optional[List[Dict]]:
    """Get team schedule/results."""
    import pandas as pd
    schedule_file = DATA_DIR / "schedules" / f"{team_id}_schedule.csv"
    if schedule_file.exists():
        try:
            df = pd.read_csv(schedule_file)
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(f"Error reading schedule: {e}")
    return None


def get_import_summary(division: int = 1) -> Optional[Dict]:
    """Get import summary for a division."""
    summary_file = DATA_DIR / f"import_summary_d{division}.json"
    if summary_file.exists():
        try:
            with open(summary_file) as f:
                return json.load(f)
        except:
            pass
    return None


def _run_import_process(division: int, year: int, team_id: Optional[int] = None) -> Dict:
    """Run R import script and capture output."""
    import re
    
    _update_status("Starting R process...", 5, division=division)
    
    try:
        cmd = [
            "Rscript",
            str(R_SCRIPT_PATH),
            str(division),
            str(year),
            str(DATA_DIR)
        ]
        
        if team_id:
            cmd.append(str(team_id))
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(SCRIPT_DIR),
            bufsize=1
        )
        
        stdout_lines = []
        team_count = 0
        current_team = 0
        
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
                
            if line:
                stdout_lines.append(line)
                logger.info(f"R: {line.strip()}")
                
                # Parse progress
                team_match = re.search(r"\[(\d+)/(\d+)\]", line)
                if team_match:
                    current_team = int(team_match.group(1))
                    total_teams = int(team_match.group(2))
                    progress = int(10 + (current_team / total_teams * 85))
                    team_name = line.split("]")[1].strip().split("(")[0].strip()
                    _update_status(f"Importing {team_name}...", progress, division=division)
                elif "Fetching" in line:
                    _update_status(line.strip(), 10, division=division)
                elif "Success" in line:
                    _update_status("Import complete!", 100, division=division)
        
        stderr_output = process.stderr.read()
        if stderr_output:
            logger.warning(f"R Stderr: {stderr_output}")
            
        return_code = process.wait()
        
        if return_code != 0:
            error_msg = f"R script failed with code {return_code}"
            logger.error(f"{error_msg}\nStderr: {stderr_output}")
            _update_status(error_msg, 0, True, division)
            return {"error": True, "message": f"{error_msg}: {stderr_output}"}
        
        # Success - return summary
        _update_status("Import complete!", 100, division=division)
        summary = get_import_summary(division)
        if summary:
            return {"success": True, **summary}
        return {"success": True, "message": "Import completed"}
        
    except Exception as e:
        logger.error(f"Exception running R script: {e}")
        _update_status(f"Error: {str(e)}", 0, True, division)
        return {"error": True, "message": str(e)}


async def run_college_baseball_import(
    division: int = 1,
    year: Optional[int] = None,
    team_id: Optional[int] = None
) -> Dict:
    """
    Run college baseball import.
    
    Args:
        division: NCAA division (1, 2, or 3)
        year: Season year (defaults to current year)
        team_id: Optional specific team to import
    """
    if year is None:
        year = datetime.now().year
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting college baseball import: D{division}, {year}")
    return await asyncio.to_thread(_run_import_process, division, year, team_id)


# Alias for API compatibility
run_import = run_college_baseball_import


# LSU Tigers team ID for easy testing
LSU_TEAM_ID = 365  # This is approximate, will need to verify


if __name__ == "__main__":
    import asyncio
    
    async def test():
        # Test import D1 teams
        result = await run_college_baseball_import(division=1, year=2024)
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
