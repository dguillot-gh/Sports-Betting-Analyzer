
import sys
import inspect

try:
    import ncaa_bbStats.team_stats as team_stats
    import ncaa_bbStats.scrape_teamNames as team_names
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)

print("\n--- scrape_teamNames functions ---")
for name, obj in inspect.getmembers(team_names):
    if inspect.isfunction(obj):
        print(f"{name}{inspect.signature(obj)}")

print("\n--- team_stats functions ---")
for name, obj in inspect.getmembers(team_stats):
    if inspect.isfunction(obj):
        print(f"{name}{inspect.signature(obj)}")
