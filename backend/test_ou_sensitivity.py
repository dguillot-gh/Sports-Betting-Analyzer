import pandas as pd
import numpy as np
import xgboost as xgb
import requests
from datetime import datetime
from pathlib import Path
import joblib

# Paths
BASE_DIR = Path("scripts/nba_ml_reference")
MODELS_DIR = BASE_DIR / "Models" / "XGBoost_Models"

# API Headers
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def load_ou_model():
    candidates = list(MODELS_DIR.glob("*UO*.json"))
    if not candidates:
        print("No models found.")
        return None
    model_path = candidates[0]
    print(f"Loading Model: {model_path.name}")
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    return booster

def fetch_live_data():
    now = datetime.now()
    season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
    url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    resp = requests.get(url, headers=NBA_API_HEADERS)
    if resp.status_code != 200:
        print("API Failed")
        return None
    
    data = resp.json()
    result_sets = data.get('resultSets', [])
    rows = result_sets[0]['rowSet']
    headers = result_sets[0]['headers']
    return pd.DataFrame(data=rows, columns=headers)

def run_test():
    model = load_ou_model()
    if not model: return
    
    df = fetch_live_data()
    if df is None: return
    
    # Pick a game (e.g. first two teams)
    h_row = df.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'])
    a_row = df.iloc[1].drop(['TEAM_ID', 'TEAM_NAME'])
    h_name = df.iloc[0]['TEAM_NAME']
    a_name = df.iloc[1]['TEAM_NAME']
    
    print(f"Matchup: {h_name} vs {a_name}")
    
    stats = pd.concat([h_row, a_row])
    base_vec = stats.values.astype(float).reshape(1, -1)
    
    print("\n--- SENSITIVITY TEST ---")
    print("Format: Line | Rest | Prob(Under) | Prob(Over) | Pick")
    
    # Test Lines
    for line in [200.0, 215.0, 225.0, 235.0, 250.0]:
        # Test Rest Days
        for rest in [0.0, 1.0, 2.0, 3.0]:
            # Construct vector
            # Append Rest
            vec_with_rest = np.append(base_vec, [[rest, rest]], axis=1)
            # Insert O/U at 104
            final_vec = np.insert(vec_with_rest, 104, line, axis=1)
            
            dmat = xgb.DMatrix(final_vec)
            probs = model.predict(dmat)
            prob_under = probs[0][0]
            prob_over = probs[0][1] if len(probs[0]) > 1 else 1.0 - prob_under
            
            pick = "OVER" if prob_over > prob_under else "UNDER"
            print(f"{line:<6} | {rest:<4} | {prob_under:.3f}       | {prob_over:.3f}      | {pick}")

if __name__ == "__main__":
    run_test()
