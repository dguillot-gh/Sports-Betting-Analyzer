"""
NFL XGBoost Model Trainer
Trains XGBoost models on historical game data for win prediction
Uses nflreadpy (Python port of nflfastR) for data
"""

import logging
import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Check if xgboost is available
try:
    import xgboost as xgb
    import numpy as np
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not installed - training will be unavailable")

MODELS_DIR = "models/nfl"


class NFLXGBTrainer:
    """
    Trains XGBoost models on NFL game results.
    Uses team rolling statistics and EPA as features.
    """
    
    def __init__(self):
        self.model_ml = None  # Moneyline model
        self.model_ou = None  # Over/Under model
        self.feature_names = [
            'home_ppg', 'home_opp_ppg', 'away_ppg', 'away_opp_ppg',
            'home_win_pct', 'away_win_pct', 
            'home_last5_wins', 'away_last5_wins',
            'home_epa_per_play', 'away_epa_per_play'
        ]
        
        # Ensure models directory exists
        os.makedirs(MODELS_DIR, exist_ok=True)
    
    def _load_training_data(self) -> Tuple[List[Dict], List[int], List[float]]:
        """
        Load historical NFL game data for training from nflreadpy.
        Returns features, win labels, and total points.
        """
        logger.info("Loading NFL training data from nflreadpy...")
        
        features = []
        win_labels = []  # 1 = home win, 0 = away win
        totals = []  # Total points scored
        
        try:
            import nfl_data_py as nfl
            
            # Fetch game schedules 2018-2025 (includes current season)
            logger.info("Fetching NFL schedules...")
            schedules_df = nfl.import_schedules([2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025])
            
            # Filter to completed games only
            games = schedules_df[schedules_df['home_score'].notna()].copy()
            games = games.sort_values('gameday')
            
            logger.info(f"Processing {len(games)} NFL games...")
            
            # Calculate rolling stats per team
            team_history = {}  # team -> list of (pts_scored, pts_allowed, win)
            
            for _, game in games.iterrows():
                home = game['home_team']
                away = game['away_team']
                home_pts = game.get('home_score', 0) or 0
                away_pts = game.get('away_score', 0) or 0
                home_win = 1 if home_pts > away_pts else 0
                
                # Get rolling stats (last 8 games for NFL)
                def get_rolling_stats(team):
                    history = team_history.get(team, [])[-8:]
                    if len(history) < 4:
                        return None  # Not enough history
                    ppg = sum(g[0] for g in history) / len(history)
                    oppg = sum(g[1] for g in history) / len(history)
                    win_pct = sum(g[2] for g in history) / len(history)
                    last5_wins = sum(g[2] for g in history[-5:]) if len(history) >= 5 else sum(g[2] for g in history)
                    return {'ppg': ppg, 'oppg': oppg, 'win_pct': win_pct, 'last5_wins': last5_wins}
                
                home_stats = get_rolling_stats(home)
                away_stats = get_rolling_stats(away)
                
                # Only use games where both teams have history
                if home_stats and away_stats:
                    feature = {
                        'home_ppg': home_stats['ppg'],
                        'home_opp_ppg': home_stats['oppg'],
                        'away_ppg': away_stats['ppg'],
                        'away_opp_ppg': away_stats['oppg'],
                        'home_win_pct': home_stats['win_pct'],
                        'away_win_pct': away_stats['win_pct'],
                        'home_last5_wins': home_stats['last5_wins'],
                        'away_last5_wins': away_stats['last5_wins'],
                        'home_epa_per_play': 0.0,  # TODO: Add EPA from pbp data
                        'away_epa_per_play': 0.0,
                    }
                    features.append(feature)
                    win_labels.append(home_win)
                    totals.append(home_pts + away_pts)
                
                # Update history
                if home not in team_history:
                    team_history[home] = []
                if away not in team_history:
                    team_history[away] = []
                team_history[home].append((home_pts, away_pts, home_win))
                team_history[away].append((away_pts, home_pts, 1 - home_win))
            
            logger.info(f"Loaded {len(features)} NFL training samples from real games")
            
        except Exception as e:
            logger.error(f"Error loading NFL training data: {e}")
            logger.info("Falling back to synthetic data...")
            return self._generate_synthetic_data()
        
        if len(features) < 100:
            logger.warning("Not enough real NFL data, falling back to synthetic")
            return self._generate_synthetic_data()
        
        return features, win_labels, totals
    
    def _generate_synthetic_data(self) -> Tuple[List[Dict], List[int], List[float]]:
        """Generate synthetic NFL training data as fallback."""
        import random
        random.seed(42)
        
        features = []
        win_labels = []
        totals = []
        
        for _ in range(500):
            home_ppg = random.uniform(17, 30)
            away_ppg = random.uniform(17, 30)
            feature = {
                'home_ppg': home_ppg,
                'home_opp_ppg': random.uniform(18, 26),
                'away_ppg': away_ppg,
                'away_opp_ppg': random.uniform(18, 26),
                'home_win_pct': random.uniform(0.25, 0.75),
                'away_win_pct': random.uniform(0.25, 0.75),
                'home_last5_wins': random.randint(1, 5),
                'away_last5_wins': random.randint(1, 5),
                'home_epa_per_play': random.uniform(-0.1, 0.15),
                'away_epa_per_play': random.uniform(-0.1, 0.15),
            }
            home_win = 1 if home_ppg > away_ppg + random.gauss(0, 4) else 0
            features.append(feature)
            win_labels.append(home_win)
            totals.append(home_ppg + away_ppg + random.gauss(0, 6))
        
        return features, win_labels, totals
    
    def _features_to_matrix(self, features: List[Dict]) -> 'np.ndarray':
        """Convert feature dicts to numpy matrix."""
        if not XGB_AVAILABLE:
            raise RuntimeError("XGBoost not installed")
        
        matrix = []
        for f in features:
            row = [f.get(name, 0) for name in self.feature_names]
            matrix.append(row)
        return np.array(matrix, dtype=np.float32)
    
    def train(self, epochs: int = 500) -> Dict[str, float]:
        """
        Train XGBoost models for moneyline and over/under.
        Returns accuracy metrics.
        """
        if not XGB_AVAILABLE:
            return {"error": "XGBoost not installed"}
        
        logger.info("Starting NFL XGBoost training...")
        
        # Load data
        features, win_labels, totals = self._load_training_data()
        X = self._features_to_matrix(features)
        y_win = np.array(win_labels)
        y_total = np.array(totals)
        
        # Split train/test (80/20)
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_win_train, y_win_test = y_win[:split_idx], y_win[split_idx:]
        y_total_train, y_total_test = y_total[:split_idx], y_total[split_idx:]
        
        # Train moneyline model
        dtrain_ml = xgb.DMatrix(X_train, label=y_win_train)
        dtest_ml = xgb.DMatrix(X_test, label=y_win_test)
        
        params_ml = {
            'max_depth': 4,
            'eta': 0.05,
            'objective': 'binary:logistic',
            'eval_metric': 'logloss'
        }
        
        self.model_ml = xgb.train(params_ml, dtrain_ml, epochs)
        
        # Evaluate
        preds_ml = self.model_ml.predict(dtest_ml)
        preds_binary = (preds_ml > 0.5).astype(int)
        ml_accuracy = (preds_binary == y_win_test).mean()
        
        # Train over/under model
        dtrain_ou = xgb.DMatrix(X_train, label=y_total_train)
        dtest_ou = xgb.DMatrix(X_test, label=y_total_test)
        
        params_ou = {
            'max_depth': 4,
            'eta': 0.05,
            'objective': 'reg:squarederror',
        }
        
        self.model_ou = xgb.train(params_ou, dtrain_ou, epochs)
        
        preds_ou = self.model_ou.predict(dtest_ou)
        ou_mae = np.abs(preds_ou - y_total_test).mean()
        
        # Save models
        self.model_ml.save_model(f"{MODELS_DIR}/xgb_moneyline.json")
        self.model_ou.save_model(f"{MODELS_DIR}/xgb_overunder.json")
        
        # Save metadata
        metadata = {
            "trained_at": datetime.now().isoformat(),
            "samples": len(X),
            "ml_accuracy": float(ml_accuracy),
            "ou_mae": float(ou_mae),
            "epochs": epochs,
            "features": self.feature_names
        }
        with open(f"{MODELS_DIR}/training_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"NFL Training complete: ML accuracy={ml_accuracy:.2%}, OU MAE={ou_mae:.1f}")
        
        return {
            "ml_accuracy": round(ml_accuracy * 100, 1),
            "ou_mae": round(ou_mae, 1),
            "samples_trained": len(X),
            "model_path": MODELS_DIR
        }
    
    def load_models(self) -> bool:
        """Load trained models from disk."""
        if not XGB_AVAILABLE:
            return False
        
        ml_path = f"{MODELS_DIR}/xgb_moneyline.json"
        ou_path = f"{MODELS_DIR}/xgb_overunder.json"
        
        if os.path.exists(ml_path) and os.path.exists(ou_path):
            self.model_ml = xgb.Booster()
            self.model_ml.load_model(ml_path)
            self.model_ou = xgb.Booster()
            self.model_ou.load_model(ou_path)
            logger.info("Loaded trained NFL XGBoost models")
            return True
        return False
    
    def predict(self, features: Dict) -> Dict[str, float]:
        """Make prediction using trained model."""
        if not self.model_ml or not self.model_ou:
            if not self.load_models():
                return {"error": "No trained NFL model available"}
        
        X = self._features_to_matrix([features])
        dmatrix = xgb.DMatrix(X)
        
        home_win_prob = float(self.model_ml.predict(dmatrix)[0])
        predicted_total = float(self.model_ou.predict(dmatrix)[0])
        
        return {
            "home_win_probability": round(home_win_prob, 3),
            "away_win_probability": round(1 - home_win_prob, 3),
            "predicted_total": round(predicted_total, 1)
        }


# Singleton instance
_trainer = None

def get_trainer() -> NFLXGBTrainer:
    global _trainer
    if _trainer is None:
        _trainer = NFLXGBTrainer()
    return _trainer


async def train_nfl_model(epochs: int = 500) -> Dict:
    """Async wrapper for training."""
    trainer = get_trainer()
    return trainer.train(epochs)


async def predict_nfl_xgb(home_team: str, away_team: str, 
                          home_stats: Dict, away_stats: Dict) -> Optional[Dict]:
    """
    Make NFL prediction using XGBoost model.
    Returns None if model not available.
    """
    trainer = get_trainer()
    
    if not trainer.model_ml:
        if not trainer.load_models():
            return None
    
    features = {
        'home_ppg': home_stats.get('ppg', 22.5),
        'home_opp_ppg': home_stats.get('oppg', 22.5),
        'away_ppg': away_stats.get('ppg', 22.5),
        'away_opp_ppg': away_stats.get('oppg', 22.5),
        'home_win_pct': home_stats.get('win_pct', 0.5),
        'away_win_pct': away_stats.get('win_pct', 0.5),
        'home_last5_wins': 2,
        'away_last5_wins': 2,
        'home_epa_per_play': 0.0,
        'away_epa_per_play': 0.0,
    }
    
    result = trainer.predict(features)
    if "error" not in result:
        result["model"] = "xgboost"
        result["home_team"] = home_team
        result["away_team"] = away_team
    
    return result
