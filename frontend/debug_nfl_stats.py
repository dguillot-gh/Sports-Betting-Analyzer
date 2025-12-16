
import requests
import json

API_KEY = "f87fec52-3532-47de-9675-24ec94fbe1dc"
HEADERS = {"Authorization": API_KEY}
BASE_URL = "https://api.balldontlie.io/nfl/v1"

def get_nfl_stats_structure():
    try:
        # 1. Get recent games to find a valid game_id
        print("Fetching recent NFL games...")
        games_res = requests.get(f"{BASE_URL}/games?per_page=5", headers=HEADERS)
        if games_res.status_code != 200:
            print(f"Failed to get games: {games_res.status_code}")
            return

        games = games_res.json().get('data', [])
        if not games:
            print("No games found.")
            return

        game_id = games[0]['id']
        print(f"Found Game ID: {game_id} ({games[0]['visitor_team']['abbreviation']} @ {games[0]['home_team']['abbreviation']})")

        # 2. Get stats for this game
        print(f"Fetching stats for game {game_id}...")
        stats_res = requests.get(f"{BASE_URL}/stats?game_ids[]={game_id}", headers=HEADERS)
        
        if stats_res.status_code == 200:
            stats = stats_res.json().get('data', [])
            if stats:
                print("\nSample Player Stat Record:")
                # Print keys and values of the first record to see structure
                print(json.dumps(stats[0], indent=2))
            else:
                 print("No player stats found for this game.")
        else:
            print(f"Failed to get stats: {stats_res.status_code} - {stats_res.text}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_nfl_stats_structure()
