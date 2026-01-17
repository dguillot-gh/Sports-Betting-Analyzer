"""
Model Testing Predictor - Full feature XGBoost predictions
Based on kyleskom/NBA-Machine-Learning-Sports-Betting methodology

Uses complete team stats and calculated rest days for accurate predictions.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import asyncio

logger = logging.getLogger(__name__)


# === Expected Value & Kelly Criterion (from reference repo) ===

def calculate_expected_value(win_prob: float, american_odds: int) -> float:
    """
    Calculate expected value for a bet.
    EV = (Pwin * payout) - (Ploss * stake)
    """
    if american_odds > 0:
        payout = american_odds
    else:
        payout = (100 / abs(american_odds)) * 100
    
    loss_prob = 1 - win_prob
    ev = (win_prob * payout) - (loss_prob * 100)
    return round(ev, 2)


def calculate_kelly_criterion(american_odds: int, model_prob: float) -> float:
    """
    Calculate recommended bankroll fraction using Kelly Criterion.
    """
    if american_odds >= 100:
        decimal_odds = american_odds / 100
    else:
        decimal_odds = 100 / abs(american_odds)
    
    bankroll_fraction = (100 * (decimal_odds * model_prob - (1 - model_prob))) / decimal_odds
    return round(max(0, bankroll_fraction), 2)


# === Team Stats Fetcher (from NBA Official API - like reference repo) ===

# Headers required to access NBA stats API (from reference repo)
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# NBA API URL for team stats (same as reference repo)
NBA_TEAM_STATS_URL = (
    "https://stats.nba.com/stats/leaguedashteamstats?"
    "Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&"
    "ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&"
    "OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&"
    "PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season={season}&"
    "SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&"
    "TeamID=0&TwoWay=0&VsConference=&VsDivision="
)


async def fetch_nba_team_stats_from_api() -> Dict[str, Dict]:
    """
    Fetch current season team stats directly from NBA's official API.
    This is the same approach used by the reference repo.
    Returns dict keyed by team name with ALL stats.
    """
    import aiohttp
    
    # Determine current season (e.g., "2025-26")
    now = datetime.now()
    if now.month >= 10:
        season = f"{now.year}-{str(now.year + 1)[2:]}"
    else:
        season = f"{now.year - 1}-{str(now.year)[2:]}"
    
    url = NBA_TEAM_STATS_URL.format(season=season)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=NBA_API_HEADERS, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"NBA API returned {response.status}")
                    return {}
                
                data = await response.json()
                
        # Parse the response (same structure as reference repo)
        result_sets = data.get('resultSets', [])
        if not result_sets:
            return {}
        
        team_data = result_sets[0]
        headers = team_data.get('headers', [])
        rows = team_data.get('rowSet', [])
        
        # Populate shared cache for kyleskom adapter
        try:
            from scripts.nba_cache import set_nba_df
            import pandas as pd
            df = pd.DataFrame(data=rows, columns=headers)
            set_nba_df(df)
        except Exception as e:
            logger.warning(f"Failed to populate shared NBA cache: {e}")

        # Convert to dict keyed by team name
        team_stats = {}
        for row in rows:
            row_dict = dict(zip(headers, row))
            team_name = row_dict.get('TEAM_NAME', '')
            
            # Map to our expected format
            team_stats[team_name] = {
                # Core stats
                'win_pct': row_dict.get('W_PCT', 0.5),
                'ppg': row_dict.get('PTS', 112),
                'oppg': row_dict.get('OPP_PTS', 112) if 'OPP_PTS' in row_dict else 112,
                
                # Shooting
                'fg_pct': row_dict.get('FG_PCT', 0.46),
                'fg3_pct': row_dict.get('FG3_PCT', 0.36),
                'ft_pct': row_dict.get('FT_PCT', 0.78),
                
                # Box score
                'reb': row_dict.get('REB', 44),
                'oreb': row_dict.get('OREB', 10),
                'dreb': row_dict.get('DREB', 34),
                'ast': row_dict.get('AST', 25),
                'tov': row_dict.get('TOV', 14),
                'stl': row_dict.get('STL', 7.5),
                'blk': row_dict.get('BLK', 5),
                'pf': row_dict.get('PF', 20),
                
                # Advanced
                'plus_minus': row_dict.get('PLUS_MINUS', 0),
                
                # Raw values for XGBoost (all columns from API)
                'W': row_dict.get('W', 0),
                'L': row_dict.get('L', 0),
                'GP': row_dict.get('GP', 0),
                'FGM': row_dict.get('FGM', 0),
                'FGA': row_dict.get('FGA', 0),
                'FG3M': row_dict.get('FG3M', 0),
                'FG3A': row_dict.get('FG3A', 0),
                'FTM': row_dict.get('FTM', 0),
                'FTA': row_dict.get('FTA', 0),
                
                # Rest days (will be calculated separately)
                'rest_days': 1,
            }
        
        logger.info(f"Fetched stats for {len(team_stats)} NBA teams from API")
        return team_stats
        
    except Exception as e:
        logger.error(f"Error fetching from NBA API: {e}")
        return {}


async def get_nba_team_stats() -> Dict[str, Dict]:
    """
    Get NBA team stats - tries NBA API first, falls back to local data.
    """
    # Try live API first
    stats = await fetch_nba_team_stats_from_api()
    
    if stats:
        return stats
    
    # Fallback to local predictor data
    logger.warning("NBA API unavailable, using local data")
    try:
        from scripts.nba_predictor import NBAPredictor
        predictor = NBAPredictor()
        
        team_stats = {}
        nba_teams = [
            "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
            "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
            "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
            "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
            "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
            "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
            "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors",
            "Utah Jazz", "Washington Wizards"
        ]
        
        for team in nba_teams:
            try:
                stats = await predictor.get_team_stats(team)
                team_stats[team] = stats if stats else _get_default_nba_stats()
            except:
                team_stats[team] = _get_default_nba_stats()
        
        return team_stats
    except Exception as e:
        logger.error(f"Error fetching NBA team stats: {e}")
        return {}


def _get_default_nba_stats() -> Dict:
    """Default NBA stats as fallback."""
    return {
        'ppg': 112.0,
        'oppg': 112.0,
        'win_pct': 0.5,
        'fg_pct': 0.46,
        'fg3_pct': 0.36,
        'ft_pct': 0.78,
        'reb': 44.0,
        'ast': 25.0,
        'tov': 14.0,
        'stl': 7.5,
        'blk': 5.0,
        'rest_days': 1
    }


async def fetch_nfl_team_stats_from_nflverse() -> Dict[str, Dict]:
    """
    Fetch comprehensive NFL team stats from nflverse using nflreadpy.
    Similar to how NBA page fetches from NBA API - gets all relevant team stats.
    """
    try:
        import numpy as np
        
        # Determine current/recent season
        now = datetime.now()
        current_year = now.year if now.month >= 9 else now.year - 1
        seasons = [current_year, current_year - 1]
        
        logger.info(f"Loading NFL team stats from nflverse for seasons {seasons}")
        
        # Load play-by-play data for EPA calculations
        # Try nflreadpy first (actively maintained)
        pbp = None
        try:
            import nflreadpy as nfl
            pbp_polars = nfl.load_pbp(seasons)
            pbp = pbp_polars.to_pandas()
            logger.info(f"Loaded {len(pbp)} plays from nflreadpy")
        except ImportError:
            import nfl_data_py as nfl
            pbp = nfl.import_pbp_data(seasons)
            logger.info(f"Loaded {len(pbp)} plays from nfl_data_py")
        except Exception as e:
            logger.warning(f"Could not load pbp data: {e}")
            return {}
        
        if pbp is None or len(pbp) == 0:
            return {}
        
        # Filter to most recent season
        pbp = pbp[pbp['season'] == current_year]
        
        # Calculate comprehensive team stats (like NBA API does)
        team_stats = {}
        teams = pbp['posteam'].dropna().unique()
        
        for team in teams:
            if not team or team == '':
                continue
                
            # Offensive stats (when team has ball)
            off_plays = pbp[pbp['posteam'] == team]
            off_pass = off_plays[off_plays['play_type'] == 'pass']
            off_run = off_plays[off_plays['play_type'] == 'run']
            
            # Defensive stats (when team is defending)
            def_plays = pbp[pbp['defteam'] == team]
            
            # Calculate all stats
            def safe_mean(series):
                val = series.mean()
                return round(float(val), 3) if not np.isnan(val) else 0.0
            
            def safe_sum(series):
                val = series.sum()
                return float(val) if not np.isnan(val) else 0.0
            
            # Core EPA stats
            off_epa = safe_mean(off_plays['epa'])
            def_epa = safe_mean(def_plays['epa'])
            pass_epa = safe_mean(off_pass['epa'])
            rush_epa = safe_mean(off_run['epa'])
            
            # Scoring stats
            games = len(off_plays['game_id'].unique())
            total_td = len(off_plays[off_plays['touchdown'] == 1])
            
            # Yardage stats
            total_yards = safe_sum(off_plays['yards_gained'])
            pass_yards = safe_sum(off_pass['yards_gained'])
            rush_yards = safe_sum(off_run['yards_gained'])
            
            # Success rates
            successful_plays = len(off_plays[off_plays['epa'] > 0])
            success_rate = round(successful_plays / len(off_plays), 3) if len(off_plays) > 0 else 0.5
            
            # Completion stats
            pass_attempts = len(off_pass)
            completions = len(off_pass[off_pass['complete_pass'] == 1])
            comp_pct = round(completions / pass_attempts, 3) if pass_attempts > 0 else 0.6
            
            # Calculate PPG and OPPG from game scores if available
            ppg = 22.5  # default
            oppg = 22.5  # default
            try:
                schedule = nfl.import_schedules([current_year])
                team_games = schedule[(schedule['home_team'] == team) | (schedule['away_team'] == team)]
                if len(team_games) > 0:
                    pts_for = []
                    pts_against = []
                    for _, g in team_games.iterrows():
                        if g['home_team'] == team:
                            if g.get('home_score'):
                                pts_for.append(g['home_score'])
                            if g.get('away_score'):
                                pts_against.append(g['away_score'])
                        else:
                            if g.get('away_score'):
                                pts_for.append(g['away_score'])
                            if g.get('home_score'):
                                pts_against.append(g['home_score'])
                    if pts_for:
                        ppg = round(np.mean(pts_for), 1)
                    if pts_against:
                        oppg = round(np.mean(pts_against), 1)
            except:
                pass
            
            # Calculate win percentage
            try:
                standings = nfl.import_team_desc()
                # Use schedule results for win pct
                team_results = schedule[(schedule['home_team'] == team) | (schedule['away_team'] == team)]
                wins = 0
                losses = 0
                for _, g in team_results.iterrows():
                    if g.get('home_score') is None:
                        continue
                    if g['home_team'] == team and g['home_score'] > g['away_score']:
                        wins += 1
                    elif g['away_team'] == team and g['away_score'] > g['home_score']:
                        wins += 1
                    elif g.get('home_score') != g.get('away_score'):
                        losses += 1
                win_pct = round(wins / (wins + losses), 3) if (wins + losses) > 0 else 0.5
            except:
                win_pct = 0.5
            
            # Build comprehensive stats dict (like NBA API returns)
            team_stats[team] = {
                # Core
                'ppg': ppg,
                'oppg': oppg,
                'win_pct': win_pct,
                'games_played': games,
                
                # EPA - the key NFL analytics
                'off_epa_per_play': off_epa,
                'def_epa_per_play': def_epa,
                'net_epa': round(off_epa - def_epa, 3),
                'pass_epa': pass_epa,
                'rush_epa': rush_epa,
                
                # Yardage
                'total_yards': total_yards,
                'yards_per_game': round(total_yards / games, 1) if games > 0 else 330,
                'pass_yards': pass_yards,
                'rush_yards': rush_yards,
                
                # Efficiency
                'success_rate': success_rate,
                'completion_pct': comp_pct,
                
                # Play counts
                'pass_attempts': pass_attempts,
                'completions': completions,
                
                # Rest days (will be calculated per game)
                'rest_days': 7,
            }
        
        logger.info(f"Loaded comprehensive stats for {len(team_stats)} NFL teams from nflverse")
        return team_stats
        
    except Exception as e:
        logger.error(f"Error fetching from nflverse: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


async def get_nfl_team_stats() -> Dict[str, Dict]:
    """
    Get NFL team stats - uses nflverse for comprehensive EPA + scoring data.
    """
    # Try nflverse first
    stats = await fetch_nfl_team_stats_from_nflverse()
    
    if stats:
        return stats
    
    # Fallback to NFLPredictor
    logger.warning("nflverse unavailable, using NFLPredictor fallback")
    try:
        from scripts.nfl_predictor import NFLPredictor
        predictor = NFLPredictor()
        
        team_stats = {}
        nfl_teams = [
            "Arizona Cardinals", "Atlanta Falcons", "Baltimore Ravens", "Buffalo Bills",
            "Carolina Panthers", "Chicago Bears", "Cincinnati Bengals", "Cleveland Browns",
            "Dallas Cowboys", "Denver Broncos", "Detroit Lions", "Green Bay Packers",
            "Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Kansas City Chiefs",
            "Las Vegas Raiders", "Los Angeles Chargers", "Los Angeles Rams", "Miami Dolphins",
            "Minnesota Vikings", "New England Patriots", "New Orleans Saints", "New York Giants",
            "New York Jets", "Philadelphia Eagles", "Pittsburgh Steelers", "San Francisco 49ers",
            "Seattle Seahawks", "Tampa Bay Buccaneers", "Tennessee Titans", "Washington Commanders"
        ]
        
        for team in nfl_teams:
            try:
                stats = predictor.get_team_stats(team)
                team_stats[team] = stats if stats else _get_default_nfl_stats()
            except:
                team_stats[team] = _get_default_nfl_stats()
        
        return team_stats
    except Exception as e:
        logger.error(f"Error fetching NFL team stats: {e}")
        return {}


def _get_default_nfl_stats() -> Dict:
    """Default NFL stats as fallback."""
    return {
        'ppg': 22.5,
        'oppg': 22.5,
        'win_pct': 0.5,
        'off_epa_per_play': 0.0,
        'def_epa_per_play': 0.0,
        'net_epa': 0.0,
        'pass_epa': 0.0,
        'rush_epa': 0.0,
        'success_rate': 0.5,
        'rest_days': 7
    }


# === XGBoost Prediction with Full Features ===

async def predict_nba_xgb_full(
    home_team: str, 
    away_team: str,
    home_stats: Dict,
    away_stats: Dict,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Make NBA XGBoost prediction with full feature set.
    """
    try:
        from scripts.nba_xgb_trainer import get_trainer
        trainer = get_trainer()
        
        if not trainer.model_ml:
            if not trainer.load_models():
                return {"error": "XGBoost model not trained. Please train first."}
        
        # Build feature vector with ALL team stats (matching reference repo)
        features = {
            # Home team stats
            'home_W_PCT': home_stats.get('win_pct', 0.5),
            'home_FG_PCT': home_stats.get('fg_pct', 0.46),
            'home_FG3_PCT': home_stats.get('fg3_pct', 0.36),
            'home_FT_PCT': home_stats.get('ft_pct', 0.78),
            'home_REB': home_stats.get('reb', 44),
            'home_AST': home_stats.get('ast', 25),
            'home_TOV': home_stats.get('tov', 14),
            'home_STL': home_stats.get('stl', 7.5),
            'home_BLK': home_stats.get('blk', 5),
            'home_PTS': home_stats.get('ppg', 112),
            
            # Away team stats
            'away_W_PCT': away_stats.get('win_pct', 0.5),
            'away_FG_PCT': away_stats.get('fg_pct', 0.46),
            'away_FG3_PCT': away_stats.get('fg3_pct', 0.36),
            'away_FT_PCT': away_stats.get('ft_pct', 0.78),
            'away_REB': away_stats.get('reb', 44),
            'away_AST': away_stats.get('ast', 25),
            'away_TOV': away_stats.get('tov', 14),
            'away_STL': away_stats.get('stl', 7.5),
            'away_BLK': away_stats.get('blk', 5),
            'away_PTS': away_stats.get('ppg', 112),
            
            # Rest days (calculated, not hardcoded!)
            'Days-Rest-Home': home_stats.get('rest_days', 1),
            'Days-Rest-Away': away_stats.get('rest_days', 1),
        }
        
        # Use trainer's predict method
        result = trainer.predict(features)
        
        if "error" in result:
            return result
        
        home_win_prob = result.get('home_win_probability', 0.5)
        away_win_prob = 1 - home_win_prob
        
        # Calculate EV and Kelly if odds provided
        ev_home = ev_away = None
        kelly_home = kelly_away = None
        
        if home_ml and away_ml:
            ev_home = calculate_expected_value(home_win_prob, home_ml)
            ev_away = calculate_expected_value(away_win_prob, away_ml)
            kelly_home = calculate_kelly_criterion(home_ml, home_win_prob)
            kelly_away = calculate_kelly_criterion(away_ml, away_win_prob)
        
        return {
            'model': 'xgboost',
            'home_team': home_team,
            'away_team': away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_winner': home_team if home_win_prob > 0.5 else away_team,
            'confidence': round(max(home_win_prob, away_win_prob) * 100, 1),
            'predicted_total': result.get('predicted_total'),
            'ev_home': ev_home,
            'ev_away': ev_away,
            'kelly_home': kelly_home,
            'kelly_away': kelly_away,
            'features_used': len(features),
            'rest_home': features['Days-Rest-Home'],
            'rest_away': features['Days-Rest-Away'],
        }
        
    except Exception as e:
        logger.error(f"XGBoost prediction error: {e}")
        return {"error": str(e)}


