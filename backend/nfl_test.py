import nflreadpy as nfl
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)

try:
    print("Attempting to load 2025 player stats (reg level)...")
    stats = nfl.load_player_stats(seasons=[2025], summary_level='reg').to_pandas()
    print(f"Loaded {len(stats)} player-season records for 2025")
    if not stats.empty:
        print(stats[['player_display_name', 'season', 'recent_team']].head())
    
    print("\nAttempting to load 2025 schedules...")
    sched = nfl.load_schedules(seasons=[2025]).to_pandas()
    print(f"Loaded {len(sched)} games for 2025")
    if not sched.empty:
        print(sched[['game_id', 'gameday', 'home_team', 'away_team', 'result']].query('result.notnull()').tail())
except Exception as e:
    print(f"Error during test: {e}")
