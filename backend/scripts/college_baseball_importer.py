"""
College Baseball Importer - Hybrid Python + R Data Sources
Primary: collegebaseball Python package (stats.ncaa.org API)
Fallback: baseballr R script (for live/current season data)
"""

import json
import subprocess
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Literal
import time
import pandas as pd

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
R_SCRIPT_PATH = SCRIPT_DIR / "college_baseball_importer.R"

# Use relative path that works locally, fallback to Docker path
_local_data_dir = SCRIPT_DIR.parent / "data" / "baseball"
_docker_data_dir = Path("/app/data/baseball")
DATA_DIR = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = DATA_DIR / "import_status.json"


def _update_status(message: str, progress: int = 0, is_error: bool = False, 
                   division: int = 1, source: str = ""):
    """Write status to JSON file for UI polling."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        status_data = {
            "status": "error" if is_error else "running",
            "message": message,
            "progress": progress,
            "division": division,
            "source": source,
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


# ============================================================
# Python Import (collegebaseball package)
# ============================================================

def _import_via_python(division: int, year: int, progress_callback=None) -> Dict:
    """
    Import college baseball data using the collegebaseball Python package.
    Returns dict with success status and imported data.
    """
    try:
        from collegebaseball import ncaa_scraper
        import os
        import collegebaseball
    except ImportError:
        logger.warning("collegebaseball package not installed")
        return {"error": True, "message": "collegebaseball package not installed. Run: pip install git+https://github.com/nathanblumenfeld/collegebaseball"}
    
    _update_status("Loading schools from collegebaseball...", 10, source="python")
    
    try:
        # Robustly load schools from package CSV
        pkg_path = os.path.dirname(collegebaseball.__file__)
        schools_path = os.path.join(pkg_path, 'data', 'schools.csv')
        
        if not os.path.exists(schools_path):
             return {"error": True, "message": f"Schools data not found at {schools_path}"}
             
        schools_df = pd.read_csv(schools_path)
        
        # Filter by division
        if 'division' in schools_df.columns:
            div_schools = schools_df[schools_df['division'] == division]
        else:
            div_schools = schools_df
        
        if len(div_schools) == 0:
            return {"error": True, "message": f"No schools found for division {division}"}
        
        _update_status(f"Found {len(div_schools)} schools for D{division}", 15, source="python")
        
        # Save teams list
        teams_data = div_schools.to_dict(orient="records")
        teams_file = DATA_DIR / f"teams_d{division}.json"
        with open(teams_file, 'w') as f:
            json.dump(teams_data, f, indent=2)
        
        logger.info(f"Saved {len(teams_data)} teams to {teams_file}")
        
        # Create stats directories
        (DATA_DIR / "stats").mkdir(exist_ok=True)
        (DATA_DIR / "schedules").mkdir(exist_ok=True)
        
        # Import stats for teams (limit to first 50 to avoid rate limits)
        teams_to_import = div_schools.head(50)
        total = len(teams_to_import)
        imported_count = 0
        
        for idx, row in teams_to_import.iterrows():
            team_id = row.get('school_id')
            team_name = row.get('ncaa_name', row.get('bd_name', 'Unknown'))
            
            progress = int(20 + (idx / total * 70))
            _update_status(f"[{idx+1}/{total}] Importing {team_name}...", progress, source="python")
            
            try:
                # Fetch team stats (Batting) as a test
                stats_df = ncaa_scraper.ncaa_team_stats(team_id, year, variant='batting')
                if stats_df is not None and not stats_df.empty:
                    stats_file = DATA_DIR / "stats" / f"{team_id}_batting.csv"
                    stats_df.to_csv(stats_file, index=False)
                    imported_count += 1
                
                # Sleep briefly to avoid aggressive rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"Could not import stats for {team_name}: {e}")
        
        # Save summary
        summary = {
            "division": division,
            "year": year,
            "total_teams": len(div_schools),
            "imported_teams": imported_count,
            "source": "python-collegebaseball",
            "generated_at": datetime.now().isoformat()
        }
        
        summary_file = DATA_DIR / f"import_summary_d{division}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        _update_status("Import complete!", 100, source="python")
        return {"success": True, "source": "python", **summary}
        
    except Exception as e:
        logger.error(f"Python import failed: {e}")
        return {"error": True, "message": str(e)}


# ============================================================
# R Import (baseballr via subprocess)
# ============================================================

def _import_via_r(division: int, year: int, team_id: Optional[int] = None) -> Dict:
    """Run R import script and capture output."""
    import re
    
    _update_status("Starting R process...", 5, source="r")
    
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
                    _update_status(f"Importing {team_name}...", progress, source="r")
                elif "Fetching" in line:
                    _update_status(line.strip(), 10, source="r")
                elif "Success" in line:
                    _update_status("Import complete!", 100, source="r")
        
        stderr_output = process.stderr.read()
        if stderr_output:
            logger.warning(f"R Stderr: {stderr_output}")
            
        return_code = process.wait()
        
        if return_code != 0:
            error_msg = f"R script failed with code {return_code}"
            logger.error(f"{error_msg}\nStderr: {stderr_output}")
            _update_status(error_msg, 0, True, division, source="r")
            return {"error": True, "message": f"{error_msg}: {stderr_output}", "source": "r"}
        
        # Success - return summary
        _update_status("Import complete!", 100, source="r")
        summary = get_import_summary(division)
        if summary:
            return {"success": True, "source": "r", **summary}
        return {"success": True, "source": "r", "message": "Import completed"}
        
    except FileNotFoundError:
        error_msg = "Rscript not found. R may not be installed."
        logger.error(error_msg)
        _update_status(error_msg, 0, True, division, source="r")
        return {"error": True, "message": error_msg, "source": "r"}
    except Exception as e:
        logger.error(f"Exception running R script: {e}")
        _update_status(f"Error: {str(e)}", 0, True, division, source="r")
        return {"error": True, "message": str(e), "source": "r"}


# ============================================================
# Main Import Function (Hybrid)
# ============================================================

async def run_college_baseball_import(
    division: int = 1,
    year: Optional[int] = None,
    team_id: Optional[int] = None,
    source: Literal["auto", "python", "r", "both"] = "auto"
) -> Dict:
    """
    Run college baseball import using specified data source.
    
    Args:
        division: NCAA division (1, 2, or 3)
        year: Season year (defaults to current year)
        team_id: Optional specific team to import
        source: Data source preference
            - 'auto': Try Python first, fallback to R
            - 'python': Use collegebaseball package only
            - 'r': Use baseballr R script only
            - 'both': Run both sources and merge results
    
    Returns:
        dict with import results
    """
    if year is None:
        year = datetime.now().year
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting college baseball import: D{division}, {year}, source={source}")
    
    results = {"division": division, "year": year, "sources_tried": []}
    
    if source in ("auto", "python", "both"):
        # Try Python first
        logger.info("Attempting Python import via collegebaseball...")
        python_result = await asyncio.to_thread(_import_via_python, division, year)
        results["sources_tried"].append("python")
        
        if python_result.get("success"):
            results["python"] = python_result
            if source == "python":
                return {**results, "success": True, "primary_source": "python"}
        else:
            results["python_error"] = python_result.get("message")
            logger.warning(f"Python import failed: {python_result.get('message')}")
    
    if source in ("auto", "r", "both"):
        # Try R (or use as fallback)
        if source == "auto" and results.get("python", {}).get("success"):
            logger.info("Python succeeded, skipping R fallback")
        else:
            logger.info("Attempting R import via baseballr...")
            r_result = await asyncio.to_thread(_import_via_r, division, year, team_id)
            results["sources_tried"].append("r")
            
            if r_result.get("success"):
                results["r"] = r_result
            else:
                results["r_error"] = r_result.get("message")
                logger.warning(f"R import failed: {r_result.get('message')}")
    
    # Determine success
    if results.get("python", {}).get("success") or results.get("r", {}).get("success"):
        results["success"] = True
        results["primary_source"] = "python" if results.get("python", {}).get("success") else "r"
        # Add flat fields for easier dashboard consumption
        results["rows"] = (results.get("python", {}).get("imported_teams", 0) + 
                          results.get("r", {}).get("imported_teams", 0))
    else:
        results["success"] = False
        results["message"] = "All import sources failed"
        results["rows"] = 0
        _update_status("Import failed - no data sources available", 0, True, division)
    
    return results


# Alias for API compatibility
run_import = run_college_baseball_import


# LSU Tigers team ID for easy testing
LSU_TEAM_ID = 365


if __name__ == "__main__":
    async def test():
        # Test import D1 teams
        result = await run_college_baseball_import(division=1, year=2024, source="auto")
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
