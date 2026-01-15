import sys
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
# import mlflow
# import mlflow.xgboost
from pathlib import Path
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, log_loss

# Setup Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "ncaab"
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

def load_data():
    """Load and prep data"""
    path = DATA_DIR / "ncaab_team_box_history.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Data not found at {path}")
    
    df = pd.read_parquet(path)
    
    # Check for required columns
    required = ['game_id', 'team_display_name', 'team_score', 'opponent_team_score', 'game_date']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
        
    return df

def engineer_features(df):
    """Create matchups and features"""
    print("Engineering features...")
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values(['team_display_name', 'game_date'])
    
    # 1. Rolling Stats
    features = ['team_score', 'opponent_team_score', 'field_goals_made', 'field_goals_attempted', 
                'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made', 
                'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 
                'turnovers', 'steals', 'blocks', 'personal_fouls']
    
    # Filter to only columns that exist
    features = [f for f in features if f in df.columns]
    
    for f in features:
        df[f'{f}_roll5'] = df.groupby('team_display_name')[f].shift(1).rolling(5).mean()
        df[f'{f}_roll10'] = df.groupby('team_display_name')[f].shift(1).rolling(10).mean()
        
    # 2. Win/Loss Target
    df['win'] = (df['team_score'] > df['opponent_team_score']).astype(int)
    
    # 3. Create Matchups (Self vs Opponent)
    # We need to join the game on itself to get Home vs Away stats
    # For simplicity in this v1, we will just use the team's rolling stats vs the opponent's rolling stats
    # if we can find the opponent's row.
    
    # Since the dataset is team-centric, we need to self-join on game_id
    # But first, let's drop rows with NaNs (early season games)
    df_clean = df.dropna()
    
    # Merge on game_id
    # This creates a row for every team-game, joined with opponent data
    # We need to ensure we don't duplicate (A vs B, B vs A) or carefully handle it
    # We want Training Data: "Home Team Stats" + "Away Team Stats" -> Home Win?
    
    # Assuming 'home_away' column exists or we infer it. 
    # If not, random assignment or double training (A vs B, B vs A)
    # Let's check columns for 'location'
    if 'location' in df.columns:
        is_home = df['location'].str.contains('Home', case=False) | (df['location'] == 'H')
        df_clean['is_home'] = is_home.astype(int)
    else:
        # Fallback: Randomly assign if not present, but for now we skip location if missing
        df_clean['is_home'] = 0 
    
    matchup_cols = ['game_id', 'team_display_name', 'win', 'is_home'] + [c for c in df_clean.columns if 'roll' in c]
    
    matchups = df_clean[matchup_cols]
    
    # Self-join to get Opponent Stats
    # We need to ensure we pair the right rows. 
    # If game_id is unique per game, there should be exactly 2 rows per game_id.
    
    # Group by game_id
    # We'll take the first row as "Team A" and second as "Team B"
    # Ideally we respect Home/Away
    
    processed_games = []
    
    for gid, group in matchups.groupby('game_id'):
        if len(group) != 2:
            continue
            
        row1 = group.iloc[0]
        row2 = group.iloc[1]
        
        # Decide who is "Home" (Team 1) in our feature set
        # If is_home is available, use it.
        if row1['is_home'] == 1:
            home, away = row1, row2
        elif row2['is_home'] == 1:
            home, away = row2, row1
        else:
            # Default to row1 as "Home" for the sake of the model
            home, away = row1, row2
            
        # Build features
        # format: home_stats... away_stats...
        feat_dict = {}
        
        # Target
        feat_dict['target_win'] = home['win']
        feat_dict['home_team'] = home['team_display_name']
        feat_dict['away_team'] = away['team_display_name']
        feat_dict['game_date'] = df.loc[home.name]['game_date']
        
        for col in [c for c in home.index if 'roll' in c]:
            feat_dict[f'home_{col}'] = home[col]
            feat_dict[f'away_{col}'] = away[col]
            
        processed_games.append(feat_dict)
        
    final_df = pd.DataFrame(processed_games)
    return final_df

def train():
    # mlflow.set_tracking_uri("file:./mlruns")
    # mlflow.set_experiment("NCAAB_Training")
    
    # with mlflow.start_run():
    if True:
        print("Loading data...")
        raw_df = load_data()
        
        print("Engineering features...")
        train_df = engineer_features(raw_df)
        print(f"Training set size: {len(train_df)}")
        
        # Split Data
        # Sort by date to avoid leakage (Train on past, test on future)
        train_df = train_df.sort_values('game_date')
        
        # Drop rows with NaNs in features
        features = [c for c in train_df.columns if 'roll' in c]
        train_df = train_df.dropna(subset=features)
        
        X = train_df[features]
        y = train_df['target_win']
        
        # Time-based split (80/20)
        split_idx = int(len(train_df) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
        
        print(f"Features: {len(features)}")
        
        # Train XGBoost
        model = xgb.XGBClassifier(
            objective='binary:logistic',
            n_estimators=100,
            learning_rate=0.1,
            max_depth=3,
            eval_metric='logloss'
        )
        
        model.fit(X_train, y_train)
        
        # Evaluate
        preds = model.predict(X_test)
        probs = model.predict_proba(X_test)[:, 1]
        
        acc = accuracy_score(y_test, preds)
        ll = log_loss(y_test, probs)
        
        print(f"Accuracy: {acc:.4f}")
        print(f"Log Loss: {ll:.4f}")
        
        # Log to MLflow
        # mlflow.log_metric("accuracy", acc)
        # mlflow.log_metric("log_loss", ll)
        # mlflow.xgboost.log_model(model, "model")
        
        # Save locally
        save_path = MODEL_DIR / "ncaab_xgb_v1.joblib"
        joblib.dump(model, save_path)
        print(f"Model saved to {save_path}")

if __name__ == "__main__":
    train()
