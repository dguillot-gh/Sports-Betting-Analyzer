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
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Monkey-patch requests.Session to ensure User-Agent and robustness
_original_session_init = requests.Session.__init__

def patched_session_init(self, *args, **kwargs):
    _original_session_init(self, *args, **kwargs)
    self.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://stats.ncaa.org/',
    })
    # Add retry logic
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    self.mount('https://', HTTPAdapter(max_retries=retries))

requests.Session.__init__ = patched_session_init

import asyncpg
from src.config import DATABASE_URL

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
R_SCRIPT_PATH = SCRIPT_DIR / "college_baseball_importer.R"

# Use relative path that works locally, fallback to Docker path
_local_data_dir = SCRIPT_DIR.parent / "data" / "baseball"
_docker_data_dir = Path("/app/data/baseball")
DATA_DIR = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = DATA_DIR / "import_status.json"

# Division import order: D1 only (D2/D3 disabled - NCAA lacks reliable D2/D3 data)
DIVISION_PRIORITY = [1]

# D2 fallback years to try if current year fails
D2_FALLBACK_YEARS = [2024, 2023]


def get_smart_year() -> int:
    """
    Determine the appropriate season year based on college baseball calendar.
    
    College baseball season runs approximately Feb-June.
    - Before February: Use previous year (most recent completed season)
    - February onward: Use current year (season in progress or upcoming)
    """
    now = datetime.now()
    # If we're in January, the most recent completed season is last year
    if now.month < 2:
        return now.year - 1
    return now.year

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



def get_team_player_stats(team_id: str, stat_type: str = "batting", year: int = 2024) -> List[Dict]:
    """Get list of players for a team (Mocking roster from leaderboards for now)."""
    # For full parity, we'd read {team_id}_batting.csv
    # Currently we only have division-wide leaderboards in 'players/'
    # Filter players/ for matches on team
    players = []
    player_dir = DATA_DIR / "players"
    if player_dir.exists():
        for p_file in player_dir.glob("*.csv"):
            try:
                df = pd.read_csv(p_file)
                if not df.empty:
                    row = df.iloc[0].to_dict()
                    # Fuzzy match or exact match on team name?
                    # The leaderboards have 'team' column
                    if str(row.get('team', '')).lower() in str(team_id).lower():
                        players.append(row)
            except:
                continue
    return players
def get_team_stats(team_id: str, stat_type: str = "stats", entity_type: str = "team") -> Optional[Dict]:
    """Get team or player stats (merged batting/pitching/fielding)."""
    # Check stats/ for teams, players/ for players
    sub_dir = "players" if entity_type == "player" else "stats"
    stats_file = DATA_DIR / sub_dir / f"{team_id}_stats.csv"
    
    if not stats_file.exists():
        # Fallback to legacy naming OR check the other directory
        other_dir = "stats" if entity_type == "player" else "players"
        stats_file = DATA_DIR / other_dir / f"{team_id}_stats.csv"
        
    if not stats_file.exists():
        # Try legacy naming
        stats_file = DATA_DIR / sub_dir / f"{team_id}_{stat_type}.csv"
        
    if stats_file.exists():
        try:
            df = pd.read_csv(stats_file)
            return df.to_dict(orient="records")[0] if not df.empty else {}
        except Exception as e:
            logger.error(f"Error reading stats: {e}")
    return None


