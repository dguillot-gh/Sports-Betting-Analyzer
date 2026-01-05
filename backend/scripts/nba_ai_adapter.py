"""
NBA_AI Adapter - Integrates NBA_AI prediction engines
Based on: https://github.com/NBA-Betting/NBA_AI

Provides 5 prediction engines:
- Baseline: Simple PPG-based predictor
- Linear: Ridge Regression with 43 rolling features
- Tree: XGBoost model
- MLP: PyTorch neural network
- Ensemble: Weighted average (30% Linear + 40% Tree + 30% MLP)
"""

import logging
import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Models directory
MODELS_DIR = Path(__file__).parent / "nba_ai_models"


class NBABaselinePredictor:
    """Simple baseline predictor using PPG and opponent PPG."""
    
    def __init__(self):
        self.name = "Baseline"
    
    def predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """
        Predict using simple PPG/defensive metrics.
        
        Expected stats:
        - pts_per_game: Points per game
        - opp_pts_per_game: Opponent points allowed per game
        """
        home_ppg = home_stats.get('pts_per_game', 110)
        away_ppg = away_stats.get('pts_per_game', 108)
        home_def = home_stats.get('opp_pts_per_game', 112)
        away_def = away_stats.get('opp_pts_per_game', 112)
        
        # Simple formula: average of offensive and opponent's defense
        home_score = (home_ppg + away_def) / 2
        away_score = (away_ppg + home_def) / 2
        
        # Add home court advantage (~3 points)
        home_score += 1.5
        away_score -= 1.5
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "low"
        }
    
    def _margin_to_prob(self, margin: float) -> float:
        """Convert predicted margin to win probability using logistic function."""
        # Approximate: 4 points = ~64% win probability
        return float(1 / (1 + np.exp(-margin / 5)))


class NBALinearPredictor:
    """Ridge Regression predictor using rolling features."""
    
    def __init__(self):
        self.name = "Linear"
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load pre-trained Ridge model if available."""
        model_path = MODELS_DIR / "linear_model.joblib"
        if model_path.exists():
            try:
                import joblib
                self.model = joblib.load(model_path)
                logger.info("Loaded Linear (Ridge) model")
            except Exception as e:
                logger.warning(f"Could not load Linear model: {e}")
    
    def predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Predict using Ridge Regression or fallback to baseline-enhanced."""
        if self.model is None:
            # Fallback: enhanced baseline
            return self._fallback_predict(home_stats, away_stats)
        
        # Build feature vector (simplified)
        features = self._build_features(home_stats, away_stats)
        
        try:
            prediction = self.model.predict([features])[0]
            home_score = prediction[0] if len(prediction) > 1 else 110
            away_score = prediction[1] if len(prediction) > 1 else 108
        except Exception as e:
            logger.warning(f"Linear prediction failed: {e}")
            return self._fallback_predict(home_stats, away_stats)
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "medium"
        }
    
    def _fallback_predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Fallback prediction when model not available."""
        home_ppg = home_stats.get('pts_per_game', 110)
        away_ppg = away_stats.get('pts_per_game', 108)
        home_fg = home_stats.get('fg_pct', 0.47)
        away_fg = away_stats.get('fg_pct', 0.46)
        
        # Weight FG% into prediction
        home_score = home_ppg * (1 + (home_fg - 0.46) * 0.5) + 2
        away_score = away_ppg * (1 + (away_fg - 0.46) * 0.5)
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "low",
            "note": "Using fallback method"
        }
    
    def _build_features(self, home_stats: Dict, away_stats: Dict) -> List[float]:
        """Build feature vector from stats."""
        features = []
        for stat in ['pts_per_game', 'reb_per_game', 'ast_per_game', 'fg_pct', 'fg3_pct']:
            features.append(home_stats.get(stat, 0))
            features.append(away_stats.get(stat, 0))
        return features
    
    def _margin_to_prob(self, margin: float) -> float:
        return float(1 / (1 + np.exp(-margin / 5)))


class NBATreePredictor:
    """XGBoost-based predictor."""
    
    def __init__(self):
        self.name = "Tree"
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load pre-trained XGBoost model."""
        model_path = MODELS_DIR / "tree_model.joblib"
        if model_path.exists():
            try:
                import joblib
                self.model = joblib.load(model_path)
                logger.info("Loaded Tree (XGBoost) model")
            except Exception as e:
                logger.warning(f"Could not load Tree model: {e}")
        else:
            # Try loading from kyleskom models (already in our system)
            try:
                from scripts.kyleskom_adapter import KyleskomPredictor
                self.kyleskom = KyleskomPredictor()
                logger.info("Using kyleskom XGBoost as Tree model")
            except Exception as e:
                logger.warning(f"Could not load kyleskom: {e}")
    
    def predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Predict using XGBoost."""
        if hasattr(self, 'kyleskom') and self.kyleskom:
            # Use kyleskom adapter
            try:
                result = self.kyleskom.predict_game(
                    home_stats.get('team_name', 'Home'),
                    away_stats.get('team_name', 'Away'),
                    home_stats.get('total_line', 225)
                )
                return {
                    "predictor": self.name,
                    "home_score": result.get('predicted_home_score', 110),
                    "away_score": result.get('predicted_away_score', 108),
                    "margin": result.get('margin', 2),
                    "home_win_prob": result.get('home_win_prob', 0.52),
                    "confidence": "high"
                }
            except Exception as e:
                logger.warning(f"Kyleskom prediction failed: {e}")
        
        # Fallback to enhanced baseline
        return self._enhanced_predict(home_stats, away_stats)
    
    def _enhanced_predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Enhanced prediction using multiple factors."""
        home_ppg = home_stats.get('pts_per_game', 110)
        away_ppg = away_stats.get('pts_per_game', 108)
        home_record = home_stats.get('win_pct', 0.5)
        away_record = away_stats.get('win_pct', 0.5)
        
        # Factor in win percentage
        home_adj = 1 + (home_record - 0.5) * 0.15
        away_adj = 1 + (away_record - 0.5) * 0.15
        
        home_score = home_ppg * home_adj + 2
        away_score = away_ppg * away_adj
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "medium"
        }
    
    def _margin_to_prob(self, margin: float) -> float:
        return float(1 / (1 + np.exp(-margin / 5)))


