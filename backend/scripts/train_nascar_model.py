import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from xgboost import XGBClassifier, XGBRegressor
from sklearn.ensemble import RandomForestRegressor, VotingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score

# Config
DATA_DIR = Path(__file__).parent.parent / "data" / "nascar"
MODEL_DIR = Path(__file__).parent.parent / "models" / "nascar" / "csv"
CSV_PATH = DATA_DIR / "cup_enhanced.csv"

# Feature Definition (Must match inference)
FEATURES = [
    # Categorical (Label Encoded or Numeric)
    'start', 'year', 'race_num',
    
    # Track Type Flags
    'is_road_course', 'is_superspeedway', 'is_short_track', 'is_dirt',
    
    # Career Stats
    'career_races', 'career_wins', 'career_win_pct', 
    'career_top5', 'career_top10', 'career_avg_finish',
    'career_laps_led_pct', 

    # Track History
    'races_at_track', 'wins_at_track', 
    'avg_finish_at_track', 'best_finish_at_track',
    
    # Recent Form
    'avg_finish_last_3', 'avg_finish_last_5', 'avg_finish_last_10',
    'laps_led_pct_last_5', 'consistency_score',
    
    # Team/Manu Stats
    'team_wins_this_season', 'team_top5_this_season', 
    'team_avg_finish_this_season',
    'manu_wins_this_season', 'manu_win_pct_this_season'
]

TARGET_CLS = 'race_win'
TARGET_REG = 'finishing_position'

def train_nascar_models():
    print("="*60)
    print("NASCAR Ensemble Model Training")
    print("="*60)
    
    # Ensure dirs
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load Data
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} not found.")
        return
        
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows.")

    # 2. Preprocessing
    # Handle missing values
    df[FEATURES] = df[FEATURES].fillna(0)
    
    # Train/Test Split (Time-based preferably, but simple for now)
    # Use 2023-2024 as test set if available, else random
    if 'year' in df.columns:
        train_df = df[df['year'] < 2024]
        test_df = df[df['year'] >= 2024]
        if len(test_df) < 100: # Fallback if 2024 not populated enough
            train_df, test_df = train_test_split(df, test_size=0.2, shuffle=False)
    else:
        train_df, test_df = train_test_split(df, test_size=0.2, shuffle=False)
        
    print(f"Train set: {len(train_df)}, Test set: {len(test_df)}")
    
    X_train = train_df[FEATURES]
    y_train_cls = train_df[TARGET_CLS]
    y_train_reg = train_df[TARGET_REG]
    
    X_test = test_df[FEATURES]
    y_test_cls = test_df[TARGET_CLS]
    y_test_reg = test_df[TARGET_REG]
    
    # 3. Train Classification Model (Win Probability)
    # Using XGBoost
    print("\nTraining Classification Model (XGBoost)...")
    xgb_clf = XGBClassifier(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        eval_metric='logloss',
        use_label_encoder=False,
        random_state=42
    )
    xgb_clf.fit(X_train, y_train_cls)
    
    y_pred_cls = xgb_clf.predict(X_test)
    y_prob_cls = xgb_clf.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test_cls, y_pred_cls)
    print(f"Classification Accuracy: {acc:.4f}")
    
    # 4. Train Regression Ensemble (Projected Finish)
    print("\nTraining Regression Ensemble (XGB + RF)...")
    
    # Model A: XGBoost
    xgb_reg = XGBRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=5,
        random_state=42
    )
    
    # Model B: Random Forest (for consistency handling)
    rf_reg = RandomForestRegressor(
        n_estimators=200,
        min_samples_leaf=5,
        random_state=42
    )
    
    # Ensemble
    ensemble = VotingRegressor([
        ('xgb', xgb_reg),
        ('rf', rf_reg)
    ])
    
    ensemble.fit(X_train, y_train_reg)
    
    y_pred_reg = ensemble.predict(X_test)
    mae = mean_absolute_error(y_test_reg, y_pred_reg)
    r2 = r2_score(y_test_reg, y_pred_reg)
    
    print(f"Ensemble MAE: {mae:.2f} positions")
    print(f"Ensemble R2: {r2:.4f}")
    
    # 5. Feature Importance (from XGB part of ensemble)
    # We can inspect the individual xgb model from the ensemble
    # But VotingRegressor doesn't expose it easily after fit unless we access estimators_
    
    # 6. Save Models
    joblib.dump(xgb_clf, MODEL_DIR / "classification_model.joblib")
    joblib.dump(ensemble, MODEL_DIR / "regression_model.joblib")
    
    print(f"\nModels saved to {MODEL_DIR}")
    
    # Save feature list for reference
    with open(MODEL_DIR / "features.txt", "w") as f:
        f.write("\n".join(FEATURES))

if __name__ == "__main__":
    train_nascar_models()
