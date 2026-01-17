import requests
import pandas as pd
import json

NBA_API_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def check_nba_api(rank='Y'):
    url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank={rank}&Season=2024-25&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    print(f"Fetching NBA API with Rank={rank}...")
    response = requests.get(url, headers=NBA_API_HEADERS, timeout=30)
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return
    
    data = response.json()
    headers = data['resultSets'][0]['headers']
    rows = data['resultSets'][0]['rowSet']
    
    df = pd.DataFrame(rows, columns=headers)
    print(f"\nTotal Columns: {len(df.columns)}")
    print(f"Columns: {headers}")
    
    # Drop TEAM_ID, TEAM_NAME (as kyleskom_adapter does)
    df_dropped = df.drop(['TEAM_ID', 'TEAM_NAME'], axis=1, errors='ignore')
    print(f"Columns after dropping ID/Name: {len(df_dropped.columns)}")
    
    # Check if PLUS_MINUS_RANK is at index 51 (so slice :52 includes it)
    if 'PLUS_MINUS_RANK' in df_dropped.columns:
        idx = df_dropped.columns.get_loc('PLUS_MINUS_RANK')
        print(f"PLUS_MINUS_RANK index: {idx}")
        print(f"Columns in slice [:52]: {list(df_dropped.columns[:52])}")
        print(f"Is PLUS_MINUS_RANK in slice? {'PLUS_MINUS_RANK' in df_dropped.columns[:52]}")

if __name__ == "__main__":
    check_nba_api(rank='Y')
    print("\n" + "="*50 + "\n")
    check_nba_api(rank='N')
