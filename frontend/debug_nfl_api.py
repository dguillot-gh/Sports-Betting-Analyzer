
import requests

API_KEY = "f87fec52-3532-47de-9675-24ec94fbe1dc"
HEADERS = {"Authorization": API_KEY}

URLS = [
    "https://nfl.balldontlie.io/v1/teams",
    "https://nfl.balldontlie.io/api/v1/teams",
    "https://nfl.balldontlie.io/teams",
    "https://api.balldontlie.io/nfl/v1/teams",
    "https://api.balldontlie.io/v1/teams?sport=nfl" # Maybe it's all on main API?
]

print("Testing NFL API Endpoints...")
for url in URLS:
    try:
        print(f"GET {url}")
        res = requests.get(url, headers=HEADERS, timeout=5)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            print(f"Success! Data keys: {data.keys()}")
            if 'data' in data and len(data['data']) > 0:
                 print(f"First team: {data['data'][0]}")
            else:
                 print(f"Response: {data}")
            break
        else:
            print(f"Response: {res.text[:100]}")
    except Exception as e:
        print(f"Error: {e}")
