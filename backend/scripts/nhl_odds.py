"""
NHL Live Odds Integration
Fetches live betting lines from sportsbooks using sbrscrape
"""

import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Supported sportsbooks
SPORTSBOOKS = [
    "fanduel",
    "draftkings", 
    "betmgm",
    "pointsbet",
    "caesars",
    "wynn",
    "bet_rivers_ny"
]

async def get_todays_nhl_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's NHL odds from the specified sportsbook.
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        logger.error("sbrscrape not installed. Run: pip install sbrscrape")
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        from datetime import timedelta
        # Use "Sports Date" (UTC - 6 hours) so late games count as "today"
        today = (datetime.utcnow() - timedelta(hours=6)).date()
        # sbrscrape uses the sport name as used by sbr (e.g., 'NHL')
        sb = Scoreboard(sport="NHL", date=today)
    except Exception as e:
        logger.error(f"Error initializing Scoreboard: {e}")
        return {"error": str(e), "games": []}
        
    if not hasattr(sb, "games") or not sb.games:
        return {
            "date": str(today),
            "sportsbook": sportsbook,
            "games": [],
            "message": "No games found for today"
        }
        
    try:
        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get('home_team', 'Unknown'),
                    "away_team": game.get('away_team', 'Unknown'),
                    "home_score": game.get('home_score'),
                    "away_score": game.get('away_score'),
                    "game_time": str(game.get('game_time', '')),
                    "status": game.get('status', 'scheduled'),
                }
                
                # Get odds for specified sportsbook
                if 'total' in game and sportsbook in game['total']:
                    game_data['over_under'] = game['total'][sportsbook]
                    
                if 'away_spread' in game and sportsbook in game['away_spread']:
                    game_data['spread'] = game['away_spread'][sportsbook]
                    
                if 'home_ml' in game and sportsbook in game['home_ml']:
                    game_data['home_moneyline'] = game['home_ml'][sportsbook]
                    
                if 'away_ml' in game and sportsbook in game['away_ml']:
                    game_data['away_moneyline'] = game['away_ml'][sportsbook]
                    
                games.append(game_data)
                
            except Exception as e:
                logger.warning(f"Error parsing game: {e}")
                continue
        
        return {
            "date": str(today),
            "sportsbook": sportsbook,
            "games": games,
            "count": len(games)
        }
        
    except Exception as e:
        logger.error(f"Error fetching NHL odds: {e}")
        return {
            "error": str(e),
            "games": [],
            "sportsbook": sportsbook
        }

def calculate_implied_probability(american_odds: int) -> float:
    """Convert American odds to implied probability percentage."""
    if american_odds > 0:
        return 100 / (american_odds + 100) * 100
    else:
        return abs(american_odds) / (abs(american_odds) + 100) * 100

def calculate_kelly_criterion(win_prob: float, odds: int, bankroll: float = 1000) -> float:
    """
    Calculate optimal bet size using Kelly Criterion.
    """
    if odds > 0:
        decimal_odds = (odds / 100) + 1
    else:
        decimal_odds = (100 / abs(odds)) + 1
    
    b = decimal_odds - 1
    q = 1 - win_prob
    
    if b == 0: return 0
    kelly_fraction = (b * win_prob - q) / b
    
    # Quarter Kelly is safer
    kelly_fraction = min(kelly_fraction * 0.25, 0.25)
    kelly_fraction = max(kelly_fraction, 0)
    
    return round(kelly_fraction * bankroll, 2)
