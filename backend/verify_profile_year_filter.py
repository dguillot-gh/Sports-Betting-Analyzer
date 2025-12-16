import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_profile_year_filter():
    print("Testing Profile Year Filter...")
    
    # 1. Get a driver (e.g., Chase Elliott)
    driver = "Chase Elliott"
    encoded_driver = requests.utils.quote(driver)
    
    # 2. Get profile without year
    print(f"\nFetching profile for {driver} (no year)...")
    url = f"{BASE_URL}/nascar/profile/{encoded_driver}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        
        print(f"Stats: {json.dumps(data.get('stats'), indent=2)}")
        years = data.get('years', [])
        print(f"Available Years: {years}")
        
        if not years:
            print("ERROR: No years returned in profile data.")
            return False
            
        # 3. Get profile for a specific year (e.g., the most recent one)
        test_year = years[0]
        print(f"\nFetching profile for {driver} (Year: {test_year})...")
        url_year = f"{BASE_URL}/nascar/profile/{encoded_driver}?year={test_year}"
        resp_year = requests.get(url_year)
        resp_year.raise_for_status()
        data_year = resp_year.json()
        
        print(f"Stats ({test_year}): {json.dumps(data_year.get('stats'), indent=2)}")
        
        # Verify that stats are different (or at least valid)
        if data['stats']['Races'] == data_year['stats']['Races']:
             print("WARNING: Stats are identical. This might be correct if the driver only raced in one year, but check manually.")
        else:
            print("SUCCESS: Stats differ when filtered by year.")
            
        # Verify history contains only races from that year
        history = data_year.get('history', [])
        for race in history:
            season = race.get('Season')
            # Handle potential string/int mismatch
            if str(season) != str(test_year):
                print(f"ERROR: History contains race from season {season}, expected {test_year}")
                return False
        print(f"SUCCESS: History verified for year {test_year}")
        
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = test_profile_year_filter()
    if success:
        print("\nVerification PASSED")
        sys.exit(0)
    else:
        print("\nVerification FAILED")
        sys.exit(1)
