import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def verify_comparison():
    print("Verifying Comparison Logic...")
    
    driver = "Chase Elliott"
    encoded_driver = requests.utils.quote(driver)
    
    # 1. Get available years
    url = f"{BASE_URL}/nascar/profile/{encoded_driver}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        years = data.get('years', [])
        
        if len(years) < 2:
            print("ERROR: Not enough years to compare.")
            return False
            
        year_a = years[0]
        year_b = years[1]
        
        print(f"Comparing {year_a} vs {year_b} for {driver}")
        
        # 2. Fetch Year A
        url_a = f"{BASE_URL}/nascar/profile/{encoded_driver}?year={year_a}"
        resp_a = requests.get(url_a)
        data_a = resp_a.json()
        
        # 3. Fetch Year B
        url_b = f"{BASE_URL}/nascar/profile/{encoded_driver}?year={year_b}"
        resp_b = requests.get(url_b)
        data_b = resp_b.json()
        
        # 4. Compare
        stats_a = data_a.get('stats', {})
        stats_b = data_b.get('stats', {})
        
        print(f"Year {year_a} Wins: {stats_a.get('Wins')}")
        print(f"Year {year_b} Wins: {stats_b.get('Wins')}")
        
        if stats_a == stats_b:
             print("WARNING: Stats are identical. Check if data is correct.")
        else:
            print("SUCCESS: Stats differ between years.")
            
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = verify_comparison()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
