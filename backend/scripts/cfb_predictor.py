"""
College Football (CFB) Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under.
Supports The-Odds-API with quota tracking.
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import math
import numpy as np
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class CFBPredictor:
    """
    Simple CFB game predictor using team statistics.
    Uses points per game, home-field advantage, and EPA (if available).
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
        self.data_dir = Path(__file__).parent.parent / "data" / "college_football"
    
    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Get team statistics. Currently uses simple defaults or imported data if available.
        """
        if team_name in self._team_stats_cache:
            return self._team_stats_cache[team_name]
        
        # Try to load from imported JSON files (simplified lookup)
        # In a real implementation, we would load the JSON once and cache it.
        # For now, we'll return generous defaults/placeholders to ensure the odds page doesn't crash.
        
        stats = {
            'ppg': 30.0,
            'oppg': 30.0,
            'win_pct': 0.5,
            'off_epa': 0.0,
            'def_epa': 0.0,
            'net_epa': 0.0,
            'is_default': True
        }
        
        # TODO: Implement robust lookup from backend/data/college_football/teams_202X.json
        # and player_stats_202X.json if needed.
        
        self._team_stats_cache[team_name] = stats
        return stats
    
    def predict_game(self, home_team: str, away_team: str, 
                     spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics.
        """
        # Home field advantage (larger in CFB)
        home_advantage = 3.5
        
        # Retrieve stats (placeholders for now)
        home_stats = self.get_team_stats(home_team)
        away_stats = self.get_team_stats(away_team)
        
        # Calculate expected points (basic heuristics)
        # This is a PLACEHOLDER model until we train a real one or import deeper stats
        # Assuming equal strength if defaults, plus home field
        home_expected = 28.0 + (home_advantage / 2)
        away_expected = 28.0 - (home_advantage / 2)
        
        # Predicted margin
        predicted_margin = home_expected - away_expected
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        # Win probability using logistic function
        home_win_prob = 1 / (1 + math.exp(-predicted_margin * 0.15))
        
        # Model confidence
        confidence = min(0.85, 0.5 + abs(predicted_margin) * 0.01)
        
        result = {
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if predicted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 3),
            'away_win_probability': round(1 - home_win_prob, 3),
            'predicted_margin': round(predicted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'confidence': round(confidence, 2),
            'model_used': 'simple_heuristic'
        }
        
        # Compare to betting lines
        if spread is not None:
            line_margin = -spread
            model_edge = predicted_margin - line_margin
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if predicted_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 4.0  # Higher threshold for CFB volatility
            
        if over_under is not None:
            ou_edge = predicted_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if predicted_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 4.0
        
        return result


