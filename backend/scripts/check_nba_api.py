import asyncio
import aiohttp

async def check_nba_api():
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Origin": "https://www.nba.com",
        "Priority": "u=3, i",
        "Referer": "https://www.nba.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }
    
    url = (
        "https://stats.nba.com/stats/leaguedashteamstats?"
        "Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&"
        "ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&"
        "OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&"
        "PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season=2024-25&"
        "SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&"
        "TeamID=0&TwoWay=0&VsConference=&VsDivision="
    )
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=30) as response:
            data = await response.json()
            
    result_sets = data.get('resultSets', [])
    if result_sets:
        headers_list = result_sets[0].get('headers', [])
        print("=== Current NBA API columns ===")
        for i, col in enumerate(headers_list):
            print(f'{i}: {col}')
        print(f'\nTotal columns from API: {len(headers_list)}')

asyncio.run(check_nba_api())
