import asyncio, sys
sys.path.insert(0, '.')
from scripts.college_baseball_results_scraper import fetch_college_baseball_scores

async def main():
    games = await fetch_college_baseball_scores(days_back=3)
    print(f"=== ESPN College Baseball Results ({len(games)} games) ===\n")
    
    by_date = {}
    for g in games:
        by_date.setdefault(g["event_date"], []).append(g)
    
    for dt in sorted(by_date.keys(), reverse=True):
        print(f"--- {dt} ({len(by_date[dt])} games) ---")
        for g in sorted(by_date[dt], key=lambda x: x["home_team"]):
            marker = ">" if g["home_score"] > g["away_score"] else "<"
            home = g["home_team"].ljust(35)
            away = g["away_team"]
            print(f"  {home} {g['home_score']:2d} {marker} {g['away_score']:2d}  {away}")
        print()

asyncio.run(main())
