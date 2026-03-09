import asyncio, sys, json
sys.path.insert(0, '.')
from scripts.college_baseball_results_scraper import fetch_college_baseball_scores

games = asyncio.run(fetch_college_baseball_scores(days_back=3))
print(f"{len(games)} completed games found")
for g in games[:5]:
    print(f"  {g['home_team']} {g['home_score']} - {g['away_score']} {g['away_team']} ({g['event_date']})")
