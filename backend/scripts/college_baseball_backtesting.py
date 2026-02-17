
import asyncio
import logging
import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime, timedelta
from typing import List, Dict, Any
from college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CollegeBaseballBacktester:
    """
    Performs walk-forward validation on College Baseball XGBoost models.
    """
    
    def __init__(self):
        self.trainer = CollegeBaseballXGBTrainer()
        
    async def run_backtest(self, start_season=2024):
        """Run walk-forward backtest."""
        logger.info(f"Starting backtest from season {start_season}...")
        
        # Load all data
        df, y_win, y_total = await self.trainer._load_training_data()
        
        if df.empty:
            logger.error("No data for backtesting.")
            return

        # Combine into one dataframe for splitting
        data = df.copy()
        data['label_win'] = y_win
        data['label_total'] = y_total
        
        # We need dates or indices to split. 
        # The trainer loads data sorted by date, so we can use index splitting.
        # Let's say we need at least 200 games to train.
        min_train_size = 200
        total_games = len(data)
        
        if total_games < min_train_size + 50:
             logger.warning(f"Not enough data for meaningful backtest (Total: {total_games})")
             return

        # We'll re-train every 50 games (batch size)
        test_batch_size = 50
        
        results = []
        
        current_idx = min_train_size
        
        while current_idx < total_games:
            # Train window
            train_data = data.iloc[:current_idx]
            
            # Test window
            end_idx = min(current_idx + test_batch_size, total_games)
            test_data = data.iloc[current_idx:end_idx]
            
            if test_data.empty:
                break
                
            logger.info(f"Training on {len(train_data)} games, testing on {len(test_data)} games...")
            
            X_train = train_data[self.trainer.feature_names]
            y_train = train_data['label_win']
            
            X_test = test_data[self.trainer.feature_names]
            y_test_labels = test_data['label_win']
            
            # Train Model
            model = xgb.XGBClassifier(
                max_depth=3, learning_rate=0.05, n_estimators=200,
                objective='binary:logistic', eval_metric='logloss', use_label_encoder=False
            )
            model.fit(X_train, y_train)
            
            # Predict
            probs = model.predict_proba(X_test)[:, 1]
            preds = (probs > 0.5).astype(int)
            
            # Evaluate Batch
            accuracy = (preds == y_test_labels).mean()
            
            # Store results
            for i, prob in enumerate(probs):
                actual = y_test_labels.iloc[i]
                pred = preds[i]
                results.append({
                    'actual': actual,
                    'predicted': pred,
                    'probability': prob,
                    'correct': 1 if actual == pred else 0
                })
            
            logger.info(f"Batch Accuracy: {accuracy:.1%}")
            
            # Move window
            current_idx += test_batch_size
            
        # Overall Metrics
        results_df = pd.DataFrame(results)
        if not results_df.empty:
            total_acc = results_df['correct'].mean()
            logger.info("========================================")
            logger.info(f"Overall Backtest Accuracy: {total_acc:.1%}")
            logger.info(f"Total Games Tested: {len(results_df)}")
            logger.info("========================================")
            
            # ROI Analysis (Assuming -110 odds -> 52.4% breakeven)
            # Simple simulation: Bet on all games
            wins = results_df['correct'].sum()
            losses = len(results_df) - wins
            # Profit = (Wins * 0.909) - Losses  (Unit size 1)
            profit = (wins * 0.909) - losses
            roi = profit / len(results_df)
            
            logger.info(f"Simulated ROI (flat betting -110): {roi:.1%}")
            
            # Confidence Filtered ROI (>60% prob)
            high_conf = results_df[results_df['probability'] > 0.60]
            if not high_conf.empty:
                hc_wins = high_conf['correct'].sum()
                hc_losses = len(high_conf) - hc_wins
                hc_profit = (hc_wins * 0.909) - hc_losses
                hc_roi = hc_profit / len(high_conf)
                logger.info(f"High Confidence (>60%) ROI ({len(high_conf)} bets): {hc_roi:.1%} (Win% {high_conf['correct'].mean():.1%})")

if __name__ == "__main__":
    backtester = CollegeBaseballBacktester()
    asyncio.run(backtester.run_backtest())
