
import requests

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

URLS = {
    "snap_counts": f"{NFLVERSE_BASE}/snap_counts/snap_counts.parquet",
    "combine": f"{NFLVERSE_BASE}/combine/combine.parquet",
    "draft_picks": f"{NFLVERSE_BASE}/draft_picks/draft_picks.parquet",
    "injuries": f"{NFLVERSE_BASE}/injuries/injuries.parquet",
    "contracts": f"{NFLVERSE_BASE}/contracts/contracts.parquet",
    "teams": f"{NFLVERSE_BASE}/teams/teams.parquet",
    "ngs_passing": f"{NFLVERSE_BASE}/nextgen_stats/ngs_passing.parquet",
}

print("Checking NFLverse URLs...")
for name, url in URLS.items():
    try:
        r = requests.head(url, timeout=5)
        print(f"{name}: {r.status_code} - {url}")
        if r.status_code != 200 and r.status_code != 302:
             # Try .csv.gz?
             csv_url = url.replace(".parquet", ".csv.gz")
             r2 = requests.head(csv_url, timeout=5)
             print(f"  -> CSV backup {name}: {r2.status_code} - {csv_url}")
    except Exception as e:
        print(f"{name}: Error - {e}")
