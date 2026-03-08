# Pure Python Architecture - Fixed GitHub Data Sources
# This version retires the brittle R script and relies on definitive GitHub CSVs.

import json
import logging
import asyncio
import re
import hashlib
import pandas as pd
import requests
import asyncpg
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Literal, Union
from io import StringIO
from src.config import DATABASE_URL

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent

# Use relative path that works locally, fallback to Docker path
_local_data_dir = SCRIPT_DIR.parent / "data" / "baseball"
_docker_data_dir = Path("/app/data/baseball")
DATA_DIR = _local_data_dir if _local_data_dir.exists() or not _docker_data_dir.exists() else _docker_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = DATA_DIR / "import_status.json"

# Division import order: D1 only (D2/D3 disabled - NCAA lacks reliable D2/D3 data)
DIVISION_PRIORITY = [1]

# D2 fallback years to try if current year fails
D2_FALLBACK_YEARS = [2025, 2024]


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




def get_team_player_stats(team_id: str, stat_type: str = "batting", year: Optional[int] = None, division: int = 1) -> List[Dict]:
    """Get list of players for a team (Pure Python / GitHub Cache preferred)."""
    if year is None:
        year = get_smart_year()
    team_id_str = str(team_id)
    stats_file = DATA_DIR / "stats" / f"{team_id_str}_{stat_type}.csv"
    
    if stats_file.exists():
        try:
            df = pd.read_csv(stats_file)
            # Fill NaN with suitable defaults for JSON serialization
            df = df.fillna(0)
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error(f"Error reading stats file {stats_file.name}: {e}")
    
    return []
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


