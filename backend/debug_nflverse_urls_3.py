
import requests

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

URLS_TO_TEST = [
    # Teams alternatives
    f"{NFLVERSE_BASE}/teams/teams_colors_logos.parquet",
    f"{NFLVERSE_BASE}/teams/teams_colors_logos.csv.gz",
    
    # Snap Counts check for a few years
    f"{NFLVERSE_BASE}/snap_counts/snap_counts_2024.parquet",
    f"{NFLVERSE_BASE}/snap_counts/snap_counts_2020.parquet",
    
    # PBP Participation (often used for snap counts)
    f"{NFLVERSE_BASE}/pbp_participation/pbp_participation_2024.parquet",
    f"{NFLVERSE_BASE}/pbp_participation/pbp_participation_2020.parquet",
]

print("Checking Final NFLverse URLs...")
for url in URLS_TO_TEST:
    try:
        r = requests.head(url, timeout=5)
        print(f"{r.status_code} - {url}")
    except Exception as e:
        print(f"Error - {url}: {e}")
