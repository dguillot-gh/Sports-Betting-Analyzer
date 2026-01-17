import requests
import json
from datetime import datetime

headers = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'Connection': 'keep-alive',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}

def test_api():
    print("Testing NBA API with Rank=N...")
    
    now = datetime.now()
    season = f"{now.year}-{str(now.year + 1)[2:]}" if now.month >= 10 else f"{now.year - 1}-{str(now.year)[2:]}"
    print(f"Season: {season}")
    
    url = f"https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season={season}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="
    
    print(f"URL: {url}")
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            result_sets = data.get('resultSets', [])
            if result_sets:
                headers_list = result_sets[0]['headers']
                print(f"Columns returned: {len(headers_list)}")
                print(f"First 10: {headers_list[:10]}")
                
                # Check for Rank
                ranks = [h for h in headers_list if 'RANK' in h]
                print(f"Rank Columns Found: {len(ranks)}")
                if ranks:
                    print(f"Sample: {ranks[:5]}")
            else:
                print("No resultSets found.")
                print(data)
        else:
            print(f"Error Response: {resp.text[:500]}")
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_api()
