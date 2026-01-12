"""
NBA XGBoost Model Trainer
Trains XGBoost models on historical game data for win prediction
"""

import logging
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import asyncio

logger = logging.getLogger(__name__)

# Check if xgboost is available
try:
    import xgboost as xgb
    import numpy as np
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not installed - training will be unavailable")

MODELS_DIR = "models/nba"


class NBAXGBTrainer:
    """
    Trains XGBoost models on NBA game results.
    Uses team rolling statistics as features.
    """
    
    def __init__(self):
        self.model_ml = None  # Moneyline model
        self.model_ou = None  # Over/Under model
        self.feature_names = [
            'home_ppg', 'home_opp_ppg', 'away_ppg', 'away_opp_ppg',
            'home_win_pct', 'away_win_pct', 
            'home_last10_wins', 'away_last10_wins',
            'rest_days_home', 'rest_days_away'
        ]
        
        # Ensure models directory exists
        os.makedirs(MODELS_DIR, exist_ok=True)
    
    def _load_training_data(self) -> Tuple[List[Dict], List[int], List[float]]:
        """
        Load historical game data for training from nba_api.
        Returns features, win labels, and total points.
        """
        logger.info("Loading training data from nba_api...")
        
        features = []
        win_labels = []  # 1 = home win, 0 = away win
        totals = []  # Total points scored
        
        try:
            from nba_api.stats.endpoints import leaguegamelog
            import time
            
            # Fetch games from 2018-2025 seasons (includes current season)
            all_games = {}  # game_id -> game data
            team_stats = {}  # team_id -> rolling stats
            
            for season_year in range(2018, 2026):
                season_str = f"{season_year}-{str(season_year+1)[-2:]}"
                logger.info(f"Fetching {season_str} games...")
                
                try:
                    game_log = leaguegamelog.LeagueGameLog(
                        season=season_str,
                        season_type_all_star='Regular Season'
                    )
                    games_df = game_log.get_data_frames()[0]
                    time.sleep(0.6)  # Rate limiting
                    
                    # Group by game_id to pair home/away teams
                    for game_id in games_df['GAME_ID'].unique():
                        game_rows = games_df[games_df['GAME_ID'] == game_id]
                        if len(game_rows) != 2:
                            continue
                        
                        # Determine home vs away from matchup string
                        for _, row in game_rows.iterrows():
                            matchup = row['MATCHUP']
                            is_home = '@' not in matchup
                            team_name = row['TEAM_NAME']
                            pts = row['PTS']
                            win = 1 if row['WL'] == 'W' else 0
                            
                            if game_id not in all_games:
                                all_games[game_id] = {'season': season_year}
                            
                            if is_home:
                                all_games[game_id]['home_team'] = team_name
                                all_games[game_id]['home_pts'] = pts
                                all_games[game_id]['home_win'] = win
                            else:
                                all_games[game_id]['away_team'] = team_name
                                all_games[game_id]['away_pts'] = pts
                                
                except Exception as e:
                    logger.warning(f"Error fetching {season_str}: {e}")
                    continue
            
            logger.info(f"Processing {len(all_games)} games...")
            
            # Calculate rolling stats per team
            team_game_history = {}  # team -> list of (pts_scored, pts_allowed, win)
            
            # Sort games by game_id (chronological)
            sorted_games = sorted(all_games.items(), key=lambda x: x[0])
            
            for game_id, game in sorted_games:
                if 'home_team' not in game or 'away_team' not in game:
                    continue
                
                home = game['home_team']
                away = game['away_team']
                home_pts = game.get('home_pts', 0)
                away_pts = game.get('away_pts', 0)
                home_win = game.get('home_win', 0)
                
                # Get rolling stats (last 10 games)
                def get_rolling_stats(team):
                    history = team_game_history.get(team, [])[-10:]
                    if len(history) < 5:
                        return None  # Not enough history
                    ppg = sum(g[0] for g in history) / len(history)
                    oppg = sum(g[1] for g in history) / len(history)
                    win_pct = sum(g[2] for g in history) / len(history)
                    last5_wins = sum(g[2] for g in history[-5:])
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
                        'home_last10_wins': home_stats['last5_wins'],
                        'away_last10_wins': away_stats['last5_wins'],
                        'rest_days_home': 1,  # Would need date parsing
                        'rest_days_away': 1,
                    }
                    features.append(feature)
                    win_labels.append(home_win)
                    totals.append(home_pts + away_pts)
                
                # Update history
                if home not in team_game_history:
                    team_game_history[home] = []
                if away not in team_game_history:
                    team_game_history[away] = []
                team_game_history[home].append((home_pts, away_pts, home_win))
                team_game_history[away].append((away_pts, home_pts, 1 - home_win))
            
            logger.info(f"Loaded {len(features)} training samples from real games")
            
        except Exception as e:
            logger.error(f"Error loading training data: {e}")
            logger.info("Falling back to synthetic data...")
            return self._generate_synthetic_data()
        
        if len(features) < 100:
            logger.warning("Not enough real data, falling back to synthetic")
            return self._generate_synthetic_data()
        
        return features, win_labels, totals
    
    def _generate_synthetic_data(self) -> Tuple[List[Dict], List[int], List[float]]:
        """Generate synthetic training data as fallback."""
        import random
        random.seed(42)
        
        features = []
        win_labels = []
        totals = []
        
        for _ in range(1000):
            home_ppg = random.uniform(100, 125)
            away_ppg = random.uniform(100, 125)
            feature = {
                'home_ppg': home_ppg,
                'home_opp_ppg': random.uniform(105, 120),
                'away_ppg': away_ppg,
                'away_opp_ppg': random.uniform(105, 120),
                'home_win_pct': random.uniform(0.3, 0.7),
                'away_win_pct': random.uniform(0.3, 0.7),
                'home_last10_wins': random.randint(3, 8),
                'away_last10_wins': random.randint(3, 8),
                'rest_days_home': random.randint(0, 4),
                'rest_days_away': random.randint(0, 4),
            }
            home_win = 1 if home_ppg > away_ppg + random.gauss(0, 5) else 0
            features.append(feature)
            win_labels.append(home_win)
            totals.append(home_ppg + away_ppg + random.gauss(0, 10))
        
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
    
    def train(self, epochs: int = 500, output_dir: str = MODELS_DIR, callback=None) -> Dict[str, float]:
        """
        Train XGBoost models for moneyline and over/under.
        Uses TimeSeriesSplit cross-validation to prevent data leaking.
        Returns accuracy metrics.
        """
        if not XGB_AVAILABLE:
            if callback: callback("XGBoost not installed", 0)
            return {"error": "XGBoost not installed"}
        
        logger.info(f"Starting XGBoost training... Output: {output_dir}")
        if callback: callback("Loading training data...", 5)
        
        # Load data (already sorted by date)
        features, win_labels, totals = self._load_training_data()
        X = self._features_to_matrix(features)
        y_win = np.array(win_labels)
        y_total = np.array(totals)
        
        # Use TimeSeriesSplit to prevent data leaking
        # This ensures we only train on past data, test on future data
        from sklearn.model_selection import TimeSeriesSplit
        tscv = TimeSeriesSplit(n_splits=5)
        
        ml_accuracies = []
        ou_maes = []
        
        logger.info(f"Running 5-fold TimeSeriesSplit cross-validation on {len(X)} samples...")
        if callback: callback(f"Running 5-fold CV on {len(X)} samples...", 10)
        
        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X[train_idx], X[test_idx]
            y_win_train, y_win_test = y_win[train_idx], y_win[test_idx]
            y_total_train, y_total_test = y_total[train_idx], y_total[test_idx]
            
            # Train moneyline model (classification)
            dtrain_ml = xgb.DMatrix(X_train, label=y_win_train)
            dtest_ml = xgb.DMatrix(X_test, label=y_win_test)
            
            params_ml = {
                'max_depth': 4,
                'eta': 0.05,
                'objective': 'binary:logistic',
                'eval_metric': 'logloss'
            }
            
            # Use custom callback for per-fold logging if needed
            model_ml = xgb.train(params_ml, dtrain_ml, epochs // 5)  # Fewer epochs per fold
            
            # Evaluate ML model
            preds_ml = model_ml.predict(dtest_ml)
            preds_binary = (preds_ml > 0.5).astype(int)
            fold_accuracy = (preds_binary == y_win_test).mean()
            ml_accuracies.append(fold_accuracy)
            
            # Train over/under model (regression)
            dtrain_ou = xgb.DMatrix(X_train, label=y_total_train)
            dtest_ou = xgb.DMatrix(X_test, label=y_total_test)
            
            params_ou = {
                'max_depth': 4,
                'eta': 0.05,
                'objective': 'reg:squarederror',
            }
            
            model_ou = xgb.train(params_ou, dtrain_ou, epochs // 5)
            
            # Evaluate OU model
            preds_ou = model_ou.predict(dtest_ou)
            fold_mae = np.abs(preds_ou - y_total_test).mean()
            ou_maes.append(fold_mae)
            
            msg = f"Fold {fold + 1}: ML accuracy={fold_accuracy:.2%}, OU MAE={fold_mae:.1f}"
            logger.info(msg)
            if callback: callback(msg, 10 + (fold + 1) * 15)
        
        # Average cross-validation scores
        cv_ml_accuracy = np.mean(ml_accuracies)
        cv_ou_mae = np.mean(ou_maes)
        
        msg = f"CV Results: ML accuracy={cv_ml_accuracy:.2%} (±{np.std(ml_accuracies):.2%}), OU MAE={cv_ou_mae:.1f}"
        logger.info(msg)
        if callback: callback(msg, 90)
        
        # Now train final model on ALL data for production use
        logger.info("Training final model on full dataset...")
        dtrain_ml_full = xgb.DMatrix(X, label=y_win)
        dtrain_ou_full = xgb.DMatrix(X, label=y_total)
        
        params_ml = {
            'max_depth': 4,
            'eta': 0.05,
            'objective': 'binary:logistic',
            'eval_metric': 'logloss'
        }
        self.model_ml = xgb.train(params_ml, dtrain_ml_full, epochs)
        
        params_ou = {
            'max_depth': 4,
            'eta': 0.05,
            'objective': 'reg:squarederror',
        }
        self.model_ou = xgb.train(params_ou, dtrain_ou_full, epochs)
        
        # Save models
        os.makedirs(output_dir, exist_ok=True)
        self.model_ml.save_model(f"{output_dir}/xgb_moneyline.json")
        self.model_ou.save_model(f"{output_dir}/xgb_overunder.json")
        
        # Save metadata with CV results
        metadata = {
            "trained_at": datetime.now().isoformat(),
            "samples": len(X),
            "ml_accuracy": float(cv_ml_accuracy),
            "ml_accuracy_std": float(np.std(ml_accuracies)),
            "ou_mae": float(cv_ou_mae),
            "ou_mae_std": float(np.std(ou_maes)),
            "epochs": epochs,
            "cv_folds": 5,
            "cv_method": "TimeSeriesSplit",
            "features": self.feature_names
        }
        with open(f"{output_dir}/training_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Training complete: CV ML accuracy={cv_ml_accuracy:.2%}, CV OU MAE={cv_ou_mae:.1f}")
        
        if callback: callback("Training complete.", 100)
        
        return {
            "ml_accuracy": round(cv_ml_accuracy * 100, 1),
            "ou_mae": round(cv_ou_mae, 1),
            "samples_trained": len(X),
            "cv_folds": 5,
            "model_path": output_dir
        }
    
    def load_models(self, model_dir: str = MODELS_DIR) -> bool:
        """Load trained models from disk."""
        if not XGB_AVAILABLE:
            return False
        
        ml_path = f"{model_dir}/xgb_moneyline.json"
        ou_path = f"{model_dir}/xgb_overunder.json"
        
        if os.path.exists(ml_path) and os.path.exists(ou_path):
            self.model_ml = xgb.Booster()
            self.model_ml.load_model(ml_path)
            self.model_ou = xgb.Booster()
            self.model_ou.load_model(ou_path)
            logger.info(f"Loaded trained XGBoost models from {model_dir}")
            return True
        return False
    
    def predict(self, features: Dict) -> Dict[str, float]:
        """Make prediction using trained model."""
        if not self.model_ml or not self.model_ou:
            if not self.load_models():
                return {"error": "No trained model available"}
        
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

def get_trainer() -> NBAXGBTrainer:
    global _trainer
    if _trainer is None:
        _trainer = NBAXGBTrainer()
    return _trainer


async def train_nba_model(epochs: int = 500) -> Dict:
    """Async wrapper for training."""
    trainer = get_trainer()
    return trainer.train(epochs)


async def predict_with_xgb(home_team: str, away_team: str, 
                            home_stats: Dict, away_stats: Dict) -> Optional[Dict]:
    """
    Make prediction using XGBoost model.
    Returns None if model not available.
    """
    trainer = get_trainer()
    
    if not trainer.model_ml:
        if not trainer.load_models():
            return None
    
    features = {
        'home_ppg': home_stats.get('ppg', 114),
        'home_opp_ppg': home_stats.get('oppg', 114),
        'away_ppg': away_stats.get('ppg', 114),
        'away_opp_ppg': away_stats.get('oppg', 114),
        'home_win_pct': home_stats.get('win_pct', 0.5),
        'away_win_pct': away_stats.get('win_pct', 0.5),
        'home_last10_wins': 5,  # Placeholder
        'away_last10_wins': 5,  # Placeholder
        'rest_days_home': 1,
        'rest_days_away': 1,
    }
    
    result = trainer.predict(features)
    if "error" not in result:
        result["model"] = "xgboost"
        result["home_team"] = home_team
        result["away_team"] = away_team
    
    return result
