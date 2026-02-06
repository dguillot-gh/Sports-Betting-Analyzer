import logging
import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.sport_factory import SportFactory
from src.database import fetch

logger = logging.getLogger(__name__)

# Team code normalization mapping from pramodkondur/NHL-Betting-Predictor
TEAM_NAME_MAPPING = {
    'S.J': 'SJS', 'N.J': 'NJD', 'T.B': 'TBL', 'L.A': 'LAK',
    'San Jose Sharks': 'SJS', 'New Jersey Devils': 'NJD', 
    'Tampa Bay Lightning': 'TBL', 'Los Angeles Kings': 'LAK',
    'Boston Bruins': 'BOS', 'Florida Panthers': 'FLA',
    'Chicago Blackhawks': 'CHI', 'Columbus Blue Jackets': 'CBJ',
    'Montreal Canadiens': 'MTL', 'Winnipeg Jets': 'WPG',
    'Arizona Coyotes': 'ARI', 'Anaheim Ducks': 'ANA',
    'Buffalo Sabres': 'BUF', 'Calgary Flames': 'CGY',
    'Carolina Hurricanes': 'CAR', 'Colorado Avalanche': 'COL',
    'Dallas Stars': 'DAL', 'Detroit Red Wings': 'DET',
    'Edmonton Oilers': 'EDM', 'Minnesota Wild': 'MIN',
    'Nashville Predators': 'NSH', 'New York Islanders': 'NYI',
    'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT',
    'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT',
    'Seattle Kraken': 'SEA', 'St. Louis Blues': 'STL',
    'Toronto Maple Leafs': 'TOR', 'Vancouver Canucks': 'VAN',
    'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH'
}

def normalize_team(name: str) -> str:
    """Normalize team name to code or standard naming."""
    return TEAM_NAME_MAPPING.get(name, name)

async def get_team_advanced_stats(team_name: str) -> Dict[str, Any]:
    """
    Fetch L10, Season-to-Date, and Rest statistics for a team.
    """
    try:
        norm_name = normalize_team(team_name)
        
        # Last 82 games (Season approx) vs Last 10
        query = """
            SELECT metadata 
            FROM results 
            WHERE series = 'nhl' 
            AND (metadata->>'team' = $1 OR metadata->>'name' = $1 OR metadata->>'team' = $2 OR metadata->>'name' = $2)
            ORDER BY season DESC, (metadata->>'gameDate')::int DESC
            LIMIT 82
        """
        rows = await fetch(query, team_name, norm_name)
        
        if not rows:
            return {}

        df = pd.DataFrame([json.loads(row['metadata']) for row in rows])
        
        # L10 Stats
        l10_df = df.head(10)
        l10_wins = sum(1 for _, r in l10_df.iterrows() if r.get('goalsFor', 0) > r.get('goalsAgainst', 0))
        
        # Season Stats
        season_wins = sum(1 for _, r in df.iterrows() if r.get('goalsFor', 0) > r.get('goalsAgainst', 0))
        
        # Rest Calculation (Quick lookup of last game date)
        # Assuming gameDate is YYYYMMDD string or similar
        rest_days = 3 # Default
        if len(rows) > 0:
            last_game_date_str = json.loads(rows[0]['metadata']).get('gameDate')
            if last_game_date_str:
                try:
                    last_date = datetime.strptime(str(last_game_date_str), "%Y%m%d")
                    today = datetime.now()
                    rest_days = (today - last_date).days
                except Exception:
                    pass

        return {
            "l10_record": f"{l10_wins}-{10-l10_wins}",
            "season_record": f"{season_wins}-{len(df)-season_wins}",
            "xgoals_for": df['xGoalsFor'].head(10).mean() if 'xGoalsFor' in df.columns else 0,
            "goals_for": df['goalsFor'].head(10).mean() if 'goalsFor' in df.columns else 0,
            "rest_days": rest_days,
            "is_b2b": rest_days <= 1
        }
    except Exception as e:
        logger.error(f"Error fetching advanced stats for {team_name}: {e}")
        return {}