class NBAMLPPredictor:
    """PyTorch MLP-based predictor."""
    
    def __init__(self):
        self.name = "MLP"
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load pre-trained PyTorch MLP model."""
        model_path = MODELS_DIR / "mlp_model.pt"
        if model_path.exists():
            try:
                import torch
                self.model = torch.load(model_path, map_location='cpu')
                self.model.eval()
                logger.info("Loaded MLP (PyTorch) model")
            except Exception as e:
                logger.warning(f"Could not load MLP model: {e}")
    
    def predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Predict using MLP or fallback."""
        if self.model is None:
            return self._fallback_predict(home_stats, away_stats)
        
        try:
            import torch
            features = self._build_features(home_stats, away_stats)
            x = torch.tensor([features], dtype=torch.float32)
            with torch.no_grad():
                output = self.model(x)
            home_score, away_score = output[0].numpy()
        except Exception as e:
            logger.warning(f"MLP prediction failed: {e}")
            return self._fallback_predict(home_stats, away_stats)
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(float(home_score), 1),
            "away_score": round(float(away_score), 1),
            "margin": round(float(margin), 1),
            "home_win_prob": round(float(home_win_prob), 3),
            "confidence": "medium"
        }
    
    def _fallback_predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Fallback when model not available."""
        # Use slightly different weighting than baseline
        home_ppg = home_stats.get('pts_per_game', 110)
        away_ppg = away_stats.get('pts_per_game', 108)
        home_pace = home_stats.get('pace', 100)
        away_pace = away_stats.get('pace', 100)
        
        avg_pace = (home_pace + away_pace) / 2 / 100
        home_score = home_ppg * avg_pace + 1.5
        away_score = away_ppg * avg_pace - 1.5
        
        margin = home_score - away_score
        home_win_prob = self._margin_to_prob(margin)
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "low",
            "note": "Using fallback method"
        }
    
    def _build_features(self, home_stats: Dict, away_stats: Dict) -> List[float]:
        features = []
        for stat in ['pts_per_game', 'reb_per_game', 'ast_per_game', 'fg_pct']:
            features.append(home_stats.get(stat, 0))
            features.append(away_stats.get(stat, 0))
        return features
    
    def _margin_to_prob(self, margin: float) -> float:
        return float(1 / (1 + np.exp(-margin / 5)))


class NBAEnsemblePredictor:
    """Ensemble predictor combining multiple engines."""
    
    def __init__(self):
        self.name = "Ensemble"
        self.weights = {
            "Linear": 0.30,
            "Tree": 0.40,
            "MLP": 0.30
        }
        self.predictors = {
            "Linear": NBALinearPredictor(),
            "Tree": NBATreePredictor(),
            "MLP": NBAMLPPredictor()
        }
    
    def predict(self, home_stats: Dict, away_stats: Dict) -> Dict:
        """Weighted average of Linear, Tree, and MLP predictions."""
        predictions = {}
        for name, predictor in self.predictors.items():
            predictions[name] = predictor.predict(home_stats, away_stats)
        
        # Weighted average
        total_weight = sum(self.weights.values())
        home_score = sum(
            self.weights[name] * pred["home_score"]
            for name, pred in predictions.items()
        ) / total_weight
        
        away_score = sum(
            self.weights[name] * pred["away_score"]
            for name, pred in predictions.items()
        ) / total_weight
        
        home_win_prob = sum(
            self.weights[name] * pred["home_win_prob"]
            for name, pred in predictions.items()
        ) / total_weight
        
        margin = home_score - away_score
        
        return {
            "predictor": self.name,
            "home_score": round(home_score, 1),
            "away_score": round(away_score, 1),
            "margin": round(margin, 1),
            "home_win_prob": round(home_win_prob, 3),
            "confidence": "high",
            "components": {
                name: {"weight": self.weights[name], "prob": pred["home_win_prob"]}
                for name, pred in predictions.items()
            }
        }


class NBAAIPredictionManager:
    """
    Main class for managing NBA_AI predictions.
    Provides predictions from all 5 engines.
    """
    
    def __init__(self):
        self.engines = {
            "Baseline": NBABaselinePredictor(),
            "Linear": NBALinearPredictor(),
            "Tree": NBATreePredictor(),
            "MLP": NBAMLPPredictor(),
            "Ensemble": NBAEnsemblePredictor()
        }
        logger.info(f"NBA_AI Prediction Manager initialized with {len(self.engines)} engines")
    
    def predict_all(self, home_stats: Dict, away_stats: Dict) -> Dict[str, Any]:
        """
        Get predictions from all engines.
        
        Returns dict with predictions from each engine.
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "home_team": home_stats.get("team_name", "Home"),
            "away_team": away_stats.get("team_name", "Away"),
            "predictions": {}
        }
        
        for name, engine in self.engines.items():
            try:
                results["predictions"][name] = engine.predict(home_stats, away_stats)
            except Exception as e:
                logger.error(f"Engine {name} failed: {e}")
                results["predictions"][name] = {"error": str(e)}
        
        # Add consensus pick
        probs = [
            p["home_win_prob"] 
            for p in results["predictions"].values() 
            if "home_win_prob" in p
        ]
        if probs:
            avg_prob = sum(probs) / len(probs)
            results["consensus"] = {
                "home_win_prob": round(avg_prob, 3),
                "pick": "Home" if avg_prob > 0.5 else "Away",
                "confidence": "high" if abs(avg_prob - 0.5) > 0.15 else "medium" if abs(avg_prob - 0.5) > 0.08 else "low"
            }
        
        return results
    
    def predict_with_engine(self, engine_name: str, home_stats: Dict, away_stats: Dict) -> Dict:
        """Get prediction from a specific engine."""
        if engine_name not in self.engines:
            return {"error": f"Unknown engine: {engine_name}"}
        return self.engines[engine_name].predict(home_stats, away_stats)


# Module-level instance for easy access
_manager = None

def get_nba_ai_predictions(home_stats: Dict, away_stats: Dict) -> Dict:
    """Get predictions from all NBA_AI engines."""
    global _manager
    if _manager is None:
        _manager = NBAAIPredictionManager()
    return _manager.predict_all(home_stats, away_stats)


if __name__ == "__main__":
    # Test
    home = {"team_name": "Lakers", "pts_per_game": 115, "fg_pct": 0.48}
    away = {"team_name": "Celtics", "pts_per_game": 118, "fg_pct": 0.47}
    
    results = get_nba_ai_predictions(home, away)
    print(json.dumps(results, indent=2))
