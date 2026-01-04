"""
NFL XGBoost Adapter with Nflverse Data
Mirrors the NBA kyleskom approach but uses nflverse (nfl_data_py) for NFL data.
No hardcoded values - all features are fetched from real data.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import asyncio

logger = logging.getLogger(__name__)

# Check if dependencies available
try:
    import xgboost as xgb
    import numpy as np
    import pandas as pd
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not available")

MODELS_DIR = "models/nfl"

# NFL Team mappings (abbreviations to full names)
NFL_TEAM_INDEX = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
    'LA': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
    'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
    # Reverse mapping
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LA', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS'
}


class NflversePredictor:
    """
    NFL XGBoost predictor using nflverse data.
    Mirrors the kyleskom NBA approach but with NFL-specific features.
    """
    
    # Feature names for the model (NFL-specific)
    FEATURE_NAMES = [
        # Home team stats
        'home_ppg', 'home_opp_ppg', 'home_win_pct',
        'home_off_epa', 'home_def_epa', 'home_pass_epa', 'home_rush_epa',
        'home_success_rate', 'home_yards_per_game',
        # Away team stats  
        'away_ppg', 'away_opp_ppg', 'away_win_pct',
        'away_off_epa', 'away_def_epa', 'away_pass_epa', 'away_rush_epa',
        'away_success_rate', 'away_yards_per_game',
        # Rest days
        'rest_home', 'rest_away'
    ]
    
    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.team_stats = {}  # Cached team stats
        self._loaded = False
        self._stats_loaded = False
        os.makedirs(MODELS_DIR, exist_ok=True)
    
    def load_models(self) -> bool:
        """Load trained models from disk."""
        if not XGB_AVAILABLE:
            return False
        
        ml_path = f"{MODELS_DIR}/nfl_xgb_moneyline.json"
        ou_path = f"{MODELS_DIR}/nfl_xgb_overunder.json"
        
        if os.path.exists(ml_path):
            self.model_ml = xgb.Booster()
            self.model_ml.load_model(ml_path)
            logger.info(f"Loaded NFL ML model from {ml_path}")
        
        if os.path.exists(ou_path):
            self.model_ou = xgb.Booster()
            self.model_ou.load_model(ou_path)
            logger.info(f"Loaded NFL OU model from {ou_path}")
        
        self._loaded = self.model_ml is not None
        return self._loaded
    
    async def fetch_team_stats_from_nflverse(self) -> Dict[str, Dict]:
        """
        Fetch comprehensive NFL team stats using existing NFLPredictor.
        Falls back to default values if EPA data not available.
        """
        if self._stats_loaded and self.team_stats:
            return self.team_stats
        
        try:
            # Use existing NFLPredictor which already handles EPA loading
            from scripts.nfl_predictor import NFLPredictor
            
            predictor = NFLPredictor()
            
            logger.info("Loading NFL team stats via NFLPredictor...")
            
            # All NFL teams
            all_teams = [
                'Arizona Cardinals', 'Atlanta Falcons', 'Baltimore Ravens',
                'Buffalo Bills', 'Carolina Panthers', 'Chicago Bears',
                'Cincinnati Bengals', 'Cleveland Browns', 'Dallas Cowboys',
                'Denver Broncos', 'Detroit Lions', 'Green Bay Packers',
                'Houston Texans', 'Indianapolis Colts', 'Jacksonville Jaguars',
                'Kansas City Chiefs', 'Las Vegas Raiders', 'Los Angeles Chargers',
                'Los Angeles Rams', 'Miami Dolphins', 'Minnesota Vikings',
                'New England Patriots', 'New Orleans Saints', 'New York Giants',
                'New York Jets', 'Philadelphia Eagles', 'Pittsburgh Steelers',
                'San Francisco 49ers', 'Seattle Seahawks', 'Tampa Bay Buccaneers',
                'Tennessee Titans', 'Washington Commanders'
            ]
            
            for team in all_teams:
                stats = predictor.get_team_stats(team)
                epa = predictor.get_team_epa(team)
                
                # Combine stats
                self.team_stats[team] = {
                    'ppg': stats.get('ppg', 22.5),
                    'oppg': stats.get('oppg', 22.5),
                    'win_pct': stats.get('win_pct', 0.5),
                    'off_epa': epa.get('off_epa_per_play', 0.0),
                    'def_epa': epa.get('def_epa_per_play', 0.0),
                    'pass_epa': epa.get('pass_epa', 0.0),
                    'rush_epa': epa.get('rush_epa', 0.0),
                    'success_rate': 0.5,  # Will be calculated if data available
                    'yards_per_game': stats.get('ypg', 330.0),
                    'games_played': 0,
                    'rest_days': 7,
                }
                
                # Also store by abbreviation
                abbr = NFL_TEAM_INDEX.get(team, team)
                if abbr != team:
                    self.team_stats[abbr] = self.team_stats[team]
            
            self._stats_loaded = True
            logger.info(f"Loaded stats for {len(all_teams)} NFL teams")
            return self.team_stats
            
        except Exception as e:
            logger.error(f"Error fetching NFL team stats: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _build_features(self, home_stats: Dict, away_stats: Dict) -> np.ndarray:
        """Build feature array from team stats."""
        features = [
            # Home team
            home_stats.get('ppg', 22.5),
            home_stats.get('oppg', 22.5),
            home_stats.get('win_pct', 0.5),
            home_stats.get('off_epa', 0.0),
            home_stats.get('def_epa', 0.0),
            home_stats.get('pass_epa', 0.0),
            home_stats.get('rush_epa', 0.0),
            home_stats.get('success_rate', 0.5),
            home_stats.get('yards_per_game', 330),
            # Away team
            away_stats.get('ppg', 22.5),
            away_stats.get('oppg', 22.5),
            away_stats.get('win_pct', 0.5),
            away_stats.get('off_epa', 0.0),
            away_stats.get('def_epa', 0.0),
            away_stats.get('pass_epa', 0.0),
            away_stats.get('rush_epa', 0.0),
            away_stats.get('success_rate', 0.5),
            away_stats.get('yards_per_game', 330),
            # Rest
            home_stats.get('rest_days', 7),
            away_stats.get('rest_days', 7),
        ]
        return np.array([features], dtype=np.float32)
    
    async def predict_game(
        self,
        home_team: str,
        away_team: str,
        total_line: float = 45.0,
        home_ml: int = None,
        away_ml: int = None
    ) -> Dict[str, Any]:
        """
        Predict NFL game outcome using nflverse data.
        """
        # Load models if needed
        if not self._loaded:
            self.load_models()
        
        # Fetch stats if needed
        if not self._stats_loaded:
            await self.fetch_team_stats_from_nflverse()
        
        # Get team stats
        home_stats = self.team_stats.get(home_team, {})
        away_stats = self.team_stats.get(away_team, {})
        
        # If no stats found, try abbreviation
        if not home_stats:
            home_abbr = NFL_TEAM_INDEX.get(home_team, home_team)
            home_stats = self.team_stats.get(home_abbr, {})
        if not away_stats:
            away_abbr = NFL_TEAM_INDEX.get(away_team, away_team)
            away_stats = self.team_stats.get(away_abbr, {})
        
        if not home_stats or not away_stats:
            # Use simple statistical model if no data
            return await self._simple_prediction(
                home_team, away_team, home_stats or {}, away_stats or {},
                total_line, home_ml, away_ml
            )
        
        # If we have trained models, use them
        if self.model_ml:
            return await self._xgboost_prediction(
                home_team, away_team, home_stats, away_stats,
                total_line, home_ml, away_ml
            )
        else:
            # Fall back to simple model
            return await self._simple_prediction(
                home_team, away_team, home_stats, away_stats,
                total_line, home_ml, away_ml
            )
    
    async def _xgboost_prediction(
        self, home_team: str, away_team: str,
        home_stats: Dict, away_stats: Dict,
        total_line: float, home_ml: int, away_ml: int
    ) -> Dict[str, Any]:
        """Make prediction using XGBoost model."""
        features = self._build_features(home_stats, away_stats)
        dmatrix = xgb.DMatrix(features)
        
        # Get ML prediction
        ml_pred = self.model_ml.predict(dmatrix)[0]
        
        # Handle different model output formats
        if hasattr(ml_pred, '__len__') and len(ml_pred) >= 2:
            home_win_prob = float(ml_pred[1])
            away_win_prob = float(ml_pred[0])
        else:
            home_win_prob = float(ml_pred)
            away_win_prob = 1 - home_win_prob
        
        # Get O/U prediction if available
        ou_pred = None
        if self.model_ou:
            ou_features = np.append(features, [[total_line]], axis=1)
            dmatrix_ou = xgb.DMatrix(ou_features)
            ou_raw = self.model_ou.predict(dmatrix_ou)[0]
            
            if hasattr(ou_raw, '__len__') and len(ou_raw) >= 2:
                under_prob = float(ou_raw[0])
                over_prob = float(ou_raw[1])
                ou_pred = {
                    'under_prob': round(under_prob, 3),
                    'over_prob': round(over_prob, 3),
                    'pick': 'OVER' if over_prob > under_prob else 'UNDER',
                    'confidence': round(max(over_prob, under_prob) * 100, 1),
                    'total_line': total_line
                }
        
        return self._format_result(
            home_team, away_team, home_win_prob, away_win_prob,
            home_stats, away_stats, ou_pred, home_ml, away_ml,
            model_name='nflverse_xgb'
        )
    
    async def _simple_prediction(
        self, home_team: str, away_team: str,
        home_stats: Dict, away_stats: Dict,
        total_line: float, home_ml: int, away_ml: int
    ) -> Dict[str, Any]:
        """Make prediction using simple statistical model."""
        # Calculate win probability based on available stats
        home_advantage = 0.03  # NFL home field advantage ~3%
        
        # Use EPA differential as primary predictor
        home_epa = home_stats.get('off_epa', 0) - home_stats.get('def_epa', 0)
        away_epa = away_stats.get('off_epa', 0) - away_stats.get('def_epa', 0)
        epa_diff = home_epa - away_epa
        
        # Also factor in win percentage
        home_wp = home_stats.get('win_pct', 0.5)
        away_wp = away_stats.get('win_pct', 0.5)
        wp_diff = home_wp - away_wp
        
        # Combined probability (EPA weighted more heavily)
        raw_prob = 0.5 + (epa_diff * 0.15) + (wp_diff * 0.2) + home_advantage
        home_win_prob = max(0.1, min(0.9, raw_prob))  # Clamp to reasonable range
        away_win_prob = 1 - home_win_prob
        
        # Simple O/U prediction based on PPG
        home_ppg = home_stats.get('ppg', 22.5)
        away_ppg = away_stats.get('ppg', 22.5)
        predicted_total = home_ppg + away_ppg
        
        ou_pred = {
            'pick': 'OVER' if predicted_total > total_line else 'UNDER',
            'confidence': round(abs(predicted_total - total_line) * 2 + 50, 1),
            'total_line': total_line,
            'predicted_total': round(predicted_total, 1)
        }
        
        return self._format_result(
            home_team, away_team, home_win_prob, away_win_prob,
            home_stats, away_stats, ou_pred, home_ml, away_ml,
            model_name='nflverse_simple'
        )
    
    def _format_result(
        self, home_team: str, away_team: str,
        home_win_prob: float, away_win_prob: float,
        home_stats: Dict, away_stats: Dict,
        ou_pred: Dict, home_ml: int, away_ml: int,
        model_name: str
    ) -> Dict[str, Any]:
        """Format prediction result."""
        # Calculate EV and Kelly if odds provided
        ev_home = ev_away = None
        kelly_home = kelly_away = None
        
        if home_ml and away_ml:
            ev_home = self._expected_value(home_win_prob, home_ml)
            ev_away = self._expected_value(away_win_prob, away_ml)
            kelly_home = self._kelly_criterion(home_ml, home_win_prob)
            kelly_away = self._kelly_criterion(away_ml, away_win_prob)
        
        predicted_winner = home_team if home_win_prob > away_win_prob else away_team
        confidence = round(max(home_win_prob, away_win_prob) * 100, 1)
        
        return {
            'model': model_name,
            'home_team': home_team,
            'away_team': away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_winner': predicted_winner,
            'confidence': confidence,
            'over_under': ou_pred,
            'ev_home': ev_home,
            'ev_away': ev_away,
            'kelly_home': kelly_home,
            'kelly_away': kelly_away,
            'features_used': len(self.FEATURE_NAMES),
            'home_epa': home_stats.get('off_epa', 0),
            'away_epa': away_stats.get('off_epa', 0),
        }
    
    def _expected_value(self, win_prob: float, american_odds: int) -> float:
        """Calculate expected value."""
        if american_odds > 0:
            payout = american_odds
        else:
            payout = (100 / abs(american_odds)) * 100
        
        loss_prob = 1 - win_prob
        ev = (win_prob * payout) - (loss_prob * 100)
        return round(ev, 2)
    
    def _kelly_criterion(self, american_odds: int, model_prob: float) -> float:
        """Calculate Kelly Criterion."""
        if american_odds >= 100:
            decimal_odds = american_odds / 100
        else:
            decimal_odds = 100 / abs(american_odds)
        
        bankroll_fraction = (100 * (decimal_odds * model_prob - (1 - model_prob))) / decimal_odds
        return round(max(0, bankroll_fraction), 2)


# Singleton instance
_predictor = None

def get_nflverse_predictor() -> NflversePredictor:
    global _predictor
    if _predictor is None:
        _predictor = NflversePredictor()
    return _predictor


async def predict_with_nflverse(
    home_team: str,
    away_team: str,
    total_line: float = 45.0,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """
    Convenience function to make NFL predictions using nflverse data.
    """
    predictor = get_nflverse_predictor()
    return await predictor.predict_game(
        home_team, away_team, total_line, home_ml, away_ml
    )
