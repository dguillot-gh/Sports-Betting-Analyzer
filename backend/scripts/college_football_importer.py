"""
College Football Data Importer
Uses sportsdataverse-py to fetch CFB data from CollegeFootballData.com API.
"""


import sys
from pathlib import Path
# Add backend root to path to allow imports if run as script
sys.path.append(str(Path(__file__).resolve().parents[1]))

import src.patch_xgboost  # Monkeypatch for legacy models BEFORE importing sportsdataverse
import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from datetime import datetime
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Data directory setup
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "college_football"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Import config
from src.config import COLLEGE_FOOTBALL_API_KEY, DATABASE_URL


def get_current_season() -> int:
    """Get the current CFB season year (August starts new season)."""
    now = datetime.now()
    if now.month >= 8:
        return now.year
    return now.year - 1


async def run_college_football_import(
    year: Optional[int] = None,
    conference: Optional[str] = None,
    import_type: str = "all"  # "teams", "games", "stats", "all"
) -> Dict[str, Any]:
    """
    Import college football data using sportsdataverse-py.
    
    Args:
        year: Season year (defaults to current season)
        conference: Filter by conference (e.g., "SEC", "Big Ten")
        import_type: What to import - "teams", "games", "stats", or "all"
    
    Returns:
        Dict with import results
    """
    if not COLLEGE_FOOTBALL_API_KEY:
        return {
            "success": False,
            "message": "COLLEGE_FOOTBALL_API_KEY not configured. Add it to your .env file."
        }
    
    # Set the API key for sportsdataverse
    os.environ["CFBD_API_KEY"] = COLLEGE_FOOTBALL_API_KEY
    
    year = year or get_current_season()
    results = {
        "success": True,
        "year": year,
        "conference": conference,
        "teams_imported": 0,
        "games_imported": 0,
        "players_imported": 0,
        "errors": []
    }
    
    try:
        # Try to import sportsdataverse
        try:
            import sportsdataverse.cfb as cfb
        except ImportError:
            return {
                "success": False,
                "message": "sportsdataverse package not installed. Run: pip install sportsdataverse[all]"
            }
        
        # === IMPORT TEAMS ===
        if import_type in ["teams", "all"]:
            logger.info(f"Importing CFB teams for {year}...")
            try:
                # POLYFILL: Try different API methods for teams
                teams_df = None
                if hasattr(cfb, "cfbd_team_info"):
                    teams_df = cfb.cfbd_team_info(year=year)
                elif hasattr(cfb, "get_teams"):
                    teams_df = cfb.get_teams(year=year)
                elif hasattr(cfb, "load_cfb_teams"):
                    teams_df = cfb.load_cfb_teams(year=year)
                elif hasattr(cfb, "load_cfb_rosters"): # Potential alternative
                    teams_df = cfb.load_cfb_rosters(seasons=[year])
                else:
                    logger.error(f"Could not find team import function. Available: {[x for x in dir(cfb) if 'team' in x or 'roster' in x]}")
                
                if teams_df is not None:
                    logger.info(f"Teams data type: {type(teams_df)}")
                    # Handle Polars or other DataFrame types
                    if hasattr(teams_df, "to_pandas"):
                        teams_df = teams_df.to_pandas()
                    
                    if not teams_df.empty:
                        # Sanitize NaN values for JSON
                        teams_df = teams_df.replace({np.nan: None})
                        teams_list = teams_df.to_dict(orient="records")
                        
                        # DATA MAPPING: Ensure we have teams, not rosters
                        if len(teams_list) > 0 and "athlete_id" in teams_list[0]:
                            logger.info("De-duplicating roster data to extract unique teams...")
                            seen_teams = set()
                            unique_teams = []
                            for row in teams_list:
                                t_name = row.get("team")
                                if t_name and t_name not in seen_teams:
                                    unique_teams.append({
                                        "school": t_name,
                                        "conference": row.get("conference"),
                                        "division": row.get("division"),
                                        "color": row.get("color"),
                                        "alt_color": row.get("alt_color")
                                    })
                                    seen_teams.add(t_name)
                            teams_list = unique_teams

                        # Post-process to ensure integers for IDs if they exist
                        for t in teams_list:
                            if "id" in t and t["id"] is not None:
                                try: t["id"] = int(float(t["id"]))
                                except: pass

                        # Save to file
                        teams_file = DATA_DIR / f"teams_{year}.json"
                        with open(teams_file, 'w') as f:
                            json.dump(teams_list, f, indent=2)
                        
                        results["teams_imported"] = len(teams_list)
                        logger.info(f"Imported {len(teams_list)} teams")
                    else:
                        logger.warning("Teams DataFrame is empty")
                else:
                    logger.warning("No teams data returned (None)")
                    
            except Exception as e:
                error_msg = f"Teams import error: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # === IMPORT GAMES/SCHEDULE ===
        if import_type in ["games", "all"]:
            logger.info(f"Importing CFB games for {year}...")
            try:
                # POLYFILL: Try different API methods for schedule
                games_df = None
                if hasattr(cfb, "cfbd_game_info"):
                     games_df = cfb.cfbd_game_info(year=year)
                elif hasattr(cfb, "get_schedule"):
                     games_df = cfb.get_schedule(year=year)
                elif hasattr(cfb, "load_cfb_schedule"):
                     # Fix: load_cfb_schedule likely takes 'seasons' list
                     try:
                        games_df = cfb.load_cfb_schedule(seasons=[year])
                     except TypeError:
                        games_df = cfb.load_cfb_schedule(year=year)
                else:
                     logger.error(f"Could not find schedule import function. Available: {[x for x in dir(cfb) if 'sched' in x or 'game' in x]}")

                if games_df is not None:
                    logger.info(f"Games data type: {type(games_df)}")
                    # Handle Polars or other DataFrame types
                    if hasattr(games_df, "to_pandas"):
                        games_df = games_df.to_pandas()

                    if not games_df.empty:
                        # Sanitize NaN values for JSON
                        games_df = games_df.replace({np.nan: None})
                        games_list = games_df.to_dict(orient="records")
                        
                        # Post-process list to ensure integers for scores (prevents 21.0)
                        for g in games_list:
                            for key in ["home_points", "away_points", "week", "season"]:
                                val = g.get(key)
                                if val is not None:
                                    try: g[key] = int(float(val))
                                    except: pass

                        # Filter by conference if specified
                        if conference:
                            games_list = [
                                g for g in games_list 
                                if g.get("home_conference") == conference 
                                or g.get("away_conference") == conference
                            ]
                        
                        # Save to file
                        games_file = DATA_DIR / f"games_{year}.json"
                        with open(games_file, 'w') as f:
                            json.dump(games_list, f, indent=2) # Remove default=str to catch issues early
                        
                        results["games_imported"] = len(games_list)
                        logger.info(f"Imported {len(games_list)} games")
                    else:
                        logger.warning("Games DataFrame is empty")
                else:
                    logger.warning("No games data returned (None)")
                    
            except Exception as e:
                error_msg = f"Games import error: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # === IMPORT PLAYER STATS ===
        if import_type in ["stats", "all"]:
            logger.info(f"Importing CFB player stats for {year}...")
            try:
                # Get season stats
                # POLYFILL for player stats
                stats_df = None
                if hasattr(cfb, "cfbd_player_season_stats"):
                     stats_df = cfb.cfbd_player_season_stats(year=year)
                elif hasattr(cfb, "get_player_stats"):
                     stats_df = cfb.get_player_stats(year=year)
                elif hasattr(cfb, "load_cfb_player_stats"):
                     stats_df = cfb.load_cfb_player_stats(year=year)
                elif hasattr(cfb, "load_cfb_rosters"):
                     # Fallback to rosters since player stats function is missing
                     logger.info("Using load_cfb_rosters as fallback for player stats")
                     stats_df = cfb.load_cfb_rosters(seasons=[year])
                else:
                     logger.warning("Could not find player stats import function.")

                if stats_df is not None:
                    logger.info(f"Player stats data type: {type(stats_df)}")
                    # Handle Polars or other DataFrame types
                    if hasattr(stats_df, "to_pandas"):
                        stats_df = stats_df.to_pandas()

                    if not stats_df.empty:
                        # Sanitize NaN values for JSON
                        stats_df = stats_df.replace({np.nan: None})
                        
                        # Optimization: Convert identifiable integer columns to prevent float JSON (e.g. 21.0)
                        for col in stats_df.columns:
                            if col in ['jersey', 'weight', 'height', 'year']:
                                try:
                                    # Fill None with 0 or keep as None? 
                                    # JSON serialization of NaN is the issue. 
                                    # If we want to keep it as null in JSON, we must keep it as None in dict.
                                    pass
                                except: pass

                        stats_list = stats_df.to_dict(orient="records")
                        
                        # DATA MAPPING: Check if this is roster data (fallback) and map to stats schema
                        if len(stats_list) > 0 and "first_name" in stats_list[0] and "player" not in stats_list[0]:
                            logger.info("Mapping roster data to player stats schema...")
                            mapped_list = []
                            for row in stats_list:
                                first = row.get("first_name", "")
                                last = row.get("last_name", "")
                                full_name = f"{first} {last}".strip()
                                
                                # Ensure jersey is integer if possible, then string
                                jersey_val = row.get("jersey")
                                if jersey_val is not None:
                                    try: jersey_val = int(float(jersey_val))
                                    except: pass
                                
                                mapped_list.append({
                                    "player": full_name,
                                    "team": row.get("team"),
                                    "position": row.get("position"),
                                    "category": "Roster",
                                    "stat_type": "Jersey",
                                    "stat": str(jersey_val) if jersey_val is not None else ""
                                })
                            stats_list = mapped_list

                        # Save to file
                        stats_file = DATA_DIR / f"player_stats_{year}.json"
                        with open(stats_file, 'w') as f:
                            json.dump(stats_list, f, indent=2) # Remove default=str to catch issues early
                        
                        results["players_imported"] = len(stats_list)
                        logger.info(f"Imported stats for {len(stats_list)} player records")
                    else:
                        logger.warning("Player stats DataFrame is empty")
                else:
                    logger.warning("No player stats data returned (None)")
                    
            except Exception as e:
                error_msg = f"Player stats import error: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # Mark success if we got any data
        total_imported = (
            results["teams_imported"] + 
            results["games_imported"] + 
            results["players_imported"]
        )
        
        if total_imported == 0 and results["errors"]:
            results["success"] = False
            results["message"] = "Import failed - see errors"
        else:
            results["message"] = f"Imported {total_imported} total records"
        
    except Exception as e:
        results["success"] = False
        results["message"] = f"Critical error: {e}"
        logger.error(f"CFB import failed: {e}")
    
    return results


