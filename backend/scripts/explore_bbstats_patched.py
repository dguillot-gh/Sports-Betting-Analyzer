
import pandas as pd
import inspect
import requests
import ncaa_bbStats.scrape_teamNames as team_names
import ncaa_bbStats.team_stats as team_stats

# Monkey-patch requests
_original_get = requests.get

def patched_get(*args, **kwargs):
    headers = kwargs.get('headers', {})
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    kwargs['headers'] = headers
    print(f"Making request to {args[0]} with headers")
    return _original_get(*args, **kwargs)

requests.get = patched_get

print("\n--- Testing batting_average() with User-Agent ---")
try:
    # Use 2024 as 2025 might not have data yet or be weird
    df = team_stats.batting_average(year=2024, division=1)
    print(f"Type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        print("Columns:", df.columns.tolist())
        print(df.head(3))
    else:
        print("Result:", df)
        if isinstance(df, dict):
            print("Keys:", list(df.keys())[:5])
except Exception as e:
    print(f"Error calling batting_average: {e}")
