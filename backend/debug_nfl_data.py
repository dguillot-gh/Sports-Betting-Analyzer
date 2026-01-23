import sys
import os

# Add the current directory to path so we can import from src
sys.path.append(os.getcwd())

try:
    import nflreadpy as nfl
    import pandas as pd
    print(f"nflreadpy version: {getattr(nfl, '__version__', 'unknown')}")
except ImportError:
    print("nflreadpy NOT installed in this environment")
    sys.exit(1)

def debug_nfl():
    print("--- NFL Data Debug ---")
    
    current_year = 2026
    # NFL season corresponds to the year it started (e.g., Jan 2026 is still the 2025 season)
    # A new season's data starts appearing around July/August of that year
    active_season = current_year if datetime.now().month >= 7 else current_year - 1
    
    print(f"Current Year: {current_year}, Calculated Active Season: {active_season}")
    target_years = list(range(2020, active_season + 1))
    print(f"Target Years for modern stats: {target_years}")

    # Check schedules
    print(f"\nChecking Schedules for {target_years}...")
    try:
        schedules = nfl.load_schedules(seasons=target_years)
        if hasattr(schedules, "to_pandas"):
            schedules = schedules.to_pandas()
        
        print(f"2025 Schedules loaded: {len(schedules)} rows")
        if len(schedules) > 0:
            cols = [c for c in ['game_id', 'week', 'away_team', 'home_team', 'gameday', 'away_score', 'home_score'] if c in schedules.columns]
            print("First 5 games:")
            print(schedules[cols].head())
            
            # Check for scores
            if 'away_score' in schedules.columns:
                scored_games = schedules[schedules['away_score'].notna()]
                print(f"Games with scores: {len(scored_games)}")
        else:
            print("WARNING: No 2025 schedule data returned.")
    except Exception as e:
        print(f"Error loading schedules: {e}")

    # Check stats
    print(f"\nChecking Player Stats (Regular Season aggregates) for {target_years}...")
    try:
        stats = nfl.load_player_stats(seasons=target_years, summary_level="reg")
        if hasattr(stats, "to_pandas"):
            stats = stats.to_pandas()
        
        print(f"Stats loaded: {len(stats)} rows")
        if len(stats) > 0:
            cols = [c for c in ['player_display_name', 'recent_team', 'passing_yards', 'rushing_yards', 'season'] if c in stats.columns]
            print("Top 5 players (first 5 in list):")
            print(stats[cols].head())
            
            # Check for current season Specifically
            current_stats = stats[stats['season'] == active_season]
            print(f"Stats found for {active_season}: {len(current_stats)} rows")
        else:
            print(f"WARNING: No stats returned for {target_years}.")
    except Exception as e:
        print(f"Error loading stats: {e}")

    # Check Players
    print("\nChecking Player Directory...")
    try:
        players = nfl.load_players()
        if hasattr(players, "to_pandas"):
            players = players.to_pandas()
        print(f"Total players in directory: {len(players)}")
    except Exception as e:
        print(f"Error loading players: {e}")

if __name__ == "__main__":
    debug_nfl()
