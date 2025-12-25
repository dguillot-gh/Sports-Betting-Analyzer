"""
NBA Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under
Inspired by: https://github.com/kyleskom/NBA-Machine-Learning-Sports-Betting
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import asyncio

logger = logging.getLogger(__name__)

# Team name mappings (sbrscrape uses abbreviations sometimes)
TEAM_MAPPINGS = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'Los Angeles Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards',
    # Full names map to themselves
    'Atlanta Hawks': 'Atlanta Hawks', 'Boston Celtics': 'Boston Celtics',
    'Brooklyn Nets': 'Brooklyn Nets', 'Charlotte Hornets': 'Charlotte Hornets',
    'Chicago Bulls': 'Chicago Bulls', 'Cleveland Cavaliers': 'Cleveland Cavaliers',
    'Dallas Mavericks': 'Dallas Mavericks', 'Denver Nuggets': 'Denver Nuggets',
    'Detroit Pistons': 'Detroit Pistons', 'Golden State Warriors': 'Golden State Warriors',
    'Houston Rockets': 'Houston Rockets', 'Indiana Pacers': 'Indiana Pacers',
    'Los Angeles Clippers': 'Los Angeles Clippers', 'LA Clippers': 'Los Angeles Clippers',
    'Los Angeles Lakers': 'Los Angeles Lakers', 'Memphis Grizzlies': 'Memphis Grizzlies',
    'Miami Heat': 'Miami Heat', 'Milwaukee Bucks': 'Milwaukee Bucks',
    'Minnesota Timberwolves': 'Minnesota Timberwolves', 'New Orleans Pelicans': 'New Orleans Pelicans',
    'New York Knicks': 'New York Knicks', 'Oklahoma City Thunder': 'Oklahoma City Thunder',
    'Orlando Magic': 'Orlando Magic', 'Philadelphia 76ers': 'Philadelphia 76ers',
    'Phoenix Suns': 'Phoenix Suns', 'Portland Trail Blazers': 'Portland Trail Blazers',
    'Sacramento Kings': 'Sacramento Kings', 'San Antonio Spurs': 'San Antonio Spurs',
    'Toronto Raptors': 'Toronto Raptors', 'Utah Jazz': 'Utah Jazz',
    'Washington Wizards': 'Washington Wizards'
}


class NBAPredictor:
    """
    Simple NBA game predictor using team statistics.
    Uses historical averages and recent form to predict outcomes.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
    
    async def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Get team statistics from database.
        Falls back to league averages if not available.
        """
        # Normalize team name
        team = TEAM_MAPPINGS.get(team_name, team_name)
        
        if team in self._team_stats_cache:
            return self._team_stats_cache[team]
        
        # Default stats (league averages as baseline)
        stats = {
            'ppg': 114.0,  # Points per game
            'oppg': 114.0,  # Opponent points per game
            'pace': 100.0,  # Possessions per game
            'off_rtg': 114.0,  # Offensive rating
            'def_rtg': 114.0,  # Defensive rating
            'net_rtg': 0.0,  # Net rating
            'win_pct': 0.5,  # Win percentage
            'home_win_pct': 0.55,  # Home win percentage
            'away_win_pct': 0.45,  # Away win percentage
            'last_5': 0.5,  # Last 5 games win %
            'sos': 0.0,  # Strength of schedule
        }
        
        # Try to fetch from database if available
        if self.db:
            try:
                row = await self.db.fetchrow("""
                    SELECT 
                        AVG(pts) as ppg,
                        AVG(reb) as rpg,
                        AVG(ast) as apg,
                        COUNT(CASE WHEN pts > opp_pts THEN 1 END)::float / NULLIF(COUNT(*), 0) as win_pct
                    FROM (
                        SELECT r.data->>'pts' as pts, r.data->>'reb' as reb, 
                               r.data->>'ast' as ast, r.data->>'opp_pts' as opp_pts
                        FROM results r
                        JOIN entities e ON r.entity_id = e.id
                        WHERE e.name ILIKE $1 AND r.series = 'nba_game_log'
                        ORDER BY r.game_date DESC
                        LIMIT 20
                    ) recent
                """, f"%{team}%")
                
                if row and row['ppg']:
                    stats['ppg'] = float(row['ppg'] or 114)
                    stats['win_pct'] = float(row['win_pct'] or 0.5)
            except Exception as e:
                logger.warning(f"Could not fetch stats for {team}: {e}")
        
        self._team_stats_cache[team] = stats
        return stats
    
    async def predict_game(self, home_team: str, away_team: str, 
                           spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics.
        
        Returns prediction with confidence levels.
        """
        home_stats = await self.get_team_stats(home_team)
        away_stats = await self.get_team_stats(away_team)
        
        # Home court advantage (typically 2-3 points in NBA)
        home_advantage = 2.5
        
        # Calculate expected points
        # Use average of team's offense vs opponent's defense
        home_expected = (home_stats['ppg'] + away_stats['oppg']) / 2 + home_advantage / 2
        away_expected = (away_stats['ppg'] + home_stats['oppg']) / 2 - home_advantage / 2
        
        # Predicted margin (positive = home win)
        predicted_margin = home_expected - away_expected
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        # Win probability using logistic function
        # Steepness factor: each point of predicted margin = ~4% win probability shift
        import math
        home_win_prob = 1 / (1 + math.exp(-predicted_margin * 0.15))
        
        # Model confidence based on sample size and stat reliability
        confidence = min(0.75, 0.5 + abs(predicted_margin) * 0.02)
        
        # Build prediction result
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
        
        # Compare to betting lines if provided
        if spread is not None:
            # Spread is typically expressed as away team spread
            # Negative = away favored, positive = home favored
            line_margin = -spread  # Convert to home perspective
            model_edge = predicted_margin - line_margin
            
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if predicted_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 2.0  # 2+ point edge = value
            
        if over_under is not None:
            ou_edge = predicted_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if predicted_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 3.0  # 3+ point edge = value
        
        return result
    
    async def predict_games(self, games: List[Dict]) -> List[Dict]:
        """
        Predict outcomes for multiple games.
        """
        predictions = []
        for game in games:
            try:
                pred = await self.predict_game(
                    home_team=game.get('home_team', ''),
                    away_team=game.get('away_team', ''),
                    spread=game.get('spread'),
                    over_under=game.get('over_under')
                )
                predictions.append(pred)
            except Exception as e:
                logger.error(f"Error predicting game {game}: {e}")
                predictions.append({
                    'home_team': game.get('home_team'),
                    'away_team': game.get('away_team'),
                    'error': str(e)
                })
        
        return predictions


