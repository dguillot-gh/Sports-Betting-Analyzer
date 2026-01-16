"""
Verify the exact column order in kyleskom prediction vs training
"""
import pandas as pd
import aiohttp
import asyncio

async def check():
    url = 'https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season=2024-25&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision='
    headers = {'Accept': '*/*', 'Origin': 'https://www.nba.com', 'Referer': 'https://www.nba.com/', 'User-Agent': 'Mozilla/5.0'}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=10) as resp:
            data = await resp.json()
            headers_list = data['resultSets'][0]['headers']
            print(f'Total columns from NBA API: {len(headers_list)}')
            
            # Simulate main.py processing
            df = pd.DataFrame(data=data['resultSets'][0]['rowSet'], columns=headers_list)
            
            # home + away stats (like kyleskom main.py)
            home = df.iloc[0]
            away = df.iloc[1].rename(lambda x: f'{x}.1')
            stats = pd.concat([home, away])
            stats['Days-Rest-Home'] = 2
            stats['Days-Rest-Away'] = 2
            
            # This is what main.py does - drop TEAM_ID, TEAM_NAME
            frame_ml = pd.DataFrame([stats]).drop(columns=['TEAM_ID', 'TEAM_NAME'], errors='ignore')
            print(f'\nframe_ml (ML model input):')
            print(f'  Total columns: {len(frame_ml.columns)}')
            print(f'  Last 5 columns: {list(frame_ml.columns[-5:])}')
            
            # This is what xgb_runner does for O/U
            frame_uo = frame_ml.copy()
            frame_uo['OU'] = 225.0
            print(f'\nframe_uo (O/U model input - kyleskom prediction):')
            print(f'  Total columns: {len(frame_uo.columns)}')
            print(f'  Last 5 columns: {list(frame_uo.columns[-5:])}')
            ou_index = list(frame_uo.columns).index('OU')
            print(f'  OU column is at index: {ou_index}')
            
            # Compare to training order from Create_Games.py
            # Training adds: [Stats, Stats.1, Score, Home-Team-Win, OU, OU-Cover, Days-Rest-Home, Days-Rest-Away]
            # Then XGBoost_Model_UO.py drops: Score, Home-Team-Win, TEAM_NAME, Date, TEAM_NAME.1, Date.1, OU-Cover
            # So training order after drops: [Stats(52), Stats.1(52), OU, Days-Rest-Home, Days-Rest-Away]
            print(f'\n=== TRAINING ORDER (from Create_Games.py) ===')
            print(f'After drops: [Stats(52), Stats.1(52), OU, Days-Rest-Home, Days-Rest-Away]')
            print(f'OU should be at index: 104')
            
            print(f'\n=== PREDICTION ORDER (from XGBoost_Runner.py) ===')
            print(f'frame_uo columns: [Stats(52), Stats.1(52), Days-Rest-Home, Days-Rest-Away, OU]')
            print(f'OU is at index: {ou_index}')
            
            if ou_index == 104:
                print(f'\n✓ MATCH: Prediction order matches training order')
            else:
                print(f'\n✗ MISMATCH: Training expects OU at 104, but prediction puts it at {ou_index}')

asyncio.run(check())
