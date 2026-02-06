"""
Quick test script to evaluate NHL XGBoost model performance
"""
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    print("=" * 60)
    print("NHL XGBOOST MODEL EVALUATION")
    print("=" * 60)
    
    # Train the model
    print("\n[1/2] Training XGBoost model with walk-forward validation...")
    from scripts.nhl_xgb_trainer import train_nhl_model
    
    training_result = await train_nhl_model(epochs=200)
    
    print("\n✅ TRAINING COMPLETE")
    print(f"   Moneyline Accuracy: {training_result.get('ml_accuracy', 0)}%")
    print(f"   Over/Under MAE: {training_result.get('ou_mae', 0)} goals")
    print(f"   Training Samples: {training_result.get('samples_trained', 0)}")
    print(f"   Cross-Validation: {training_result.get('cv_folds', 0)}-fold")
    
    # Run backtest
    print("\n[2/2] Running comprehensive backtest...")
    from scripts.nhl_backtesting import run_nhl_backtest
    
    backtest_result = await run_nhl_backtest(
        min_edge=0.05,  # 5% minimum edge
        stake=100.0,
        use_kelly=False
    )
    
    print("\n✅ BACKTEST COMPLETE")
    print(f"   Total Bets: {backtest_result.get('total_bets', 0)}")
    print(f"   Win Rate: {backtest_result.get('win_rate', 0)}%")
    print(f"   Total Profit: ${backtest_result.get('total_profit', 0):.2f}")
    print(f"   ROI: {backtest_result.get('roi', 0)}%")
    print(f"   Sharpe Ratio: {backtest_result.get('sharpe_ratio', 0)}")
    print(f"   Max Drawdown: ${backtest_result.get('max_drawdown', 0):.2f}")
    
    # Save results to file for frontend
    import json
    results = {
        "training": training_result,
        "backtest": backtest_result,
        "timestamp": "2026-02-04T21:22:00"
    }
    
    output_path = "models/nhl/performance_report.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📊 Results saved to: {output_path}")
    print("=" * 60)
    
    return results

if __name__ == "__main__":
    result = asyncio.run(main())
