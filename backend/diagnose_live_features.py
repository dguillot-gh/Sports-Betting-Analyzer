import pandas as pd
import numpy as np
import requests
from datetime import datetime
import json

# Headers must match what we suspect works
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def diagnose():
    print("--- STARTING LIVE DIAGNOSTIC (SYNC) ---")
    
    # 1. Fetch Data
    now = datetime.now()
    season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
    print(f"Season: {season}")
    
    url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    try:
        resp = requests.get(url, headers=NBA_API_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"API Error: {resp.status_code}")
            return
            
        data = resp.json()
        result_sets = data.get('resultSets', [])
        if not result_sets:
            print("No resultSets.")
            return
            
        rows = result_sets[0]['rowSet']
        headers = result_sets[0]['headers']
        df = pd.DataFrame(data=rows, columns=headers)
        print(f"Data Fetched. Shape: {df.shape}")
        
        print("--- LIVE API COLUMNS (First 20) ---")
        print(headers[:20])
        print("--- LIVE API COLUMNS (Middle) ---")
        print(headers[20:40])
        print("--- LIVE API COLUMNS (Contains RANK) ---")
        ranks = [h for h in headers if 'RANK' in h]
        print(ranks[:10])
        
        # 2. Simulate Pre-Processing
        # Assume first two rows are Home and Away
        h_row = df.iloc[0]
        a_row = df.iloc[1]
        
        print(f"Home Team: {h_row['TEAM_NAME']}")
        print(f"Away Team: {a_row['TEAM_NAME']}")
        
        # Drop ID and Name
        h_stats = h_row.drop(['TEAM_ID', 'TEAM_NAME'])
        a_stats = a_row.drop(['TEAM_ID', 'TEAM_NAME'])
        
        # Concat
        # Corresponding to kyleskom_adapter logic
        stats = pd.concat([h_stats, a_stats])
        
        # Add Rest
        # In adapter: stats['Days-Rest-Home'], stats['Days-Rest-Away'] = 2.0, 2.0
        # This appends to the Series
        stats['Days-Rest-Home'] = 2.0
        stats['Days-Rest-Away'] = 2.0
        
        # Reshape
        data_vec = stats.values.astype(float).reshape(1, -1)
        print(f"Vector Shape BEFORE O/U Insert: {data_vec.shape}")
        
        # Insert O/U at 104
        total_line = 225.0
        data_ou = np.insert(data_vec, 104, total_line, axis=1)
        print(f"Vector Shape AFTER O/U Insert: {data_ou.shape}")
        
        # Print Key Indices
        # Index 104 should be 225.0
        val_104 = data_ou[0][104]
        val_105 = data_ou[0][105]
        val_106 = data_ou[0][106]
        
        print(f"Value at Index 104 (Expected 225.0): {val_104}")
        print(f"Value at Index 105 (Expected 2.0/Rest): {val_105}")
        print(f"Value at Index 106 (Expected 2.0/Rest): {val_106}")
        
        # Print Feature Count Summary
        # 54 Base Columns
        # - 2 (ID/Name) = 52
        # 52 * 2 = 104
        # + 2 Rest = 106
        # + 1 O/U = 107
        
        expected_len = 107
        actual_len = data_ou.shape[1]
        
        if actual_len == expected_len:
            print("SUCCESS: Feature Count Matches Model (107).")
            
            # 4. Final Verification: Run actual prediction
            print("\n--- MODEL PREDICTION VERIFICATION ---")
            try:
                import xgboost as xgb
                from scripts.kyleskom_adapter import KyleskomPredictor
                
                kp = KyleskomPredictor()
                kp.load_models()
                
                if not kp.xgb_ou:
                    print("Error: O/U Model (xgb_ou) could not be loaded.")
                else:
                    print(f"Matchup: {h_row['TEAM_NAME']} vs {a_row['TEAM_NAME']}")
                    print("\nLINE SWEEP TEST:")
                    print("Line | Prob(Under) | Prob(Over) | Pick")
                    print("-" * 40)
                    
                    for test_line in [200.0, 215.0, 225.0, 235.0, 250.0]:
                        # Re-create vector with different line
                        vec_sweep = np.insert(data_vec, 104, test_line, axis=1)
                        res = kp._predict_probs(kp.xgb_ou, vec_sweep, kp.xgb_ou_calibrator)[0]
                        
                        p_u = float(res[0])
                        p_o = float(res[1]) if len(res) > 1 else 1.0 - p_u
                        p_pick = "OVER" if p_o > p_u else "UNDER"
                        print(f"{test_line:<4} | {p_u:.4f}      | {p_o:.4f}     | {p_pick}")
                    
                    # Also test WITHOUT calibrator if possible to see if it's skewing
                    print("\nRAW BOOSTED OUTPUT (No Calibration):")
                    raw_res = kp.xgb_ou.predict(xgb.DMatrix(data_ou))
                    print(f"Raw Output (225.0): {raw_res[0]}")
                    
            except Exception as e:
                print(f"Prediction Error: {e}")
        else:
            print(f"FAILURE: Feature Count Mismatch. Expected 107, Got {actual_len}")
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    diagnose()
