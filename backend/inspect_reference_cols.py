
import sys
import os
import pandas as pd
import numpy as np

# Add local reference to path
sys.path.append(os.path.join(os.getcwd(), 'scripts', 'nba_ml_reference'))

from src.Utils.tools import to_data_frame, get_json_data

DATA_URL = "https://stats.nba.com/stats/leaguedashteamstats?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment=&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location=&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N&Season=2024-25&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision="

def main():
    print("=== Reference Repo Column Inspection ===")
    stats_json = get_json_data(DATA_URL)
    df = to_data_frame(stats_json)
    
    print(f"Total Columns in df: {len(df.columns)}")
    print(f"Columns: {list(df.columns)}")
    
    # Simulate main.py drop
    frame_stats = df.drop(columns=['TEAM_ID', 'TEAM_NAME'])
    print(f"Columns after drop(TEAM_ID, TEAM_NAME): {len(frame_stats.columns)}")
    
    # ML Features = 2 * Stats + 2 Rest
    ml_feature_count = 2 * len(frame_stats.columns) + 2
    print(f"Expected ML Feature Count: {ml_feature_count}")
    
    # OU Features = ML Features + 1 OU
    ou_feature_count = ml_feature_count + 1
    print(f"Expected OU Feature Count (if appended): {ou_feature_count}")

if __name__ == "__main__":
    main()
