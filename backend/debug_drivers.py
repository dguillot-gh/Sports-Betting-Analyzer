import sys
from pathlib import Path
import pandas as pd

# Add src to path
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / 'src'))

from sport_factory import SportFactory

def debug_drivers():
    print("Debugging Drivers via SportFactory...")
    
    # Simulate API call: /nascar/drivers?series=cup&team=Joe%20Gibbs%20Racing
    sport_name = 'nascar'
    series = 'cup'
    
    print(f"Creating sport for {sport_name} series={series}")
    sport, label = SportFactory.get_sport(sport_name, series)
    print(f"Model Label: {label}")
    
    # Check Active Drivers
    if hasattr(sport, '_active_drivers'):
        print(f"\nActive Drivers Count: {len(sport._active_drivers)}")
        print(f"Denny Hamlin in active: {'Denny Hamlin' in sport._active_drivers}")
    else:
        print("\nWARNING: _active_drivers not found.")

    teams_to_check = ["Joe Gibbs Racing", "Hendrick Motorsports"]
    
    for team_name in teams_to_check:
        print(f"\n--- Checking Team: {team_name} ---")
        
        drivers = sport.get_drivers(team_id=team_name)
        print(f"Drivers returned: {drivers}")
        
        if team_name == "Joe Gibbs Racing":
            if "Denny Hamlin" not in drivers:
                print("ERROR: Denny Hamlin MISSING!")
            else:
                print("SUCCESS: Denny Hamlin found.")
                
        if team_name == "Hendrick Motorsports":
            if "Kyle Larson" not in drivers:
                print("ERROR: Kyle Larson MISSING!")
            else:
                print("SUCCESS: Kyle Larson found.")

if __name__ == "__main__":
    debug_drivers()