async def predict_nfl_xgb_full(
    home_team: str, 
    away_team: str,
    home_stats: Dict,
    away_stats: Dict,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Make NFL XGBoost prediction with full feature set.
    """
    try:
        from scripts.nfl_xgb_trainer import get_trainer
        trainer = get_trainer()
        
        if not trainer.model_ml:
            if not trainer.load_models():
                return {"error": "NFL XGBoost model not trained. Please train first."}
        
        # Build feature vector with NFL-specific stats (from nflverse)
        features = {
            # Scoring
            'home_ppg': home_stats.get('ppg', 22.5),
            'home_opp_ppg': home_stats.get('oppg', 22.5),
            'home_win_pct': home_stats.get('win_pct', 0.5),
            
            # EPA stats (the key NFL analytics from nflverse)
            'home_off_epa': home_stats.get('off_epa_per_play', 0.0),
            'home_def_epa': home_stats.get('def_epa_per_play', 0.0),
            'home_net_epa': home_stats.get('net_epa', 0.0),
            'home_pass_epa': home_stats.get('pass_epa', 0.0),
            'home_rush_epa': home_stats.get('rush_epa', 0.0),
            'home_success_rate': home_stats.get('success_rate', 0.5),
            
            # Away team
            'away_ppg': away_stats.get('ppg', 22.5),
            'away_opp_ppg': away_stats.get('oppg', 22.5),
            'away_win_pct': away_stats.get('win_pct', 0.5),
            
            # Away EPA stats
            'away_off_epa': away_stats.get('off_epa_per_play', 0.0),
            'away_def_epa': away_stats.get('def_epa_per_play', 0.0),
            'away_net_epa': away_stats.get('net_epa', 0.0),
            'away_pass_epa': away_stats.get('pass_epa', 0.0),
            'away_rush_epa': away_stats.get('rush_epa', 0.0),
            'away_success_rate': away_stats.get('success_rate', 0.5),
            
            # Rest days
            'rest_home': home_stats.get('rest_days', 7),
            'rest_away': away_stats.get('rest_days', 7),
        }
        
        result = trainer.predict(features)
        
        if "error" in result:
            return result
        
        home_win_prob = result.get('home_win_probability', 0.5)
        away_win_prob = 1 - home_win_prob
        
        ev_home = ev_away = None
        kelly_home = kelly_away = None
        
        if home_ml and away_ml:
            ev_home = calculate_expected_value(home_win_prob, home_ml)
            ev_away = calculate_expected_value(away_win_prob, away_ml)
            kelly_home = calculate_kelly_criterion(home_ml, home_win_prob)
            kelly_away = calculate_kelly_criterion(away_ml, away_win_prob)
        
        return {
            'model': 'xgboost',
            'home_team': home_team,
            'away_team': away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_winner': home_team if home_win_prob > 0.5 else away_team,
            'confidence': round(max(home_win_prob, away_win_prob) * 100, 1),
            'predicted_total': result.get('predicted_total'),
            'ev_home': ev_home,
            'ev_away': ev_away,
            'kelly_home': kelly_home,
            'kelly_away': kelly_away,
            'features_used': len(features),
        }
        
    except Exception as e:
        logger.error(f"NFL XGBoost prediction error: {e}")
        return {"error": str(e)}


# === Simple Model Predictions ===

async def predict_nba_simple(
    home_team: str,
    away_team: str,
    home_stats: Dict,
    away_stats: Dict,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Make NBA prediction using simple statistical model.
    Uses the passed stats (from NBA API) instead of database defaults.
    """
    try:
        import math
        
        # Use passed stats, with fallbacks to league averages
        home_ppg = home_stats.get('ppg', home_stats.get('PTS', 114.0))
        away_ppg = away_stats.get('ppg', away_stats.get('PTS', 114.0))
        home_oppg = home_stats.get('oppg', home_stats.get('OPP_PTS', 114.0))
        away_oppg = away_stats.get('oppg', away_stats.get('OPP_PTS', 114.0))
        home_win_pct = home_stats.get('win_pct', home_stats.get('W_PCT', 0.5))
        away_win_pct = away_stats.get('win_pct', away_stats.get('W_PCT', 0.5))
        
        # Ensure numeric values
        home_ppg = float(home_ppg) if home_ppg else 114.0
        away_ppg = float(away_ppg) if away_ppg else 114.0
        home_oppg = float(home_oppg) if home_oppg else 114.0
        away_oppg = float(away_oppg) if away_oppg else 114.0
        home_win_pct = float(home_win_pct) if home_win_pct else 0.5
        away_win_pct = float(away_win_pct) if away_win_pct else 0.5
        
        # Home court advantage (typically 2-3 points in NBA)
        home_advantage = 2.5
        
        # Calculate expected points
        home_expected = (home_ppg + away_oppg) / 2 + home_advantage / 2
        away_expected = (away_ppg + home_oppg) / 2 - home_advantage / 2
        
        # Predicted margin (positive = home win)
        predicted_margin = home_expected - away_expected
        
        # Factor in win percentage
        win_pct_diff = home_win_pct - away_win_pct
        adjusted_margin = predicted_margin + (win_pct_diff * 5)  # Win% adds up to ~5 pts
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        # Win probability using logistic function
        home_win_prob = 1 / (1 + math.exp(-adjusted_margin * 0.15))
        away_win_prob = 1 - home_win_prob
        
        # Build prediction result
        result = {
            'model': 'simple',
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if adjusted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_margin': round(adjusted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'confidence': round(max(home_win_prob, away_win_prob) * 100, 1),
        }
        
        # Add EV and Kelly if odds provided
        if home_ml and away_ml:
            result['ev_home'] = calculate_expected_value(home_win_prob, home_ml)
            result['ev_away'] = calculate_expected_value(away_win_prob, away_ml)
            result['kelly_home'] = calculate_kelly_criterion(home_ml, home_win_prob)
            result['kelly_away'] = calculate_kelly_criterion(away_ml, away_win_prob)
        
        return result
        
    except Exception as e:
        logger.error(f"Simple prediction error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e), "model": "simple"}


async def predict_nfl_simple(
    home_team: str,
    away_team: str,
    home_stats: Dict,
    away_stats: Dict,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Make NFL prediction using simple statistical model.
    Uses the passed stats (from nflverse) instead of database defaults.
    """
    try:
        import math
        
        # Use passed stats (from nflverse), with fallbacks
        home_ppg = float(home_stats.get('ppg', 22.5))
        away_ppg = float(away_stats.get('ppg', 22.5))
        home_oppg = float(home_stats.get('oppg', 22.5))
        away_oppg = float(away_stats.get('oppg', 22.5))
        home_win_pct = float(home_stats.get('win_pct', 0.5))
        away_win_pct = float(away_stats.get('win_pct', 0.5))
        
        # EPA stats (key NFL analytics)
        home_off_epa = float(home_stats.get('off_epa', home_stats.get('off_epa_per_play', 0.0)))
        away_off_epa = float(away_stats.get('off_epa', away_stats.get('off_epa_per_play', 0.0)))
        home_def_epa = float(home_stats.get('def_epa', home_stats.get('def_epa_per_play', 0.0)))
        away_def_epa = float(away_stats.get('def_epa', away_stats.get('def_epa_per_play', 0.0)))
        
        # Home field advantage in NFL (~2.5 points)
        home_advantage = 2.5
        
        # Calculate using EPA differential as primary metric
        home_net_epa = home_off_epa - home_def_epa
        away_net_epa = away_off_epa - away_def_epa
        epa_diff = home_net_epa - away_net_epa
        
        # Calculate expected points
        home_expected = (home_ppg + away_oppg) / 2 + home_advantage / 2
        away_expected = (away_ppg + home_oppg) / 2 - home_advantage / 2
        
        # Combine EPA and scoring for predicted margin
        predicted_margin = home_expected - away_expected
        
        # Adjust by EPA (each 0.1 EPA ~= 3 points)
        epa_adjustment = epa_diff * 30
        adjusted_margin = predicted_margin + epa_adjustment * 0.3 + (home_win_pct - away_win_pct) * 5
        
        # Win probability using logistic function
        home_win_prob = 1 / (1 + math.exp(-adjusted_margin * 0.12))
        away_win_prob = 1 - home_win_prob
        
        # Predicted total
        predicted_total = home_expected + away_expected
        
        result = {
            'model': 'simple',
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if adjusted_margin > 0 else away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_margin': round(adjusted_margin, 1),
            'predicted_total': round(predicted_total, 1),
            'confidence': round(max(home_win_prob, away_win_prob) * 100, 1),
        }
        
        # Add EV and Kelly if odds provided
        if home_ml and away_ml:
            result['ev_home'] = calculate_expected_value(home_win_prob, home_ml)
            result['ev_away'] = calculate_expected_value(away_win_prob, away_ml)
            result['kelly_home'] = calculate_kelly_criterion(home_ml, home_win_prob)
            result['kelly_away'] = calculate_kelly_criterion(away_ml, away_win_prob)
        
        return result
        
    except Exception as e:
        logger.error(f"NFL Simple prediction error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": str(e), "model": "simple"}

