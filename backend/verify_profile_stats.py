import sys
from pathlib import Path
import json

# Add src to path
sys.path.append(str(Path.cwd() / 'src'))

from sport_factory import SportFactory

def verify_stats():
    try:
        sport, label = SportFactory.get_sport('nascar', 'cup')
        
        driver = "Chase Elliott"
        print(f"\nFetching stats for {driver}...")
        
        profile = sport.get_entity_stats(driver)
        
        print("\n--- Stats ---")
        print(json.dumps(profile['stats'], indent=2))
        
        print("\n--- History (First 2) ---")
        print(json.dumps(profile['history'][:2], indent=2))
        
        if not profile['stats']:
            print("\nERROR: Stats are empty!")
            return

        if not profile['history']:
            print("\nERROR: History is empty!")
            return
            
        print("\nSUCCESS: Profile stats retrieved successfully.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_stats()
