
import asyncio
import json
import logging
import os
import pandas as pd
import numpy as np
import joblib
from datetime import datetime
from typing import List, Dict, Tuple, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not installed - training will be unavailable")

MODELS_DIR = "models/college_baseball"

class CollegeBaseballXGBTrainer:
    """
    Trains XGBoost models on College Baseball game results using rolling stats.
    """
    
    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.feature_names = [
            'home_runs_scored_avg_l5', 'home_runs_allowed_avg_l5',
            'home_win_pct_l10', 'home_streak',
            'away_runs_scored_avg_l5', 'away_runs_allowed_avg_l5',
            'away_win_pct_l10', 'away_streak',
            'is_neutral'
        ]
        
        # Ensure models dir exists
        os.makedirs(MODELS_DIR, exist_ok=True)
        
    async def _load_training_data(self) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
        """
        Load historical game data from database and engineer features.
        Returns: (features_df, win_labels, total_runs)
        """
        logger.info("Loading College Baseball training data from database...")
        
        try:
            # Use DATABASE_URL from config if possible
            try:
                from src.config import DATABASE_URL as CFG_DB
                db_url = CFG_DB
            except:
                db_url = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/sports_betting")
            
            import asyncpg
            conn = await asyncpg.connect(db_url)
            
            # Fetch all games ordered chronologically
            # Use JSON extraction for metadata fields
            query = """
                SELECT season, metadata 
                FROM results 
                WHERE series = 'college_baseball' 
                ORDER BY event_date ASC
            """
            rows = await conn.fetch(query)
            await conn.close()
            
            if not rows or len(rows) < 50:
                logger.warning("Insufficient data for training (need >50 games)")
                return pd.DataFrame(), pd.Series(), pd.Series()
            
            # Parse game data
            games = []
            for row in rows:
                meta = json.loads(row['metadata'])
                meta['season'] = row['season']
                games.append(meta)
            
            logger.info(f"Loaded {len(games)} game records")
            
            # Build features with rolling statistics
            features_list = []
            win_labels = []
            totals = []
            
            # Group by team to calculate rolling stats
            # team -> list of game stats (runs_scored, runs_allowed, won)
            team_history = {} 
            
            for game in games:
                home_team = game.get('homeTeam')
                away_team = game.get('awayTeam')
                
                if not home_team or not away_team:
                    continue
                
                # Initialize team history if needed
                if home_team not in team_history: team_history[home_team] = []
                if away_team not in team_history: team_history[away_team] = []
                
                # Calculate features for this game based on history BEFORE this game
                home_feats = self._calculate_rolling_features(team_history[home_team])
                away_feats = self._calculate_rolling_features(team_history[away_team])
                
                # Only include games where both teams have enough history (e.g. 5 games)
                if home_feats and away_feats:
                    features = {
                        'home_runs_scored_avg_l5': home_feats['runs_scored_avg_l5'],
                        'home_runs_allowed_avg_l5': home_feats['runs_allowed_avg_l5'],
                        'home_win_pct_l10': home_feats['win_pct_l10'],
                        'home_streak': home_feats['streak'],
                        'away_runs_scored_avg_l5': away_feats['runs_scored_avg_l5'],
                        'away_runs_allowed_avg_l5': away_feats['runs_allowed_avg_l5'],
                        'away_win_pct_l10': away_feats['win_pct_l10'],
                        'away_streak': away_feats['streak'],
                        'is_neutral': 1 if game.get('neutralSite') else 0
                    }
                    
                    home_score = float(game.get('homeScore', 0))
                    away_score = float(game.get('awayScore', 0))
                    
                    winner = 1 if home_score > away_score else 0
                    total_runs = home_score + away_score
                    
                    features_list.append(features)
                    win_labels.append(winner)
                    totals.append(total_runs)
                
                # Update history AFTER processing (to avoid lookahead bias)
                # For neutral site games, 'home' designation is arbitrary but stats still count
                
                home_score = float(game.get('homeScore', 0))
                away_score = float(game.get('awayScore', 0))
                
                # Update Home Team History
                team_history[home_team].append({
                    'runs_scored': home_score,
                    'runs_allowed': away_score,
                    'won': 1 if home_score > away_score else 0
                })
                
                # Update Away Team History
                team_history[away_team].append({
                    'runs_scored': away_score,
                    'runs_allowed': home_score,
                    'won': 1 if away_score > home_score else 0
                })
            
            # Convert to DataFrame
            features_df = pd.DataFrame(features_list)
            # Reorder columns to match feature_names
            if not features_df.empty:
                features_df = features_df[self.feature_names]
                
            win_series = pd.Series(win_labels)
            total_series = pd.Series(totals)
            
            logger.info(f"Engineered {len(features_df)} training samples")
            return features_df, win_series, total_series
            
        except Exception as e:
            logger.error(f"Error loading training data: {e}", exc_info=True)
            return pd.DataFrame(), pd.Series(), pd.Series()

    def _calculate_rolling_features(self, history: List[Dict]) -> Dict:
        """Calculate rolling stats from a list of past game results."""
        if len(history) < 5:
            return None
            
        # Recent 5 games
        last_5 = history[-5:]
        runs_scored_l5 = sum(g['runs_scored'] for g in last_5) / 5.0
        runs_allowed_l5 = sum(g['runs_allowed'] for g in last_5) / 5.0
        
        # Recent 10 games
        last_10 = history[-10:]
        win_pct_l10 = sum(g['won'] for g in last_10) / len(last_10)
        
        # Streak (current)
        streak = 0
        for g in reversed(history):
            if g['won'] == 1:
                if streak >= 0: streak += 1
                else: break
            else:
                if streak <= 0: streak -= 1
                else: break
                
        return {
            'runs_scored_avg_l5': runs_scored_l5,
            'runs_allowed_avg_l5': runs_allowed_l5,
            'win_pct_l10': win_pct_l10,
            'streak': streak
        }

    async def train(self):
        """Train XGBoost models."""
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available.")
            return
            
        X, y_win, y_total = await self._load_training_data()
        
        if X.empty:
            logger.warning("No training data available.")
            return
            
        logger.info(f"Training XGBoost models on {len(X)} samples...")
        
        # 1. Train Classifier (Win/Loss)
        # Using binary:logistic for probability
        # Tuned hyperparameters for sports data (robust to noise)
        model_ml = xgb.XGBClassifier(
            max_depth=3,
            learning_rate=0.05,
            n_estimators=300,
            objective='binary:logistic',
            colsample_bytree=0.8,
            subsample=0.8,
            eval_metric='logloss',
            use_label_encoder=False
        )
        
        model_ml.fit(X, y_win)
        self.model_ml = model_ml
        
        # Save Classifier
        ml_path = os.path.join(MODELS_DIR, "cbb_xgb_classifier.json")
        model_ml.save_model(ml_path)
        logger.info(f"Saved classifier to {ml_path}")
        
        # 2. Train Regressor (Total Runs)
        model_ou = xgb.XGBRegressor(
            max_depth=3,
            learning_rate=0.05,
            n_estimators=300,
            objective='reg:squarederror',
            colsample_bytree=0.8,
            subsample=0.8
        )
        
        model_ou.fit(X, y_total)
        self.model_ou = model_ou
        
        # Save Regressor
        ou_path = os.path.join(MODELS_DIR, "cbb_xgb_regressor.json")
        model_ou.save_model(ou_path)
        logger.info(f"Saved regressor to {ou_path}")
        
        # Save feature names/metadata
        meta_path = os.path.join(MODELS_DIR, "model_metadata.json")
        with open(meta_path, 'w') as f:
            json.dump({
                "feature_names": self.feature_names,
                "trained_at": str(datetime.now()),
                "samples": len(X)
            }, f, indent=2)
            
        logger.info("Training complete.")

if __name__ == "__main__":
    trainer = CollegeBaseballXGBTrainer()
    asyncio.run(trainer.train())

def train_cbb_model_wrapper(job):
    """Wrapper for TrainingOrchestrator."""
    try:
        job.log("Initializing College Baseball XGBoost Trainer...")
        trainer = CollegeBaseballXGBTrainer()
        
        # Run async train in this thread (using new event loop)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        job.log("Loading data and training...")
        loop.run_until_complete(trainer.train())
        
        job.log("Training finished.")
        job.progress = 100
        job.status = "completed"
    except Exception as e:
        job.error = str(e)
        job.status = "failed"
        job.log(f"Training failed: {e}")
        raise e
    finally:
        loop.close()
