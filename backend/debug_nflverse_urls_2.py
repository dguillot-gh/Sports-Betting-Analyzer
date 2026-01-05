
import requests

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

URLS_TO_TEST = [
    # Snap Counts alternatives
    f"{NFLVERSE_BASE}/snap_counts/snap_counts_2023.parquet",
    f"{NFLVERSE_BASE}/snap_counts/snap_counts_2023.csv.gz",
    f"{NFLVERSE_BASE}/pbp_participation/pbp_participation_2023.parquet",
    
    # Teams alternatives
    f"{NFLVERSE_BASE}/teams/teams.csv.gz",
    f"{NFLVERSE_BASE}/site_data/site_teams.csv.gz",
    f"{NFLVERSE_BASE}/misc/teams.parquet",
    f"{NFLVERSE_BASE}/misc/teams.csv.gz",
    
    # Injuries alternatives
    f"{NFLVERSE_BASE}/injuries/injuries_2023.parquet",
    f"{NFLVERSE_BASE}/misc/injuries.parquet",
    
    # Contracts alternatives
    f"{NFLVERSE_BASE}/contracts/contracts.csv.gz",
    f"{NFLVERSE_BASE}/contracts/historical_contracts.parquet",
    f"{NFLVERSE_BASE}/misc/contracts.parquet",
]

print("Checking Alternative NFLverse URLs...")
for url in URLS_TO_TEST:
    try:
        r = requests.head(url, timeout=5)
        print(f"{r.status_code} - {url}")
    except Exception as e:
        print(f"Error - {url}: {e}")