def get_team_schedule(team_id) -> Optional[List[Dict]]:
    """Get team schedule/results. team_id can be int or string."""
    # Convert to string for file lookup - handle both 'LSU__SEC' and numeric IDs
    team_id_str = str(team_id)
    schedule_file = DATA_DIR / "schedules" / f"{team_id_str}_schedule.csv"
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
    Import college baseball data using ncaa_bbStats package.
    """
    try:
        import ncaa_bbStats
    except ImportError:
        logger.warning("ncaa_bbStats package not installed")
        return {"error": True, "message": "ncaa_bbStats package not installed."}
    
    _update_status(f"Fetching D{division} stats from ncaa_bbStats...", 10, source="python")
    
    imported_count = 0
    
    try:
        # 1. Fetch Team List
        logger.info(f"Fetching Team List for D{division} {year}...")
        try:
            teams = ncaa_bbStats.list_all_teams(year=year, division=division)
        except Exception as e:
            logger.error(f"Failed to list teams for {year} D{division}: {e}")
            return {"error": True, "message": f"NCAA site error: {e}"}

        if not teams:
             return {"error": True, "message": "No teams found for this year/division."}

        teams_list = []
        (DATA_DIR / "stats").mkdir(exist_ok=True, parents=True)
        
        # Populate basic team profiles
        for team_name in teams:
            safe_id = "".join([c if c.isalnum() else "_" for c in team_name]).strip("_")
            teams_list.append({
                "team_id": safe_id,
                "ncaa_name": team_name,
                "division": division,
                "type": "team",
                "season": year
            })
            imported_count += 1
            
        # 2. Save Teams List (Entities list)
        teams_file = DATA_DIR / f"teams_d{division}.json"
        with open(teams_file, 'w') as f:
            json.dump(teams_list, f, indent=2)
            
        logger.info(f"Saved {len(teams_list)} teams")

        # 3. Save summary
        summary = {
            "division": division,
            "year": year,
            "total_teams": len(teams_list),
            "imported_teams": imported_count,
            "source": "python-ncaa_bbStats",
            "generated_at": datetime.now().isoformat()
        }
        
        summary_file = DATA_DIR / f"import_summary_d{division}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        _update_status(f"Imported {len(teams_list)} team names!", 50, source="python")
        return {"success": True, "source": "python", **summary}
        
    except Exception as e:
        logger.error(f"Python import failed: {e}", exc_info=True)
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

async def _import_division_with_fallback(
    division: int,
    year: int,
    team_id: Optional[int],
    source: str
) -> Dict:
    """
    Import a single division with fallback logic for D2.
    D2 often has NCAA restrictions, so we try fallback years.
    """
    years_to_try = [year]
    
    # For D2, add fallback years if the primary year fails
    if division == 2:
        for fallback_year in D2_FALLBACK_YEARS:
            if fallback_year not in years_to_try:
                years_to_try.append(fallback_year)
    
    div_results = {"division": division, "year": year, "sources_tried": [], "fallback_used": False}
    
    for try_year in years_to_try:
        if try_year != year:
            logger.info(f"D{division}: Trying fallback year {try_year}...")
            _update_status(f"D{division}: Trying fallback year {try_year}...", 30, division=division, source=source)
            div_results["fallback_used"] = True
            div_results["fallback_year"] = try_year
        
        # Try Python source first (ncaa-bbStats)
        if source in ("auto", "python", "both"):
            logger.info(f"D{division}: Attempting Python import via ncaa_bbStats for year {try_year}...")
            python_result = await asyncio.to_thread(_import_via_python, division, try_year)
            div_results["sources_tried"].append("python")
            
            if python_result.get("success"):
                div_results["python"] = python_result
                div_results["success"] = True
                div_results["year"] = try_year
                return div_results
            else:
                div_results["python_error"] = python_result.get("message")
        
        # Try R source (baseballr) as fallback
        if source in ("r", "both") or (source == "auto" and not div_results.get("success")):
            logger.info(f"D{division}: Attempting R import via baseballr for year {try_year}...")
            r_result = await asyncio.to_thread(_import_via_r, division, try_year, team_id)
            div_results["sources_tried"].append("r")
            
            if r_result.get("success"):
                div_results["r"] = r_result
                div_results["success"] = True
                div_results["year"] = try_year
                return div_results
            else:
                div_results["r_error"] = r_result.get("message")
    
    # All attempts failed
    div_results["success"] = False
    return div_results


async def run_college_baseball_import(
    division: int = 0,  # Default to ALL divisions
    year: Optional[int] = None,  # Default to smart year detection
    team_id: Optional[int] = None,
    source: Literal["auto", "python", "r", "both"] = "auto"
) -> Dict:
    """
    Run college baseball import using specified data source.
    
    This is the "one-click" dynamic importer that:
    - Auto-detects the appropriate season year
    - Imports all divisions (D1, D3, D2) in priority order
    - Falls back to previous years for D2 if current year fails
    
    Args:
        division: NCAA division (1, 2, or 3). Use 0 for ALL divisions (default).
        year: Season year. Use None or 0 for smart year detection (default).
        team_id: Optional specific team to import
        source: Data source preference: 'auto', 'python' (ncaa_bbStats), 'r' (baseballr), 'both'
    
    Reference packages:
        - Python: https://github.com/JohnJustinn/ncaa-bbStats
        - R: https://github.com/BillPetti/baseballr
    """
    # Smart year detection
    if year is None or year == 0:
        year = get_smart_year()
        logger.info(f"Smart year detection: using {year}")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Handle Bulk Division (All) - use priority order (D1, D3, D2)
    if division == 0:
        divisions_to_import = DIVISION_PRIORITY
    else:
        divisions_to_import = [division]
    
    logger.info(f"Starting dynamic college baseball import: Divisions {divisions_to_import}, Year {year}, Source {source}")
    _update_status(f"Starting one-click import for {len(divisions_to_import)} divisions...", 5, source=source)
    
    overall_results = {
        "success": False,
        "divisions": divisions_to_import,
        "year": year,
        "smart_year_used": True,
        "total_teams": 0,
        "results_per_division": {},
        "synced_to_db": False
    }

    for idx, div in enumerate(divisions_to_import):
        progress = 10 + int((idx / len(divisions_to_import)) * 70)
        _update_status(f"Importing D{div}...", progress, division=div, source=source)
        
        div_results = await _import_division_with_fallback(div, year, team_id, source)
        
        overall_results["results_per_division"][div] = div_results
        if div_results.get("success"):
            overall_results["success"] = True
            team_count = div_results.get("python", {}).get("total_teams", 0) or div_results.get("r", {}).get("total_teams", 0)
            overall_results["total_teams"] += team_count
            logger.info(f"D{div}: Successfully imported {team_count} teams")
        else:
            logger.warning(f"D{div}: Import failed - {div_results.get('python_error') or div_results.get('r_error')}")

    # Sync to Database
    if overall_results.get("success"):
        try:
            _update_status("Syncing to database...", 90, source=source)
            logger.info("Syncing imported data to PostgreSQL...")
            for div, res in overall_results["results_per_division"].items():
                if res.get("success"):
                    await sync_to_postgresql(res)
            overall_results["synced_to_db"] = True
            _update_status(f"Complete! Imported {overall_results['total_teams']} teams", 100, source=source)
        except Exception as se:
            logger.error(f"Database sync failed: {se}")
            overall_results["synced_to_db"] = False
            overall_results["db_error"] = str(se)
    else:
        _update_status("Import failed for all divisions", 0, is_error=True, source=source)

    return overall_results



def compute_hash(data: Dict) -> str:
    """Compute deterministic hash for upsert protection."""
    s = json.dumps(data, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()

import hashlib

async def sync_to_postgresql(import_results: Dict):
    """Sync file-based stats to PostgreSQL tables."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 1. Ensure sport exists
        sport_id = await conn.fetchval(
            "INSERT INTO sports (name, display_name) VALUES ('college_baseball', 'College Baseball') "
            "ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id"
        )
        
        # 2. Sync Teams
        division = import_results.get("division", 1)
        teams = get_teams(division)
        
        for t in teams:
            team_name = t.get("ncaa_name")
            team_id = t.get("team_id")
            
            # Entity row
            metadata = {"league": t.get("league"), "division": division}
            content_hash = compute_hash({"sport": "college_baseball", "team_id": team_id})
            
            entity_id = await conn.fetchval(
                """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                   VALUES ($1, $2, 'team', $3, $4, $5)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                   RETURNING id""",
                sport_id, team_name, f"D{division}", json.dumps(metadata), content_hash
            )
            
            # Stats row
            stats = get_team_stats(team_id, entity_type="team")
            if stats:
                season = stats.get("season", 2024)
                await conn.execute(
                    """INSERT INTO stats (entity_id, season, stat_type, stats)
                       VALUES ($1, $2, 'season_summary', $3)
                       ON CONFLICT (entity_id, season, stat_type)
                       DO UPDATE SET stats = EXCLUDED.stats""",
                    entity_id, season, json.dumps(stats)
                )

        # 3. Sync Players (from leaderboard/top N)
        # We look in the 'players' directory
        player_dir = DATA_DIR / "players"
        if player_dir.exists():
            for p_file in player_dir.glob("*_stats.csv"):
                try:
                    df = pd.read_csv(p_file)
                    if not df.empty:
                        s = df.iloc[0].to_dict()
                        p_name = s.get("player_name")
                        p_id = p_file.stem.replace("_stats", "")
                        
                        p_hash = compute_hash({"sport": "college_baseball", "player_id": p_id})
                        p_meta = {"team": s.get("team"), "league": s.get("league")}
                        
                        p_entity_id = await conn.fetchval(
                            """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                               VALUES ($1, $2, 'player', $3, $4, $5)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET metadata = EXCLUDED.metadata, series = EXCLUDED.series
                               RETURNING id""",
                            sport_id, p_name, s.get("team"), json.dumps(p_meta), p_hash
                        )
                        
                        season = s.get("season", 2024)
                        await conn.execute(
                            """INSERT INTO stats (entity_id, season, stat_type, stats)
                               VALUES ($1, $2, 'season_summary', $3)
                               ON CONFLICT (entity_id, season, stat_type)
                               DO UPDATE SET stats = EXCLUDED.stats""",
                            p_entity_id, season, json.dumps(s)
                        )
                except Exception as pe:
                    logger.debug(f"Error syncing player {p_file}: {pe}")

    finally:
        await conn.close()


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
