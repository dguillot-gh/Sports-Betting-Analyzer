import subprocess
import json
import pandas as pd

def get_live_headers():
    url = "https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season=2024-25&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    # Headers for curl
    headers = [
        '-H', 'Accept: */*',
        '-H', 'Origin: https://www.nba.com',
        '-H', 'Referer: https://www.nba.com/',
        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    
    print("Fetching live headers via curl...")
    try:
        result = subprocess.run(['curl', '-s', url] + headers, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"Curl error: {result.stderr}")
            return
        
        data = json.loads(result.stdout)
        headers_list = data['resultSets'][0]['headers']
        print(f"\nTotal Live Columns: {len(headers_list)}")
        print(f"Headers: {headers_list}")
        
        # Simulate dropping ID and Name
        cols = [h for h in headers_list if h not in ['TEAM_ID', 'TEAM_NAME']]
        print(f"\nColumns after dropping ID/Name: {len(cols)}")
        
        # Check slice of 52
        slice_52 = cols[:52]
        print(f"Slice [:52]: {slice_52}")
        
        if 'PLUS_MINUS_RANK' in slice_52:
            print(f"PLUS_MINUS_RANK is at index {slice_52.index('PLUS_MINUS_RANK')} in slice")
            if slice_52[-1] == 'PLUS_MINUS_RANK':
                print("PERFECT MATCH: PLUS_MINUS_RANK is the last column in the slice.")
            else:
                print(f"MISMATCH: Slice ends with {slice_52[-1]}, but should end with PLUS_MINUS_RANK")
        else:
            print("CRITICAL MISMATCH: PLUS_MINUS_RANK NOT IN SLICE!")
            if 'PLUS_MINUS_RANK' in cols:
                print(f"PLUS_MINUS_RANK is actually at index {cols.index('PLUS_MINUS_RANK')} in dropped list")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_live_headers()
