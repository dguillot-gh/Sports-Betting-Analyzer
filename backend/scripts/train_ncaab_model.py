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
    
    # --- Data Cleaning ---
    # Fix for potential stringified lists in Parquet
    for col in df.columns:
        try:
            series_str = df[col].astype(str)
            if series_str.str.contains(r'\[|\]', regex=True).any():
                print(f"Cleaning corrupted column: {col}")
                df[col] = series_str.str.replace(r'[\[\]\'\"]', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            elif df[col].dtype == 'object' and col not in ['game_id', 'team_display_name', 'opponent_team_display_name', 'game_date', 'season']:
                 # Try a soft conversion for unknown numeric columns
                 df[col] = pd.to_numeric(df[col], errors='ignore')
        except: pass
        
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
    
    # 0. Calculated Base Stats
    # Possessions = FGA - ORB + TO + 0.44 * FTA
    df['possessions'] = (
        df['field_goals_attempted'] - 
        df['offensive_rebounds'] + 
        df['turnovers'] + 
        (0.44 * df['free_throws_attempted'])
    )
    df['off_eff'] = (df['team_score'] / df['possessions']) * 100
    df['def_eff'] = (df['opponent_team_score'] / df['possessions']) * 100
    
    # 0.5 Calculate Win Pct and OWP (Strength of Schedule)
    print("Calculating Strength of Schedule (SOS)...")
    # First, simple win % per season for each team
    df['is_win'] = (df['team_score'] > df['opponent_team_score']).astype(int)
    team_season_win_pct = df.groupby(['season', 'team_display_name'])['is_win'].expanding().mean().reset_index(level=[0,1], drop=True)
    df['win_pct'] = team_season_win_pct
    
    # OWP (Opponent Win %)
    matchup_map = df[['game_id', 'team_display_name', 'win_pct']].rename(columns={'team_display_name': 'opponent_team_display_name', 'win_pct': 'opp_win_pct'})
    df = pd.merge(df, matchup_map, on=['game_id', 'opponent_team_display_name'], how='left')
    df['owp'] = df.groupby(['season', 'team_display_name'])['opp_win_pct'].expanding().mean().reset_index(level=[0,1], drop=True)
    
    # OOWP (Opponent's Opponent Win %)
    matchup_map_owp = df[['game_id', 'team_display_name', 'owp']].rename(columns={'team_display_name': 'opponent_team_display_name', 'owp': 'opp_owp'})
    df = pd.merge(df, matchup_map_owp, on=['game_id', 'opponent_team_display_name'], how='left')
    df['oowp'] = df.groupby(['season', 'team_display_name'])['opp_owp'].expanding().mean().reset_index(level=[0,1], drop=True)

    # Core stats to aggregate
    core_stats = [
        'team_score', 'opponent_team_score', 'field_goal_pct', 'three_point_field_goal_pct',
        'free_throw_pct', 'total_rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'fouls',
        'possessions', 'off_eff', 'def_eff', 'win_pct', 'owp', 'oowp'
    ]
    
    # Ensure columns exist
    core_stats = [s for s in core_stats if s in df.columns]
    
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

    # 4. Integrate Torvik Data (if available)
    print("Integrating Torvik T-Rank data...")
    torvik_path = DATA_DIR / "torvik_ratings.parquet"
    if torvik_path.exists():
        torvik_df = pd.read_parquet(torvik_path)
        # Normalize names for join
        def normalize(n):
            return str(n).lower().replace(" state", " st").replace(" university", "").strip()
            
        torvik_df['team_norm'] = torvik_df['team'].apply(normalize)
        matchups['team_home_norm'] = matchups['team_display_name_home'].apply(normalize)
        matchups['team_away_norm'] = matchups['team_display_name_away'].apply(normalize)
        
        # Merge Home
        t_home = torvik_df[['team_norm', 'adj_o', 'adj_d', 'adj_t']].rename(columns={
            'adj_o': 'torvik_adj_o_home', 'adj_d': 'torvik_adj_d_home', 'adj_t': 'torvik_tempo_home'
        })
        matchups = pd.merge(matchups, t_home, left_on='team_home_norm', right_on='team_norm', how='left')
        
        # Merge Away
        t_away = torvik_df[['team_norm', 'adj_o', 'adj_d', 'adj_t']].rename(columns={
            'adj_o': 'torvik_adj_o_away', 'adj_d': 'torvik_adj_d_away', 'adj_t': 'torvik_tempo_away'
        })
        matchups = pd.merge(matchups, t_away, left_on='team_away_norm', right_on='team_norm', how='left')
        
        # Fill missing historical Torvik data with our calculated proxies
        # torvik_adj_o ~= off_eff_season_avg
        # torvik_tempo ~= possessions_season_avg
        for side in ['home', 'away']:
            matchups[f'torvik_adj_o_{side}'] = matchups[f'torvik_adj_o_{side}'].fillna(matchups[f'off_eff_season_avg_{side}'])
            matchups[f'torvik_adj_d_{side}'] = matchups[f'torvik_adj_d_{side}'].fillna(matchups[f'def_eff_season_avg_{side}'])
            matchups[f'torvik_tempo_{side}'] = matchups[f'torvik_tempo_{side}'].fillna(matchups[f'possessions_season_avg_{side}'])
            
        diff_feature_names.extend([
            'torvik_adj_o_home', 'torvik_adj_d_home', 'torvik_tempo_home',
            'torvik_adj_o_away', 'torvik_adj_d_away', 'torvik_tempo_away'
        ])
    else:
        print("Torvik data not found. Skipping integration.")

    # 5. Targets
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
    print(f"Total Features: {len(final_features)}")
    sos_feats = [f for f in final_features if 'owp' in f or 'oowp' in f or 'win_pct' in f]
    print(f"SOS Features included: {len(sos_feats)}")
    if sos_feats:
        print(f"Sample SOS features: {sos_feats[:5]}")
    
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
