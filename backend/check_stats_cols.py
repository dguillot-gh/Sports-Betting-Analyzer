import pandas as pd
import aiohttp
import asyncio
import sqlite3
import os

async def check_cols():
    # 1. LIVE NBA COLUMNS
    url = 'https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season=2024-25&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision='
    headers = {'Accept': '*/*', 'Origin': 'https://www.nba.com', 'Referer': 'https://www.nba.com/', 'User-Agent': 'Mozilla/5.0'}
    
    print('Fetching Live NBA Stats Columns...')
    live_cols = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                data = await resp.json()
                live_cols = data['resultSets'][0]['headers']
        print(f'Received {len(live_cols)} columns from API')
    except Exception as e:
        print(f'API Fetch Failed: {e}')
        # Fallback to local cache if possible or mock
        return

    db_path = r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Data\dataset.sqlite'
    expected_cols = []
    if os.path.exists(db_path):
        print('\nFetching Expected Training Columns from DB...')
        with sqlite3.connect(db_path) as con:
            df = pd.read_sql_query('SELECT * FROM "dataset_2012-26" LIMIT 1', con)
            expected_cols = list(df.columns)
            print(f'Training dataset has {len(expected_cols)} columns')
    else:
        print('\nERROR: Training database not found')
        return

    # 3. COMPARE
    # Pre-process live columns as adapter does (drop ID/Name)
    processed_live = [c for c in live_cols if c not in ['TEAM_ID', 'TEAM_NAME']]
    
    # Pre-process expected columns (Training data has roughly 116 cols)
    # It contains [Home Stats ... Away Stats ... OU/Rest ...]
    # We want to identify the Home Stats block.
    # We can try to align the first 10 columns.
    
    print(f'\n--- Column Comparison ---\n')
    
    print(f'Live (First 15 excluding ID/Name):')
    print(processed_live[:15])
    
    print(f'\nExpected (First 15 from DB):')
    print(expected_cols[:15])
    
    if processed_live[:15] == expected_cols[:15]:
        print('\nMatch: First 15 columns match exactly.')
    else:
        print('\nMISMATCH DETECTED!')
        # Print diff
        for i in range(min(len(processed_live), len(expected_cols), 30)):
            l = processed_live[i]
            e = expected_cols[i]
            if l != e:
                print(f'  Index {i}: Live="{l}" vs Expected="{e}"')

asyncio.run(check_cols())