async def get_cfb_teams(year: Optional[int] = None) -> List[Dict]:
    """Get list of CFB teams from cache or API."""
    year = year or get_current_season()
    teams_file = DATA_DIR / f"teams_{year}.json"
    
    if teams_file.exists():
        with open(teams_file, 'r') as f:
            return json.load(f)
    
    # Trigger import if cache doesn't exist
    result = await run_college_football_import(year=year, import_type="teams")
    
    if result["success"] and teams_file.exists():
        with open(teams_file, 'r') as f:
            return json.load(f)
    
    return []


async def get_cfb_games(year: Optional[int] = None, week: Optional[int] = None) -> List[Dict]:
    """Get CFB games from cache, optionally filtered by week."""
    year = year or get_current_season()
    games_file = DATA_DIR / f"games_{year}.json"
    
    if not games_file.exists():
        await run_college_football_import(year=year, import_type="games")
    
    if games_file.exists():
        with open(games_file, 'r') as f:
            games = json.load(f)
        
        if week is not None:
            games = [g for g in games if g.get("week") == week]
        
        return games
    
    return []


async def get_cfb_player_stats(year: Optional[int] = None, team: Optional[str] = None) -> List[Dict]:
    """Get CFB player stats from cache, optionally filtered by team."""
    year = year or get_current_season()
    stats_file = DATA_DIR / f"player_stats_{year}.json"
    
    if not stats_file.exists():
        await run_college_football_import(year=year, import_type="stats")
    
    if stats_file.exists():
        with open(stats_file, 'r') as f:
            stats = json.load(f)
        
        if team:
            stats = [s for s in stats if s.get("team") == team]
        
        return stats
    
    return []


# Main entry point for testing
if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("Testing College Football Import...")
        result = await run_college_football_import(year=2024, import_type="teams")
        print(f"Result: {result}")
    
    asyncio.run(main())
