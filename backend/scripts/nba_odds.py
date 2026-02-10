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
        from datetime import timedelta
        # Use "Sports Date" (UTC - 6 hours) so late games count as "today"
        # This prevents games from disappearing when UTC passes midnight (which is only 7 PM ET)
        today = (datetime.utcnow() - timedelta(hours=6)).date()
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
        
            except Exception as e:
                logger.warning(f"Error parsing game: {e}")
                continue
        
        # -------------------------------------------------------------------------
        # [EXPERIMENTAL] Add Experimental Neural Net predictions if model exists
        # This is purely additive and does not affect existing odds/data
        # -------------------------------------------------------------------------
        try:
            import os
            import asyncio
            from scripts.nba_ai_integration import get_all_predictions
            from scripts.kyleskom_adapter import get_kyleskom_predictor
            
            exp_model_path = "models/nba/experimental"
            # We look for ANY files in the experimental folder as a signal that the lab is "active"
            if os.path.exists(exp_model_path) and any(os.listdir(exp_model_path)):
                
                # Fetch stats (reusing kyleskom adapter's cache)
                kp = get_kyleskom_predictor()
                if await kp.fetch_data_from_nba_api():
                    stats_df = kp.df
                    
                    for game in games:
                        try:
                            # Map teams to stats
                            def get_stats_dict(name):
                                row = stats_df[stats_df['TEAM_NAME'] == name]
                                if row.empty:
                                    row = stats_df[stats_df['TEAM_NAME'].str.contains(name.split()[-1], case=False, na=False)]
                                if not row.empty:
                                    # Convert pandas Series to dict
                                    return row.iloc[0].to_dict()
                                return {}

                            h_stats = get_stats_dict(game['home_team'])
                            a_stats = get_stats_dict(game['away_team'])
                            
                            if h_stats and a_stats:
                                # Get all 5 engines (Baseline, Linear, Tree, MLP, Ensemble)
                                ai_result = get_all_predictions(
                                    game['home_team'], 
                                    game['away_team'], 
                                    h_stats, 
                                    a_stats
                                )
                                
                                # We specifically pick the MLP (Neural Network) for this experimental column
                                if "predictions" in ai_result and "MLP" in ai_result["predictions"]:
                                    pred = ai_result["predictions"]["MLP"]
                                    game['experimental_prediction'] = {
                                        "home_win_probability": pred.get("home_win_prob"),
                                        "predicted_total": pred.get("home_score", 0) + pred.get("away_score", 0)
                                    }
                        except Exception:
                            pass
                                
        except Exception as e:
            logger.error(f"Failed to attach experimental predictions: {e}")
            pass
            
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
    
    try:
        from datetime import timedelta
        # Use "Sports Date" (UTC - 6 hours) so late games count as "today"
        # This prevents games from disappearing when UTC passes midnight (which is only 7 PM ET)
        today = (datetime.utcnow() - timedelta(hours=6)).date()
        sb = Scoreboard(sport="NBA", date=today)
    except Exception as e:
        logger.error(f"Error initializing Scoreboard: {e}")
        return {"error": str(e), "games": []}
    
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
