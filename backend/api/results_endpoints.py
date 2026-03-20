"""
Results API Endpoints
Fetches completed game results for result syncing
"""

from fastapi import APIRouter, Request, Query
from datetime import date
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/nba/today")
async def get_nba_results_today(request: Request):
    """
    Get today's NBA game results (final scores).
    Uses sbrscrape to get live/completed game data.
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        logger.error("sbrscrape not installed")
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        today = date.today()
        sb = Scoreboard(sport="NBA", date=today)
        
        if not hasattr(sb, "games") or not sb.games:
            return {"date": str(today), "games": [], "message": "No games found"}
        
        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get('home_team', 'Unknown'),
                    "away_team": game.get('away_team', 'Unknown'),
                    "home_score": game.get('home_score'),
                    "away_score": game.get('away_score'),
                    "status": game.get('status', 'scheduled'),
                    "game_time": str(game.get('game_time', '')),
                }
                games.append(game_data)
            except Exception as e:
                logger.warning(f"Error parsing game: {e}")
        
        completed = [g for g in games if g.get('status', '').lower() == 'final']
        
        return {
            "date": str(today),
            "games": games,
            "completed_count": len(completed),
            "total_count": len(games)
        }
    except Exception as e:
        logger.error(f"Error fetching NBA results: {e}")
        return {"error": str(e), "games": []}


@router.get("/nfl/today")
async def get_nfl_results_today(request: Request):
    """
    Get today's NFL game results (final scores).
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        today = date.today()
        sb = Scoreboard(sport="NFL", date=today)
        
        if not hasattr(sb, "games") or not sb.games:
            return {"date": str(today), "games": [], "message": "No games found"}
        
        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get('home_team', 'Unknown'),
                    "away_team": game.get('away_team', 'Unknown'),
                    "home_score": game.get('home_score'),
                    "away_score": game.get('away_score'),
                    "status": game.get('status', 'scheduled'),
                    "game_time": str(game.get('game_time', '')),
                }
                games.append(game_data)
            except Exception as e:
                logger.warning(f"Error parsing game: {e}")
        
        return {
            "date": str(today),
            "games": games,
            "completed_count": len([g for g in games if g.get('status', '').lower() == 'final'])
        }
    except Exception as e:
        logger.error(f"Error fetching NFL results: {e}")
        return {"error": str(e), "games": []}
@router.get("/nhl/today")
async def get_nhl_results_today(request: Request):
    """
    Get today's NHL game results (final scores).
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        today = date.today()
        sb = Scoreboard(sport="NHL", date=today)
        
        if not hasattr(sb, "games") or not sb.games:
            return {"date": str(today), "games": [], "message": "No games found"}
        
        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get('home_team', 'Unknown'),
                    "away_team": game.get('away_team', 'Unknown'),
                    "home_score": game.get('home_score'),
                    "away_score": game.get('away_score'),
                    "status": game.get('status', 'scheduled'),
                    "game_time": str(game.get('game_time', '')),
                }
                games.append(game_data)
            except Exception as e:
                logger.warning(f"Error parsing game: {e}")
        
        return {
            "date": str(today),
            "games": games,
            "completed_count": len([g for g in games if g.get('status', '').lower() == 'final'])
        }
    except Exception as e:
        logger.error(f"Error fetching NHL results: {e}")
        return {"error": str(e), "games": []}