async def analyze_nhl_matchup(
    home_team: str, 
    away_team: str, 
    spread: Optional[float] = None,
    over_under: Optional[float] = None,
    home_ml: Optional[int] = None,
    away_ml: Optional[int] = None
) -> Dict[str, Any]:
    """
    Analyze matchup using combined metrics from community research.
    """
    try:
        h_stats, a_stats = await asyncio.gather(
            get_team_advanced_stats(home_team),
            get_team_advanced_stats(away_team)
        )

        # Strength Modeling (from mostgood1 ideas: Elo/Strength blend)
        # We use a weighted score of L10 form + Season Performance + Rest
        def calculate_strength(stats):
            if not stats: return 1.0
            # Wins Ratio (0-1)
            win_record = stats.get('l10_record', '0-0').split('-')
            l10_ratio = int(win_record[0]) / 10 if int(win_record[0]) + int(win_record[1]) > 0 else 0.5
            
            # xG Strength (Normalized to ~3.0 league average)
            xg_strength = stats.get('xgoals_for', 0) / 3.0
            
            # Rest Penalty
            rest_mod = 0.95 if stats.get('is_b2b', False) else 1.0
            
            return (l10_ratio * 0.4 + xg_strength * 0.6) * rest_mod

        h_score = calculate_strength(h_stats) * 1.05 # Home Advantage
        a_score = calculate_strength(a_stats)
        
        h_prob = h_score / (h_score + a_score) if (h_score + a_score) > 0 else 0.53
        h_prob = min(max(h_prob, 0.1), 0.9)

        # Score Prediction logic (Simplified Poisson-like estimation)
        # League average is ~3.1 goals per team
        league_avg = 3.1
        h_pred_score = (h_stats.get('goals_for', league_avg) + h_stats.get('xgoals_for', league_avg)) / 2 * (1.05 if h_stats else 1)
        a_pred_score = (a_stats.get('goals_for', league_avg) + a_stats.get('xgoals_for', league_avg)) / 2
        
        # Adjust for opponent defense (Approximate)
        # In a full model, we'd use GA/xGA as well. For now, we'll blend the strengths.
        pred_total = h_pred_score + a_pred_score
        pred_spread = a_pred_score - h_pred_score # Home - Away (negative means home favored)

        prediction = {
            "home_team": home_team,
            "away_team": away_team,
            "simple_model": {
                "home_win_probability": round(h_prob, 3),
                "predicted_winner": home_team if h_prob > 0.5 else away_team,
                "confidence": "High" if abs(h_prob - 0.5) > 0.15 else "Medium",
                "predicted_total": round(pred_total, 2),
                "predicted_spread": round(pred_spread, 1),
                "predicted_home_score": round(h_pred_score, 2),
                "predicted_away_score": round(a_pred_score, 2)
            },
            "has_value": False,
            "home_stats": h_stats,
            "away_stats": a_stats
        }

        from scripts.nhl_odds import calculate_implied_probability, calculate_kelly_criterion
        
        # EV/Kelly Logic
        if home_ml:
            implied = calculate_implied_probability(home_ml) / 100
            prediction["simple_model"]["ev_home"] = (h_prob * (1/implied)) - 1
            prediction["simple_model"]["kelly_home"] = calculate_kelly_criterion(h_prob, home_ml)
            if prediction["simple_model"]["ev_home"] > 0.04: prediction["has_value"] = True

        if away_ml:
            a_prob = 1 - h_prob
            implied_a = calculate_implied_probability(away_ml) / 100
            prediction["simple_model"]["ev_away"] = (a_prob * (1/implied_a)) - 1
            prediction["simple_model"]["kelly_away"] = calculate_kelly_criterion(a_prob, away_ml)
            if prediction["simple_model"]["ev_away"] > 0.04: prediction["has_value"] = True

        return prediction

    except Exception as e:
        logger.error(f"Error in analyze_nhl_matchup: {e}")
        return {"error": str(e)}

async def analyze_matchup_dual(
    home_team: str, away_team: str, spread=None, over_under=None, home_ml=None, away_ml=None
) -> Dict[str, Any]:
    return await analyze_nhl_matchup(home_team, away_team, spread, over_under, home_ml, away_ml)
