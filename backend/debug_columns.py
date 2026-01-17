import asyncio
import pandas as pd
import aiohttp
from scripts.kyleskom_adapter import KyleskomPredictor

async def check():
    p = KyleskomPredictor()
    await p.fetch_data_from_nba_api()
    if p.df is not None:
        print(f"Total columns: {len(p.df.columns)}")
        print(f"Columns: {list(p.df.columns)}")
        
        # Test the drop
        h_stats = p.df.iloc[0].drop(['TEAM_ID', 'TEAM_NAME'], errors='ignore')
        print(f"Stats count after basic drop: {len(h_stats)}")
        
        # Identify unexpected cols
        expected_last = 'PLUS_MINUS_RANK'
        if expected_last in h_stats.index:
            last_idx = h_stats.index.get_loc(expected_last)
            print(f"Index of {expected_last}: {last_idx}")
            if last_idx == 51:
                print("SUCCESS: exactly 52 columns would be used if we sliced up to PLUS_MINUS_RANK")
            else:
                print(f"WARNING: PLUS_MINUS_RANK is at index {last_idx}, expected 51")
        else:
            print("ERROR: PLUS_MINUS_RANK not found in columns!")

asyncio.run(check())
