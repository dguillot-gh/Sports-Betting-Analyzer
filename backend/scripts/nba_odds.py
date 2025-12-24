"""
NBA Live Odds Integration
Fetches live betting lines from sportsbooks using sbrscrape
Adapted from: https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting
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


async def get_todays_nba_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's NBA odds from the specified sportsbook.
    
    Args:
        sportsbook: One of fanduel, draftkings, betmgm, etc.
        
    Returns:
        Dictionary with games and their betting lines
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        logger.error("sbrscrape not installed. Run: pip install sbrscrape")
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        today = date.today()
        sb = Scoreboard(sport="NBA", date=today)
        
        if not hasattr(sb, "games") or not sb.games:
            return {
                "date": str(today),
                "sportsbook": sportsbook,
                "games": [],
                "message": "No games found for today"
            }
        
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
        logger.error(f"Error fetching NBA odds: {e}")
        return {
            "error": str(e),
            "games": [],
            "sportsbook": sportsbook
        }


async def get_all_sportsbook_odds() -> Dict[str, Any]:
    """
    Fetch odds from all available sportsbooks for comparison.
    
    Returns:
        Dictionary with odds from each sportsbook
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        return {"error": "sbrscrape not installed"}
    
    today = date.today()
    sb = Scoreboard(sport="NBA", date=today)
    
    if not hasattr(sb, "games") or not sb.games:
        return {"date": str(today), "games": []}
    
    games = []
    for game in sb.games:
        try:
            game_data = {
                "home_team": game.get('home_team'),
                "away_team": game.get('away_team'),
                "odds_by_book": {}
            }
            
            for book in SPORTSBOOKS:
                book_odds = {}
                if 'total' in game and book in game.get('total', {}):
                    book_odds['over_under'] = game['total'][book]
                if 'away_spread' in game and book in game.get('away_spread', {}):
                    book_odds['spread'] = game['away_spread'][book]
                if 'home_ml' in game and book in game.get('home_ml', {}):
                    book_odds['home_ml'] = game['home_ml'][book]
                if 'away_ml' in game and book in game.get('away_ml', {}):
                    book_odds['away_ml'] = game['away_ml'][book]
                    
                if book_odds:
                    game_data['odds_by_book'][book] = book_odds
                    
            games.append(game_data)
            
        except Exception as e:
            logger.warning(f"Error parsing game for multi-book: {e}")
            
    return {
        "date": str(today),
        "games": games,
        "sportsbooks": SPORTSBOOKS
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
    
    Args:
        win_prob: Model's predicted win probability (0-1)
        odds: American odds
        bankroll: Total bankroll
        
    Returns:
        Recommended bet amount
    """
    if odds > 0:
        decimal_odds = (odds / 100) + 1
    else:
        decimal_odds = (100 / abs(odds)) + 1
    
    # Kelly formula: f = (bp - q) / b
    # where b = decimal odds - 1, p = win prob, q = 1 - p
    b = decimal_odds - 1
    q = 1 - win_prob
    
    kelly_fraction = (b * win_prob - q) / b
    
    # Never bet more than 25% (quarter Kelly is safer)
    kelly_fraction = min(kelly_fraction * 0.25, 0.25)
    kelly_fraction = max(kelly_fraction, 0)  # No negative bets
    
    return round(kelly_fraction * bankroll, 2)
