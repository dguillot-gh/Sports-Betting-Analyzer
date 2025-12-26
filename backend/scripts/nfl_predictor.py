"""
NFL Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under
Simple statistical model (EPA-ready for future enhancement)
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import math

logger = logging.getLogger(__name__)

# NFL Team name mappings
NFL_TEAM_MAPPINGS = {
    # Abbreviations
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
    'LAR': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
    'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
    # Full names map to themselves
    'Arizona Cardinals': 'Arizona Cardinals', 'Atlanta Falcons': 'Atlanta Falcons',
    'Baltimore Ravens': 'Baltimore Ravens', 'Buffalo Bills': 'Buffalo Bills',
    'Carolina Panthers': 'Carolina Panthers', 'Chicago Bears': 'Chicago Bears',
    'Cincinnati Bengals': 'Cincinnati Bengals', 'Cleveland Browns': 'Cleveland Browns',
    'Dallas Cowboys': 'Dallas Cowboys', 'Denver Broncos': 'Denver Broncos',
    'Detroit Lions': 'Detroit Lions', 'Green Bay Packers': 'Green Bay Packers',
    'Houston Texans': 'Houston Texans', 'Indianapolis Colts': 'Indianapolis Colts',
    'Jacksonville Jaguars': 'Jacksonville Jaguars', 'Kansas City Chiefs': 'Kansas City Chiefs',
    'Las Vegas Raiders': 'Las Vegas Raiders', 'Los Angeles Chargers': 'Los Angeles Chargers',
    'Los Angeles Rams': 'Los Angeles Rams', 'Miami Dolphins': 'Miami Dolphins',
    'Minnesota Vikings': 'Minnesota Vikings', 'New England Patriots': 'New England Patriots',
    'New Orleans Saints': 'New Orleans Saints', 'New York Giants': 'New York Giants',
    'New York Jets': 'New York Jets', 'Philadelphia Eagles': 'Philadelphia Eagles',
    'Pittsburgh Steelers': 'Pittsburgh Steelers', 'San Francisco 49ers': 'San Francisco 49ers',
    'Seattle Seahawks': 'Seattle Seahawks', 'Tampa Bay Buccaneers': 'Tampa Bay Buccaneers',
    'Tennessee Titans': 'Tennessee Titans', 'Washington Commanders': 'Washington Commanders'
}


class NFLPredictor:
    """
    Simple NFL game predictor using team statistics.
    Uses points per game and home-field advantage.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
    
    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Get team statistics. Falls back to league averages if not available.
        """
        team = NFL_TEAM_MAPPINGS.get(team_name, team_name)
        
        if team in self._team_stats_cache:
            return self._team_stats_cache[team]
        
        # Default stats (2024 NFL averages as baseline)
        stats = {
            'ppg': 22.5,  # Points per game
            'oppg': 22.5,  # Opponent points per game
            'ypg': 330.0,  # Yards per game
            'opp_ypg': 330.0,  # Opponent yards per game
            'win_pct': 0.5,
            'home_win_pct': 0.55,
            'away_win_pct': 0.45,
        }
        
        self._team_stats_cache[team] = stats
        return stats
    
    def predict_game(self, home_team: str, away_team: str, 
                     spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics.
        """
        home_stats = self.get_team_stats(home_team)
        away_stats = self.get_team_stats(away_team)
        
        # Home field advantage (typically 2.5-3 points in NFL)
        home_advantage = 2.5
        
        # Calculate expected points
        home_expected = (home_stats['ppg'] + away_stats['oppg']) / 2 + home_advantage / 2
        away_expected = (away_stats['ppg'] + home_stats['oppg']) / 2 - home_advantage / 2
        
        # Predicted margin
        predicted_margin = home_expected - away_expected
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        # Win probability using logistic function
        home_win_prob = 1 / (1 + math.exp(-predicted_margin * 0.12))
        
        # Model confidence
        confidence = min(0.75, 0.5 + abs(predicted_margin) * 0.015)
        
        result = {
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if predicted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 3),
            'away_win_probability': round(1 - home_win_prob, 3),
            'predicted_margin': round(predicted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'home_expected_points': round(home_expected, 1),
            'away_expected_points': round(away_expected, 1),
            'confidence': round(confidence, 2),
            'confidence_level': 'high' if confidence >= 0.65 else 'medium' if confidence >= 0.55 else 'low'
        }
        
        # Compare to betting lines
        if spread is not None:
            line_margin = -spread
            model_edge = predicted_margin - line_margin
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if predicted_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 3.0  # 3+ point edge = value
            
        if over_under is not None:
            ou_edge = predicted_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if predicted_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 3.0
        
        return result


async def get_todays_nfl_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's NFL odds from the specified sportsbook.
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        logger.error("sbrscrape not installed")
        return {"error": "sbrscrape not installed", "games": []}
    
    try:
        from datetime import date
        today = date.today()
        sb = Scoreboard(sport="NFL", date=today)
        
        if not hasattr(sb, "games") or not sb.games:
            return {
                "date": str(today),
                "sportsbook": sportsbook,
                "games": [],
                "message": "No NFL games found for today"
            }
        
        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get('home_team', 'Unknown'),
                    "away_team": game.get('away_team', 'Unknown'),
                    "home_score": game.get('home_score'),
                    "away_score": game.get('away_score'),
                    "status": game.get('status', 'scheduled'),
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
                logger.warning(f"Error parsing NFL game: {e}")
        
        return {
            "date": str(today),
            "sportsbook": sportsbook,
            "games": games,
            "count": len(games)
        }
        
    except Exception as e:
        logger.error(f"Error fetching NFL odds: {e}")
        return {"error": str(e), "games": [], "sportsbook": sportsbook}


async def analyze_nfl_matchup(home_team: str, away_team: str, 
                              spread: float = None, over_under: float = None,
                              home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive NFL matchup analysis."""
    predictor = NFLPredictor()
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
    
    return prediction
