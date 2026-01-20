
import requests
import time
import json

def test_bulk():
    url = "http://localhost:8000/trends/ncaab/analyze-all"
    # Note: Use trends/ncaab prefix as seen in ncaab_endpoints.py? 
    # Wait, the frontend uses http://backend:8000/odds/ncaab/analyze-all
    
    url = "http://localhost:8000/odds/ncaab/analyze-all"
    
    print(f"Testing bulk analysis: {url}...")
    start = time.time()
    try:
        # Note: Set timeout to 60s as it might be slow
        response = requests.post(url, timeout=60)
        end = time.time()
        print(f"Response received in {end - start:.2f}s (Status: {response.status_code})")
        
        if response.status_code == 200:
            data = response.json()
            games = data.get('games', [])
            print(f"Found {len(games)} games.")
            
            for i, game in enumerate(games[:3]):
                h = game.get('home_team')
                a = game.get('away_team')
                pred = game.get('prediction', {})
                factors = pred.get('v2_factors', [])
                print(f"Game {i+1}: {h} vs {a}")
                print(f"  - V2 Factors: {len(factors)}")
                if not factors:
                    print("  - WARNING: factors list is EMPTY")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_bulk()
