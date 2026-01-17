import pandas as pd
import requests
from datetime import datetime

# API Headers
NBA_API_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def verify_ranks():
    now = datetime.now()
    season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
    url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=Y&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    resp = requests.get(url, headers=NBA_API_HEADERS)
    data = resp.json()
    rows = result_sets = data.get('resultSets', [])[0]['rowSet']
    headers = data.get('resultSets', [])[0]['headers']
    df = pd.DataFrame(data=rows, columns=headers)
    
    rank_cols = [c for c in df.columns if 'RANK' in c]
    print(f"Rank Columns: {len(rank_cols)}")
    
    # Check values for first row
    row0 = df.iloc[0]
    print(f"Team: {row0['TEAM_NAME']}")
    for rc in rank_cols[:5]:
        print(f"{rc}: {row0[rc]}")
        
    # Check if any NaN
    nans = df[rank_cols].isna().sum().sum()
    print(f"Total NaNs in Rank Cols: {nans}")

if __name__ == "__main__":
    verify_ranks()