async def get_todays_cfb_odds(sportsbook: str = "draftkings") -> Dict[str, Any]:
    """
    Fetch today's CFB odds (americanfootball_ncaaf).
    Uses The Odds API with request quota tracking.
    """
    import os
    from datetime import date
    
    from datetime import timedelta
    # Use "Sports Date" (UTC - 6 hours) so late games count as "today"
    today = (datetime.utcnow() - timedelta(hours=6)).date()
    
    # Map sportsbook names to Odds API format
    SPORTSBOOK_MAP = {
        "fanduel": "fanduel",
        "draftkings": "draftkings",
        "betmgm": "betmgm",
        "pointsbet": "pointsbetus",
        "caesars": "williamhill_us",
    }
    
    # Try The Odds API
    from src.config import ODDS_API_KEY
    odds_api_key = ODDS_API_KEY
    
    if odds_api_key:
        try:
            import httpx
            
            book = SPORTSBOOK_MAP.get(sportsbook, "fanduel")
            # CFB Key: americanfootball_ncaaf
            url = f"https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
            params = {
                "apiKey": odds_api_key,
                "regions": "us",
                "markets": "h2h,totals",
                "bookmakers": book,
            }
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    games = []
                    for event in data:
                        try:
                            home_team = event.get("home_team", "")
                            away_team = event.get("away_team", "")
                            
                            game_data = {
                                "home_team": home_team,
                                "away_team": away_team,
                                "game_time": event.get("commence_time", ""),
                                "status": "scheduled",
                            }
                            
                            # Extract odds from bookmakers
                            for bookmaker in event.get("bookmakers", []):
                                if bookmaker.get("key") == book:
                                    for market in bookmaker.get("markets", []):
                                        if market.get("key") == "h2h":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == home_team:
                                                    game_data["home_moneyline"] = _decimal_to_american(outcome.get("price", 2.0))
                                                elif outcome.get("name") == away_team:
                                                    game_data["away_moneyline"] = _decimal_to_american(outcome.get("price", 2.0))
                                        elif market.get("key") == "totals":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == "Over":
                                                    game_data["over_under"] = outcome.get("point", 55.0)
                                                    break
                            
                            games.append(game_data)
                        except Exception as e:
                            logger.warning(f"Error parsing Odds API CFB game: {e}")
                    
                    if games or not games: # Always return structural data even if empty
                        logger.info(f"Loaded {len(games)} CFB games from The Odds API")
                        
                        # Extract API quota from headers
                        api_quota = {
                            "requests_remaining": int(response.headers.get("x-requests-remaining", 0)),
                            "requests_used": int(response.headers.get("x-requests-used", 0)),
                        }
                        
                        return {
                            "date": str(today),
                            "sportsbook": sportsbook,
                            "games": games,
                            "count": len(games),
                            "source": "the-odds-api",
                            "api_quota": api_quota
                        }
                else:
                    logger.warning(f"Odds API returned {response.status_code} for CFB")
                    return {
                         "error": f"The Odds API returned status {response.status_code}",
                         "details": response.text,
                         "games": []
                     }
        except Exception as e:
            logger.warning(f"The Odds API request failed: {e}")
                    
    # Fallback to sbrscrape
    try:
        from sbrscrape import Scoreboard
        sb = Scoreboard(sport="CFB", date=today)
        
        if hasattr(sb, "games") and sb.games:
            games = []
            for game in sb.games:
                try:
                    game_data = {
                        "home_team": game.get('home_team', 'Unknown'),
                        "away_team": game.get('away_team', 'Unknown'),
                        "game_time": str(game.get('game_time', '')),
                        "status": "scheduled",
                    }
                    
                    if 'total' in game and sportsbook in game.get('total', {}):
                        game_data['over_under'] = game['total'][sportsbook]
                    if 'away_spread' in game and sportsbook in game.get('away_spread', {}):
                        game_data['spread'] = game['away_spread'][sportsbook]
                    if 'home_ml' in game and sportsbook in game.get('home_ml', {}):
                        game_data['home_moneyline'] = game['home_ml'][sportsbook]
                    if 'away_ml' in game and sportsbook in game.get('away_ml', {}):
                        game_data['away_moneyline'] = game['away_ml'][sportsbook]
                        
                    games.append(game_data)
                except Exception as e:
                    logger.warning(f"Error parsing CFB game from sbrscrape: {e}")
            
            return {
                "date": str(today),
                "sportsbook": sportsbook,
                "games": games,
                "count": len(games),
                "source": "sbrscrape"
            }
    except Exception as e:
        logger.warning(f"sbrscrape fallback failed for CFB: {e}")

    return {
        "date": str(today),
        "sportsbook": sportsbook,
        "games": [],
        "message": "No CFB games found"
    }

def _decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))

async def analyze_cfb_matchup(home_team: str, away_team: str, 
                              spread: float = None, over_under: float = None,
                              home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive CFB matchup analysis."""
    predictor = CFBPredictor()
    prediction = predictor.predict_game(home_team, away_team, spread, over_under)
    
    # Add moneyline analysis if provided
    if home_ml and away_ml:
        def implied_prob(odds):
            if odds > 0:
                return 100 / (odds + 100)
            else:
                return abs(odds) / (abs(odds) + 100)
        
        home_implied = implied_prob(home_ml)
        away_implied = implied_prob(away_ml)
        
        prediction['home_moneyline'] = home_ml
        prediction['away_moneyline'] = away_ml
        prediction['home_implied_prob'] = round(home_implied, 3)
        prediction['away_implied_prob'] = round(away_implied, 3)
        
        home_edge = prediction['home_win_probability'] - home_implied
        prediction['home_ml_edge'] = round(home_edge * 100, 1)
        prediction['ml_pick'] = home_team if home_edge > 0 else away_team
        prediction['ml_value'] = abs(home_edge) >= 0.05
    
    # Value bets summary
    value_bets = []
    if prediction.get('ml_value'):
        value_bets.append(f"ML: {prediction['ml_pick']}")
    if prediction.get('spread_value'):
        value_bets.append(f"Spread: {prediction['spread_pick']}")
    if prediction.get('ou_value'):
        value_bets.append(f"Total: {prediction['ou_pick']}")
    
    prediction['value_bets'] = value_bets
    prediction['has_value'] = len(value_bets) > 0
    prediction['model'] = 'simple'
    
    return prediction

async def analyze_cfb_matchup_dual(home_team: str, away_team: str, 
                                   spread: float = None, over_under: float = None,
                                   home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """
    CFB matchup analysis with simple model (and placeholder for future ML).
    """
    # Get simple model prediction
    simple_pred = await analyze_cfb_matchup(home_team, away_team, spread, over_under, home_ml, away_ml)
    
    # Placeholder for XGB/ML model
    xgb_pred = {'model': 'xgboost', 'error': 'Not available yet'}
    
    # Return combined result
    return {
        'home_team': home_team,
        'away_team': away_team,
        'simple_model': simple_pred,
        'xgboost_model': xgb_pred,
        'home_moneyline': home_ml,
        'away_moneyline': away_ml,
        'spread': spread,
        'over_under': over_under,
        **simple_pred
    }
