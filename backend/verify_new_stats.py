import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def verify_new_stats():
    print("Verifying New Stats (Laps Led, Poles, DNFs)...")
    
    driver = "Kyle Larson"
    encoded_driver = requests.utils.quote(driver)
    
    # Fetch Profile
    url = f"{BASE_URL}/nascar/profile/{encoded_driver}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        stats = data.get('stats', {})
        
        print(f"Stats for {driver}:")
        print(json.dumps(stats, indent=2))
        
        # Check for new keys
        required = ['Laps Led', 'Poles', 'DNFs']
        missing = [k for k in required if k not in stats]
        
        if missing:
            print(f"ERROR: Missing keys: {missing}")
            return False
            
        # Basic sanity check (Larson definitely has led laps and won poles)
        if stats['Laps Led'] == 0:
            print("WARNING: Laps Led is 0. Might be suspicious for Kyle Larson.")
        
        print("SUCCESS: New stats present.")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = verify_new_stats()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