async def analyze_matchup(home_team: str, away_team: str, 
                          spread: float = None, over_under: float = None,
                          home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """
    Comprehensive matchup analysis.
    """
    predictor = NBAPredictor()
    prediction = await predictor.predict_game(home_team, away_team, spread, over_under)
    
    # Add moneyline analysis if provided
    if home_ml and away_ml:
        # Calculate implied probabilities from odds
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
        
        # Model edge vs market
        home_edge = prediction['home_win_probability'] - home_implied
        prediction['home_ml_edge'] = round(home_edge * 100, 1)  # As percentage
        prediction['ml_pick'] = home_team if home_edge > 0 else away_team
        prediction['ml_value'] = abs(home_edge) >= 0.05  # 5%+ edge = value
        
        # Expected Value calculation
        if home_edge > 0:
            if home_ml > 0:
                ev = (home_ml / 100) * prediction['home_win_probability'] - (1 - prediction['home_win_probability'])
            else:
                ev = (100 / abs(home_ml)) * prediction['home_win_probability'] - (1 - prediction['home_win_probability'])
            prediction['home_ev'] = round(ev * 100, 1)
        else:
            if away_ml > 0:
                ev = (away_ml / 100) * prediction['away_win_probability'] - (1 - prediction['away_win_probability'])
            else:
                ev = (100 / abs(away_ml)) * prediction['away_win_probability'] - (1 - prediction['away_win_probability'])
            prediction['away_ev'] = round(ev * 100, 1)
    
    # Summary recommendation
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
