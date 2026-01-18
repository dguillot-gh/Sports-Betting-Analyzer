import sys
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
from pathlib import Path
from datetime import datetime
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, r2_score

# Setup Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "ncaab"
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

def load_data():
    """Load and prep data from local parquet"""
    path = DATA_DIR / "ncaab_team_box_history.parquet"
    if not path.exists():
        path = Path("ncaab_team_box_history.parquet")
        if not path.exists():
            raise FileNotFoundError(f"Data not found at {path}")
    
    df = pd.read_parquet(path)
    df['game_date'] = pd.to_datetime(df['game_date'])
    return df

def engineer_features_v2(df):
    """
    Advanced Feature Engineering inspired by Kaggle Elite models:
    - Multi-window aggregations (mean, std, skew, median)
    - Seasonal trends
    - Matchup difference features
    """
    print("Engineering features V2 (Deep Aggregation)...")
    df = df.copy().sort_values(['team_display_name', 'game_date'])
    
    # Core stats to aggregate
    core_stats = [
        'team_score', 'opponent_team_score', 'field_goal_pct', 'three_point_field_goal_pct',
        'free_throw_pct', 'total_rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'fouls'
    ]
    
    # Ensure columns exist
    core_stats = [s for s in core_stats if s in df.columns]
    
    # 1. Team-level Aggregations
    new_features_list = []
    windows = [5, 10, 20]
    
    for stat in core_stats:
        grouped = df.groupby(['season', 'team_display_name'])[stat]
        shifted = grouped.shift(1)
        
        stat_dict = {}
        for w in windows:
            stat_dict[f'{stat}_mean_{w}'] = shifted.rolling(w, min_periods=3).mean()
            stat_dict[f'{stat}_std_{w}'] = shifted.rolling(w, min_periods=3).std()
            stat_dict[f'{stat}_median_{w}'] = shifted.rolling(w, min_periods=3).median()
            
        stat_dict[f'{stat}_season_avg'] = shifted.expanding(min_periods=5).mean()
        
        # Collection of all stats for this column
        new_features_list.append(pd.DataFrame(stat_dict, index=df.index))

    # Concat all new features at once to avoid fragmentation
    print("Concatenating technical features...")
    df_features = pd.concat(new_features_list, axis=1)
    df = pd.concat([df, df_features], axis=1)
    
    technical_feature_names = df_features.columns.tolist()

    # 2. Cleanup and Pair Matchups
    df['is_home'] = df['team_home_away'].map({'home': 1, 'away': 0}).fillna(0)
    
    # Prepare the paired dataset (Game ID based)
    df_clean = df.dropna(subset=[f for f in technical_feature_names if 'mean_5' in f])
    
    print("Pairing matchups...")
    home_df = df_clean[df_clean['is_home'] == 1].copy()
    away_df = df_clean[df_clean['is_home'] == 0].copy()
    
    id_cols = ['game_id', 'game_date', 'season', 'team_display_name', 'team_score', 'opponent_team_score']
    
    matchups = pd.merge(
        home_df[id_cols + technical_feature_names],
        away_df[id_cols + technical_feature_names],
        on='game_id',
        suffixes=('_home', '_away')
    )
    
    # 3. Matchup Difference Features
    print("Calculating matchup differences...")
    diff_feats_dict = {}
    for stat in core_stats:
        h_col = f'{stat}_season_avg_home'
        a_col = f'{stat}_season_avg_away'
        diff_feats_dict[f'{stat}_diff_season'] = matchups[h_col] - matchups[a_col]
        
        h_col_10 = f'{stat}_mean_10_home'
        a_col_10 = f'{stat}_mean_10_away'
        diff_feats_dict[f'{stat}_diff_10'] = matchups[h_col_10] - matchups[a_col_10]
        
    df_diffs = pd.DataFrame(diff_feats_dict, index=matchups.index)
    matchups = pd.concat([matchups, df_diffs], axis=1)
    
    diff_feature_names = df_diffs.columns.tolist()

    # 4. Targets
    matchups['target_win'] = (matchups['team_score_home'] > matchups['team_score_away']).astype(int)
    matchups['target_total'] = matchups['team_score_home'] + matchups['team_score_away']
    
    return matchups, technical_feature_names, diff_feature_names

def train_v2():
    print("Loading data...")
    try:
        raw_df = load_data()
    except Exception as e:
        print(f"Error loading data: {e}")
        return
    
    matchups, team_feats, diff_feats = engineer_features_v2(raw_df)
    print(f"Paired Matchups: {len(matchups)}")
    
    if len(matchups) == 0:
        print("No paired matchups found. Check cleaning logic.")
        return
        
    all_home_feats = [f'{f}_home' for f in team_feats]
    all_away_feats = [f'{f}_away' for f in team_feats]
    final_features = all_home_feats + all_away_feats + diff_feats
    
    # Filter for valid data
    matchups = matchups.dropna(subset=final_features)
    
    matchups = matchups.sort_values('game_date_home')
    split_idx = int(len(matchups) * 0.85)
    
    X = matchups[final_features]
    y_ml = matchups['target_win']
    y_ou = matchups['target_total']
    
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_ml_train, y_ml_test = y_ml.iloc[:split_idx], y_ml.iloc[split_idx:]
    y_ou_train, y_ou_test = y_ou.iloc[:split_idx], y_ou.iloc[split_idx:]
    
    # --- 1. Moneyline Classifier (v2) ---
    print("\n--- Training Moneyline Classifier (v2) ---")
    ml_model = xgb.XGBClassifier(
        objective='binary:logistic',
        n_estimators=1000,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42
    )
    ml_model.fit(X_train, y_ml_train, eval_set=[(X_test, y_ml_test)], verbose=100)
    
    y_ml_pred = ml_model.predict(X_test)
    ml_acc = accuracy_score(y_ml_test, y_ml_pred)
    print(f"ML Accuracy: {ml_acc:.4f}")
    
    # --- 2. Over/Under Regressor (v2) ---
    print("\n--- Training Over/Under Regressor (v2) ---")
    ou_model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=1000,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42
    )
    ou_model.fit(X_train, y_ou_train, eval_set=[(X_test, y_ou_test)], verbose=100)
    
    y_ou_pred = ou_model.predict(X_test)
    ou_mae = mean_absolute_error(y_ou_test, y_ou_pred)
    ou_r2 = r2_score(y_ou_test, y_ou_pred)
    print(f"O/U MAE: {ou_mae:.4f}")
    print(f"O/U R2: {ou_r2:.4f}")
    
    # Save Models
    joblib.dump(ml_model, MODEL_DIR / "ncaab_ml_v2.joblib")
    joblib.dump(ou_model, MODEL_DIR / "ncaab_ou_v2.joblib")
    joblib.dump(final_features, MODEL_DIR / "ncaab_features_v2.joblib")
    
    print("\nModels and Features list saved successfully.")

if __name__ == "__main__":
    train_v2()