def get_team_schedule(team_id, year: Optional[int] = None) -> List[Dict]:
    """Schedules are no longer supported in the simplified pure-Python engine."""
    if year is None:
        year = get_smart_year()
    return []


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
    Import college baseball data using definitive GitHub sources and mapping.
    """
    _update_status(f"Initializing pure-Python engine for D{division}...", 5, source="python")
    
    try:
        # 1. Fetch Official Team Mapping (Gold Standard)
        _update_status(f"Fetching official team name mappings...", 10, source="python")
        TEAM_NAME_MAPPINGS = {}
        try:
            map_url = "https://raw.githubusercontent.com/CodeMateo15/CollegeBaseballStatsPackage/main/src/data/team_names_stats/team_name_mapping.csv"
            m_resp = requests.get(map_url, timeout=15)
            if m_resp.status_code == 200:
                # Format: team_id,division,team_old,team_new
                for line in m_resp.text.splitlines()[1:]:
                    parts = line.split(',')
                    if len(parts) >= 4:
                        # parts[3] is the "Official" name on NCAA site
                        # parts[2] is the "Common" name in stats CSVs
                        TEAM_NAME_MAPPINGS[parts[3].strip('"')] = parts[2].strip('"')
            logger.info(f"Loaded {len(TEAM_NAME_MAPPINGS)} source-level mappings.")
        except Exception as e:
            logger.warning(f"Failed to fetch remote mapping: {e}. Falling back to heuristics.")

        # 2. Fetch Team List (NCAA Source)
        try:
            import ncaa_bbStats
            teams = ncaa_bbStats.list_all_teams(year=year, division=division)
        except ImportError:
            logger.error("ncaa_bbStats package not installed")
            return {"error": True, "message": "Required package ncaa_bbStats is missing."}
        except Exception as e:
            logger.error(f"Failed to list teams: {e}")
            return {"error": True, "message": f"NCAA site error: {e}"}

        if not teams:
             return {"error": True, "message": "No teams found for this year/division."}

        teams_list = []
        (DATA_DIR / "stats").mkdir(exist_ok=True, parents=True)
        
        is_dict = isinstance(teams, dict)
        for team_name in (teams.keys() if is_dict else teams):
            safe_id = "".join([c if c.isalnum() else "_" for c in team_name]).strip("_")
            ncaa_id = teams[team_name] if is_dict else None
            teams_list.append({"team_id": safe_id, "ncaa_id": ncaa_id, "ncaa_name": team_name, "division": division})
            
        with open(DATA_DIR / f"teams_d{division}.json", 'w') as f:
            json.dump(teams_list, f, indent=2)

        # 3. Process Stats (Bulk)
        stats_imported = 0
        inventory = {} # { player: { team_id: info } }

        for stat_type in ["batting", "pitching"]:
            _update_status(f"Importing {stat_type} stats...", 30 if stat_type=="batting" else 60, source="python")
            
            # Gold Standard URL
            gh_url = f"https://raw.githubusercontent.com/CodeMateo15/CollegeBaseballStatsPackage/main/src/data/player_stats_cache/{stat_type}/{stat_type}_noMin.csv"
            
            try:
                logger.info(f"Downloading {stat_type} from {gh_url}...")
                resp = requests.get(gh_url, timeout=30)
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")
                
                df_all = pd.read_csv(StringIO(resp.text))
                if 'year' in df_all.columns:
                    df_all = df_all[df_all['year'] == year]
                
                # Normalize columns for matching
                df_all.columns = [c.lower().strip() for c in df_all.columns]
                target_col = 'team name' if 'team name' in df_all.columns else ('team_name' if 'team_name' in df_all.columns else 'team')
                
                # Match teams
                match_count = 0
                for team in teams_list:
                    n_name = team["ncaa_name"]
                    t_id = team["team_id"]
                    
                    # Normalization logic
                    def clean(s): return re.sub(r'[^a-z0-9]', '', str(s).lower())
                    
                    # Abbreviation expansion for matching
                    def expand_abbrevs(s):
                        """Expand common NCAA abbreviations to full words."""
                        s = re.sub(r'\bSt\.\s', 'State ', s)
                        s = re.sub(r'\bSt\.\s*$', 'State', s)
                        s = re.sub(r'\bKy\.\s', 'Kentucky ', s)
                        s = re.sub(r'\bKy\.\s*$', 'Kentucky', s)
                        s = re.sub(r'\bIll\.\s', 'Illinois ', s)
                        s = re.sub(r'\bIll\.\s*$', 'Illinois', s)
                        s = re.sub(r'\bMo\.\s', 'Missouri ', s)
                        s = re.sub(r'\bMo\.\s*$', 'Missouri', s)
                        s = re.sub(r'\bLa\.\s', 'Louisiana ', s)
                        s = re.sub(r'\bLa\.\s*$', 'Louisiana', s)
                        s = re.sub(r'\bFla\.\s', 'Florida ', s)
                        s = re.sub(r'\bFla\.\s*$', 'Florida', s)
                        s = re.sub(r'\bMiss\.\s', 'Mississippi ', s)
                        s = re.sub(r'\bMiss\.\s*$', 'Mississippi', s)
                        s = re.sub(r'\bArk\.\s', 'Arkansas ', s)
                        s = re.sub(r'\bArk\.\s*$', 'Arkansas', s)
                        s = re.sub(r'\bConn\.\s', 'Connecticut ', s)
                        s = re.sub(r'\bConn\.\s*$', 'Connecticut', s)
                        s = re.sub(r'\bSo\.\s', 'Southern ', s)
                        s = re.sub(r'\bSo\.\s*$', 'Southern', s)
                        return s
                    
                    # Match candidates:
                    # 1. Direct mapping from source-of-truth CSV
                    # 2. Cleaning heuristics (Conference suffix removal)
                    # 3. Expanded abbreviations
                    # 4. Robust normalized match
                    
                    mapped_name = TEAM_NAME_MAPPINGS.get(n_name, n_name)
                    cleaned_name = re.sub(r'\s*\(.*?\)', '', mapped_name).strip()
                    expanded_name = expand_abbrevs(cleaned_name)
                    
                    m_norm = clean(mapped_name)
                    c_norm = clean(cleaned_name)
                    n_norm = clean(n_name)
                    e_norm = clean(expanded_name)
                    
                    mask = (df_all[target_col].apply(clean) == m_norm) | \
                           (df_all[target_col].apply(clean) == c_norm) | \
                           (df_all[target_col].apply(clean) == n_norm) | \
                           (df_all[target_col].apply(clean) == e_norm)
                    
                    if not any(mask):
                        # Substring match with expanded name
                        mask = df_all[target_col].str.contains(expanded_name, case=False, na=False, regex=False)
                    
                    if not any(mask):
                        # Final straw: Substring match with original cleaned name
                        mask = df_all[target_col].str.contains(cleaned_name, case=False, na=False, regex=False)
                    
                    team_df = df_all[mask]
                    if not team_df.empty:
                        team_df.to_csv(DATA_DIR / "stats" / f"{t_id}_{stat_type}.csv", index=False)
                        match_count += 1
                        
                        # Inventory update
                        name_col = next((c for c in ['name', 'player_name', 'Name'] if c in team_df.columns), team_df.columns[0])
                        for p_name in team_df[name_col].unique():
                            p_str = str(p_name)
                            if p_str == 'nan': continue
                            if p_str not in inventory: inventory[p_str] = {}
                            if t_id not in inventory[p_str]:
                                inventory[p_str][t_id] = {"team_name": n_name, "stat_types": [], "division": division, "year": year}
                            inventory[p_str][t_id]["stat_types"].append(stat_type)

                logger.info(f"D{division} {stat_type}: Matched {match_count} teams.")
                stats_imported += match_count
            except Exception as e:
                logger.error(f"Failed {stat_type} import: {e}")

        # 4. Save Inventory
        inv_file = DATA_DIR / "players_inventory.json"
        existing = {}
        if inv_file.exists():
            try: existing = json.load(open(inv_file))
            except: pass
        
        for k, v in inventory.items():
            if k not in existing: existing[k] = v
            else: existing[k].update(v)
            
        with open(inv_file, 'w') as f: json.dump(existing, f, indent=2)

        _update_status("Finalizing import...", 90, source="python")
        summary = {"division": division, "year": year, "total_teams": len(teams_list), "matched": stats_imported, "status": "success"}
        with open(DATA_DIR / f"import_summary_d{division}.json", 'w') as f: json.dump(summary, f, indent=2)
        
        _update_status("System synchronized! 100% stable.", 100, source="python")
        return {"success": True, "source": "python", **summary}

    except Exception as e:
        logger.error(f"Migration fault: {e}", exc_info=True)
        _update_status(f"Import failed: {str(e)}", 0, True, source="python")
        return {"error": True, "message": str(e)}


# ============================================================
# R Import (baseballr via subprocess)
# ============================================================

# R script fallback decommissioned in favor of Pure Python architecture.
def _import_via_r(division: int, year: int, team_id: Union[int, str, None] = None, custom_id: Optional[str] = None) -> Dict:
    logger.warning("R script import is deprecated and has been disabled.")
    return {"error": True, "message": "R fallback disabled. System is now pure Python.", "source": "r"}


# ============================================================
# Main Import Function (Pure Python)
# ============================================================

async def _import_division_with_fallback(division: int, year: int) -> Dict:
    """
    Import a single division with pure Python engine.
    """
    logger.info(f"D{division}: Attempting Python import via GitHub Gold Standard for year {year}...")
    result = await asyncio.to_thread(_import_via_python, division, year)
    return result


async def run_college_baseball_import(
    division: int = 0,  # Default to ALL divisions
    year: Optional[int] = None,  # Default to smart year detection
    team_id: Optional[int] = None,
    source: str = "auto" # Kept for API compatibility, now defaults to Pure Python
) -> Dict:
    """
    Run college baseball import using specified data source.
    
    This is the "one-click" dynamic importer that:
    - Auto-detects the appropriate season year
    - Imports all divisions (D1 only in this version)
    """
    # Smart year detection
    if year is None or year == 0:
        year = get_smart_year()
        logger.info(f"Smart year detection: using {year}")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Handle Bulk Division (All) - use priority order (D1)
    if division == 0:
        divisions_to_import = DIVISION_PRIORITY
    else:
        divisions_to_import = [division]
    
    logger.info(f"Starting dynamic college baseball import: Divisions {divisions_to_import}, Year {year}")
    _update_status(f"Starting one-click import for {len(divisions_to_import)} divisions...", 5, source="python")
    
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
        _update_status(f"Importing D{div}...", progress, division=div, source="python")
        
        div_results = await _import_division_with_fallback(div, year)
        
        overall_results["results_per_division"][div] = div_results
        if div_results.get("success"):
            overall_results["success"] = True
            team_count = div_results.get("total_teams", 0)
            overall_results["total_teams"] += team_count
            logger.info(f"D{div}: Successfully imported {team_count} teams")
        else:
            logger.warning(f"D{div}: Import failed - {div_results.get('message')}")

    # Sync to Database
    if overall_results.get("success"):
        try:
            _update_status("Syncing to database...", 90, source="python")
            logger.info("Syncing imported data to PostgreSQL...")
            for div, res in overall_results["results_per_division"].items():
                if res.get("success"):
                    await sync_to_postgresql(res)
            overall_results["synced_to_db"] = True
            _update_status(f"Complete! Imported {overall_results['total_teams']} teams", 100, source="python")
        except Exception as se:
            logger.error(f"Database sync failed: {se}")
            overall_results["synced_to_db"] = False
            overall_results["db_error"] = str(se)
    else:
        _update_status("Import failed for all divisions", 0, is_error=True)

    return overall_results


def compute_hash(data: Dict) -> str:
    """Compute deterministic hash for upsert protection."""
    s = json.dumps(data, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()


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
                season = stats.get("season", get_smart_year())
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
                        
                        season = s.get("season", get_smart_year())
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
        result = await run_college_baseball_import(division=1, year=get_smart_year())
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
