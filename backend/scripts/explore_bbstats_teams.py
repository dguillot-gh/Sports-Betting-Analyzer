
import pandas as pd
import inspect
import ncaa_bbStats.scrape_teamNames as team_names
import ncaa_bbStats.team_stats as team_stats

print("\n--- scrape_teamNames functions ---")
for name, obj in inspect.getmembers(team_names):
    if inspect.isfunction(obj):
        print(f"{name}{inspect.signature(obj)}")

print("\n--- Testing batting_average() return type ---")
try:
    df = team_stats.batting_average(year=2024, division=1)
    print(f"Type: {type(df)}")
    if isinstance(df, pd.DataFrame):
        print("Columns:", df.columns.tolist())
        print(df.head(3))
    else:
        print("Result:", df)
except Exception as e:
    print(f"Error calling batting_average: {e}")
