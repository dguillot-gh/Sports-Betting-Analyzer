"""
Apex Model - Main Predictor Class
Uses trained XGBoost models for NBA and NFL predictions.
Integrates with apex_features.py for feature extraction.
"""

import logging
import os
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    import numpy as np
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False


MODELS_DIR = "models/apex"


class ApexPredictor:
    """
    Apex model predictor for NBA and NFL.
    Uses pre-trained XGBoost models with enhanced features.
    """
    
    def __init__(self):
        self.nba_model_ml = None
        self.nba_model_ou = None
        self.nfl_model_ml = None
        self.nfl_model_ou = None
        
        self.feature_names_nba = []
        self.feature_names_nfl = []
        
        self._models_loaded = False
    
    def load_models(self) -> bool:
        """Load trained Apex models from disk."""
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available")
            return False
        
        if self._models_loaded:
            return True
        
        try:
            import json
            
            # NBA Models
            nba_ml_path = f"{MODELS_DIR}/nba_ml.json"
            if os.path.exists(nba_ml_path):
                self.nba_model_ml = xgb.Booster()
                self.nba_model_ml.load_model(nba_ml_path)
                logger.info("Loaded Apex NBA ML model")
            
            nba_ou_path = f"{MODELS_DIR}/nba_ou.json"
            if os.path.exists(nba_ou_path):
                self.nba_model_ou = xgb.Booster()
                self.nba_model_ou.load_model(nba_ou_path)
            
            # NFL Models
            nfl_ml_path = f"{MODELS_DIR}/nfl_ml.json"
            if os.path.exists(nfl_ml_path):
                self.nfl_model_ml = xgb.Booster()
                self.nfl_model_ml.load_model(nfl_ml_path)
                logger.info("Loaded Apex NFL ML model")
            
            nfl_ou_path = f"{MODELS_DIR}/nfl_ou.json"
            if os.path.exists(nfl_ou_path):
                self.nfl_model_ou = xgb.Booster()
                self.nfl_model_ou.load_model(nfl_ou_path)
            
            # Feature names
            nba_feat_path = f"{MODELS_DIR}/nba_features.json"
            if os.path.exists(nba_feat_path):
                with open(nba_feat_path) as f:
                    self.feature_names_nba = json.load(f)
            
            nfl_feat_path = f"{MODELS_DIR}/nfl_features.json"
            if os.path.exists(nfl_feat_path):
                with open(nfl_feat_path) as f:
                    self.feature_names_nfl = json.load(f)
            
            self._models_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error loading Apex models: {e}")
            return False
    
    async def predict_nba(
        self,
        home_team: str,
        away_team: str,
        total_line: float = 225.0,
        home_ml: int = None,
        away_ml: int = None
    ) -> Dict[str, Any]:
        """
        Predict NBA game outcome using Apex model.
        """
        if not self._models_loaded:
            if not self.load_models():
                return {"error": "Apex NBA model not trained yet"}
        
        if self.nba_model_ml is None:
            return {"error": "Apex NBA model not available - please train first"}
        
        from scripts.apex_features import get_feature_extractor
        
        # Get features
        extractor = get_feature_extractor()
        await extractor.load_nba_data()
        
        features = extractor.extract_nba_features(home_team, away_team)
        if features is None:
            return {"error": f"Could not extract features for {home_team} vs {away_team}"}
        
        # Ensure feature order matches training
        feature_values = [features.get(k, 0) for k in self.feature_names_nba]
        X = np.array([feature_values], dtype=np.float32)
        
        # Predict
        dmatrix = xgb.DMatrix(X)
        ml_prob = float(self.nba_model_ml.predict(dmatrix)[0])
        
        # ML model predicts home win probability
        home_win_prob = ml_prob
        away_win_prob = 1 - ml_prob
        
        # O/U prediction
        ou_pred = None
        if self.nba_model_ou and total_line:
            ou_raw = float(self.nba_model_ou.predict(dmatrix)[0])
            ou_pred = {
                'pick': 'OVER' if ou_raw > total_line else 'UNDER',
                'predicted_total': round(ou_raw, 1),
                'line': total_line,
                'confidence': round(abs(ou_raw - total_line) / 10 * 100, 1)
            }
        
        # Calculate EV if odds provided
        ev_home = ev_away = None
        if home_ml and away_ml:
            ev_home = self._expected_value(home_win_prob, home_ml)
            ev_away = self._expected_value(away_win_prob, away_ml)
        
        predicted_winner = home_team if home_win_prob > 0.5 else away_team
        confidence = max(home_win_prob, away_win_prob) * 100
        
        return {
            'model': 'apex',
            'model_version': 'v1.0',
            'sport': 'NBA',
            'home_team': home_team,
            'away_team': away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_winner': predicted_winner,
            'confidence': round(confidence, 1),
            'over_under': ou_pred,
            'ev_home': ev_home,
            'ev_away': ev_away,
            'features_used': len(self.feature_names_nba),
        }
    
    async def predict_nfl(
        self,
        home_team: str,
        away_team: str,
        total_line: float = 45.0,
        home_ml: int = None,
        away_ml: int = None
    ) -> Dict[str, Any]:
        """
        Predict NFL game outcome using Apex model.
        """
        if not self._models_loaded:
            if not self.load_models():
                return {"error": "Apex NFL model not trained yet"}
        
        if self.nfl_model_ml is None:
            return {"error": "Apex NFL model not available - please train first"}
        
        from scripts.apex_features import get_feature_extractor
        
        # Get features
        extractor = get_feature_extractor()
        await extractor.load_nfl_data()
        
        features = extractor.extract_nfl_features(home_team, away_team)
        if features is None:
            return {"error": f"Could not extract features for {home_team} vs {away_team}"}
        
        # Ensure feature order matches training
        feature_values = [features.get(k, 0) for k in self.feature_names_nfl]
        X = np.array([feature_values], dtype=np.float32)
        
        # Predict
        dmatrix = xgb.DMatrix(X)
        ml_prob = float(self.nfl_model_ml.predict(dmatrix)[0])
        
        home_win_prob = ml_prob
        away_win_prob = 1 - ml_prob
        
        # O/U prediction
        ou_pred = None
        if self.nfl_model_ou and total_line:
            ou_raw = float(self.nfl_model_ou.predict(dmatrix)[0])
            ou_pred = {
                'pick': 'OVER' if ou_raw > total_line else 'UNDER',
                'predicted_total': round(ou_raw, 1),
                'line': total_line,
                'confidence': round(abs(ou_raw - total_line) / 5 * 100, 1)
            }
        
        ev_home = ev_away = None
        if home_ml and away_ml:
            ev_home = self._expected_value(home_win_prob, home_ml)
            ev_away = self._expected_value(away_win_prob, away_ml)
        
        predicted_winner = home_team if home_win_prob > 0.5 else away_team
        confidence = max(home_win_prob, away_win_prob) * 100
        
        return {
            'model': 'apex',
            'model_version': 'v1.0',
            'sport': 'NFL',
            'home_team': home_team,
            'away_team': away_team,
            'home_win_probability': round(home_win_prob, 4),
            'away_win_probability': round(away_win_prob, 4),
            'predicted_winner': predicted_winner,
            'confidence': round(confidence, 1),
            'over_under': ou_pred,
            'ev_home': ev_home,
            'ev_away': ev_away,
            'features_used': len(self.feature_names_nfl),
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
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about loaded models."""
        import json
        
        info = {
            'nba_available': self.nba_model_ml is not None,
            'nfl_available': self.nfl_model_ml is not None,
            'nba_features': len(self.feature_names_nba),
            'nfl_features': len(self.feature_names_nfl),
        }
        
        # Load training metadata
        metadata_path = f"{MODELS_DIR}/metadata.json"
        if os.path.exists(metadata_path):
            with open(metadata_path) as f:
                info['training_metadata'] = json.load(f)
        
        return info


# Singleton
_predictor = None

def get_apex_predictor() -> ApexPredictor:
    global _predictor
    if _predictor is None:
        _predictor = ApexPredictor()
    return _predictor


async def predict_nba_apex(
    home_team: str,
    away_team: str,
    total_line: float = 225.0,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """Convenience function for NBA prediction."""
    predictor = get_apex_predictor()
    return await predictor.predict_nba(home_team, away_team, total_line, home_ml, away_ml)


async def predict_nfl_apex(
    home_team: str,
    away_team: str,
    total_line: float = 45.0,
    home_ml: int = None,
    away_ml: int = None
) -> Dict[str, Any]:
    """Convenience function for NFL prediction."""
    predictor = get_apex_predictor()
    return await predictor.predict_nfl(home_team, away_team, total_line, home_ml, away_ml)
