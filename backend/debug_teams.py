import sys
from pathlib import Path
import pandas as pd

# Add src to path
sys.path.append(str(Path.cwd() / 'src'))

from sport_factory import SportFactory

def debug_teams():
    print("--- Testing Cup Series ---")
    sport_cup, label_cup = SportFactory.get_sport('nascar', 'cup')
    teams_cup = sport_cup.get_teams()
    print(f"Cup Teams: {len(teams_cup)}")
    print(f"Sample: {teams_cup[:5]}")
    
    if "Hendrick Motorsports" in teams_cup:
        print("SUCCESS: 'Hendrick Motorsports' found in Cup.")
    else:
        print("ERROR: 'Hendrick Motorsports' NOT found in Cup!")
        
    if "JR Motorsports" in teams_cup:
        print("WARNING: 'JR Motorsports' (Xfinity) found in Cup list!")
    else:
        print("SUCCESS: 'JR Motorsports' correctly excluded from Cup.")

    print("\n--- Testing Xfinity Series ---")
    sport_xfinity, label_xfinity = SportFactory.get_sport('nascar', 'xfinity')
    teams_xfinity = sport_xfinity.get_teams()
    print(f"Xfinity Teams: {len(teams_xfinity)}")
    print(f"Sample: {teams_xfinity[:5]}")
    
    if "JR Motorsports" in teams_xfinity:
        print("SUCCESS: 'JR Motorsports' found in Xfinity.")
    else:
        print("ERROR: 'JR Motorsports' NOT found in Xfinity!")
        
    if "Hendrick Motorsports" in teams_xfinity:
        print("WARNING: 'Hendrick Motorsports' (Cup) found in Xfinity list!")
    else:
        print("SUCCESS: 'Hendrick Motorsports' correctly excluded from Xfinity.")

if __name__ == "__main__":
    debug_teams()
