import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def verify_teams():
    print("Verifying Team Counts...")
    
    # Check Cup Series Teams
    url = f"{BASE_URL}/nascar/teams?series=cup"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        teams = resp.json()
        print(f"Cup Series Teams Count: {len(teams)}")
        # print(f"Teams: {teams}")
        
        if len(teams) < 15:
            print("ERROR: Too few Cup Series teams found. Expected > 15.")
            return False
        
        print("SUCCESS: Cup Series team count looks reasonable.")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = verify_teams()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
