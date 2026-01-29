"""
College Football Data Importer
Uses sportsdataverse-py to fetch CFB data from CollegeFootballData.com API.
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Data directory setup
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "college_football"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Import config
from src.config import CFBD_API_KEY, DATABASE_URL


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
    if not CFBD_API_KEY:
        return {
            "success": False,
            "message": "CFBD_API_KEY not configured. Add it to your .env file."
        }
    
    # Set the API key for sportsdataverse
    os.environ["CFBD_API_KEY"] = CFBD_API_KEY
    
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
                teams_df = cfb.cfbd_team_info(year=year)
                
                if teams_df is not None and not teams_df.empty:
                    teams_list = teams_df.to_dict(orient="records")
                    
                    # Save to file
                    teams_file = DATA_DIR / f"teams_{year}.json"
                    with open(teams_file, 'w') as f:
                        json.dump(teams_list, f, indent=2, default=str)
                    
                    results["teams_imported"] = len(teams_list)
                    logger.info(f"Imported {len(teams_list)} teams")
                else:
                    logger.warning("No teams data returned")
                    
            except Exception as e:
                error_msg = f"Teams import error: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # === IMPORT GAMES/SCHEDULE ===
        if import_type in ["games", "all"]:
            logger.info(f"Importing CFB games for {year}...")
            try:
                games_df = cfb.cfbd_game_info(year=year)
                
                if games_df is not None and not games_df.empty:
                    games_list = games_df.to_dict(orient="records")
                    
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
                        json.dump(games_list, f, indent=2, default=str)
                    
                    results["games_imported"] = len(games_list)
                    logger.info(f"Imported {len(games_list)} games")
                else:
                    logger.warning("No games data returned")
                    
            except Exception as e:
                error_msg = f"Games import error: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # === IMPORT PLAYER STATS ===
        if import_type in ["stats", "all"]:
            logger.info(f"Importing CFB player stats for {year}...")
            try:
                # Get season stats
                stats_df = cfb.cfbd_player_season_stats(year=year)
                
                if stats_df is not None and not stats_df.empty:
                    stats_list = stats_df.to_dict(orient="records")
                    
                    # Save to file
                    stats_file = DATA_DIR / f"player_stats_{year}.json"
                    with open(stats_file, 'w') as f:
                        json.dump(stats_list, f, indent=2, default=str)
                    
                    results["players_imported"] = len(stats_list)
                    logger.info(f"Imported stats for {len(stats_list)} player records")
                else:
                    logger.warning("No player stats data returned")
                    
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
