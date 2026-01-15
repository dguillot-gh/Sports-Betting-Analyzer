
import pandas as pd
import xgboost as xgb
import joblib
import numpy as np
from pathlib import Path
from datetime import datetime
import json

# Setup Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "ncaab"
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "ncaab_xgb_v1.joblib"

def load_and_prep_data():
    """
    Reuses logic from train_ncaab_model.py to prep data for backtesting.
    Ideally this logic is shared, but for now we duplicate to ensure 
    backtest runs on the exact same feature set structure.
    """
    path = DATA_DIR / "ncaab_team_box_history.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Data not found at {path}")
    
    df = pd.read_parquet(path)
    
    # Simple feature engineering (Must match training exactly)
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values(['team_display_name', 'game_date'])
    
    features = ['team_score', 'opponent_team_score', 'field_goals_made', 'field_goals_attempted', 
                'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made', 
                'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 
                'turnovers', 'steals', 'blocks', 'personal_fouls']
    
    # Filter to only columns that exist
    features = [f for f in features if f in df.columns]
    
    for f in features:
        df[f'{f}_roll5'] = df.groupby('team_display_name')[f].shift(1).rolling(5).mean()
        df[f'{f}_roll10'] = df.groupby('team_display_name')[f].shift(1).rolling(10).mean()
        
    df['win'] = (df['team_score'] > df['opponent_team_score']).astype(int)
    
    # Matchup Creation
    if 'location' in df.columns:
        is_home = df['location'].str.contains('Home', case=False) | (df['location'] == 'H')
        df['is_home'] = is_home.astype(int)
    else:
        df['is_home'] = 0 
        
    matchup_cols = ['game_id', 'team_display_name', 'win', 'is_home', 'game_date', 'team_score', 'opponent_team_score'] + [c for c in df.columns if 'roll' in c]
    df_clean = df.dropna(subset=matchup_cols)
    matchups = df_clean[matchup_cols]
    
    processed_games = []
    
    for gid, group in matchups.groupby('game_id'):
        if len(group) != 2:
            continue
            
        row1 = group.iloc[0]
        row2 = group.iloc[1]
        
        # Determine Home/Away
        if row1['is_home'] == 1:
            home, away = row1, row2
        elif row2['is_home'] == 1:
            home, away = row2, row1
        else:
            home, away = row1, row2
            
        feat_dict = {}
        feat_dict['game_id'] = gid
        feat_dict['game_date'] = df.loc[home.name]['game_date']
        feat_dict['home_team'] = home['team_display_name']
        feat_dict['away_team'] = away['team_display_name']
        feat_dict['home_score'] = home['team_score']
        feat_dict['away_score'] = away['team_score']
        feat_dict['target_home_win'] = home['win']
        
        for col in [c for c in home.index if 'roll' in c]:
            feat_dict[f'home_{col}'] = home[col]
            feat_dict[f'away_{col}'] = away[col]
            
        processed_games.append(feat_dict)
        
    return pd.DataFrame(processed_games)

def run_backtest(season_filter=None):
    if not MODEL_PATH.exists():
        return {"error": "Model not found. Train usage first."}
    
    model = joblib.load(MODEL_PATH)
    data = load_and_prep_data()
    
    # Filter by season if needed (assuming date range)
    if season_filter:
        # e.g., Filter for 2023-2024 season (Nov 2023 - April 2024)
        start_date = pd.Timestamp("2023-11-01")
        data = data[data['game_date'] >= start_date]

    if data.empty:
        return {"error": "No data available for backtest."}

    # Prepare features for prediction
    feature_cols = [c for c in data.columns if 'roll' in c]
    X = data[feature_cols]
    y_true = data['target_home_win']
    
    # Predict
    probs = model.predict_proba(X)[:, 1]
    data['home_win_prob'] = probs
    
    # Apply Betting Strategy
    # Strategy: Bet Home if Prob > 55%, Bet Away if Prob < 45% (implied Home Prob < 45%)
    # Assuming -110 odds (implied prob 52.38%)
    
    results = []
    bankroll = 100.0
    units_won = 0.0
    wins = 0
    losses = 0
    skipped = 0
    
    # For JSON serialization
    daily_pnl = {}
    
    for i, row in data.iterrows():
        prob = row['home_win_prob']
        actual_win = row['target_home_win']
        
        bet_pick = None
        
        # Simple threshold strategy
        if prob > 0.55:
            bet_pick = 1 # Bet Home
        elif prob < 0.45:
            bet_pick = 0 # Bet Away
        else:
            skipped += 1
            continue
            
        # Check result
        # Bet 1.1 to win 1.0 (Standard -110)
        risk = 1.1
        reward = 1.0
        
        is_hit = (bet_pick == actual_win)
        
        pnl = 0
        if is_hit:
            pnl = reward
            wins += 1
        else:
            pnl = -risk
            losses += 1
            
        units_won += pnl
        
        date_str = row['game_date'].strftime('%Y-%m-%d')
        if date_str not in daily_pnl:
            daily_pnl[date_str] = 0
        daily_pnl[date_str] += pnl
        
    total_bets = wins + losses
    roi = (units_won / (total_bets * 1.1)) * 100 if total_bets > 0 else 0
    
    report = {
        "total_games": len(data),
        "bets_placed": total_bets,
        "wins": wins,
        "losses": losses,
        "hit_rate": round(wins / total_bets * 100, 1) if total_bets > 0 else 0,
        "units_won": round(units_won, 2),
        "roi_percent": round(roi, 2),
        "daily_pnl": daily_pnl
    }
    
    return report

if __name__ == "__main__":
    rep = run_backtest(season_filter=True)
    print(json.dumps(rep, indent=2))
