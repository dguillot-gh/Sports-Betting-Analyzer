"""
College Baseball Game Results Scraper

Fetches completed game results from ESPN's API and stores them
in the `results` table for the rolling-stats XGBoost layer.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

# ESPN API endpoints for college baseball
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"


async def fetch_college_baseball_scores(
    target_date: date = None,
    days_back: int = 1
) -> List[Dict[str, Any]]:
    """
    Fetch completed college baseball game scores from ESPN.
    
    Args:
        target_date: The date to start from (default: today)
        days_back: How many days back to fetch (default: 1)
    
    Returns:
        List of game result dicts ready for DB insertion.
    """
    if target_date is None:
        target_date = date.today()

    all_games = []

    for i in range(days_back):
        game_date = target_date - timedelta(days=i)
        date_str = game_date.strftime("%Y%m%d")
        
        try:
            url = f"{ESPN_SCOREBOARD_URL}?dates={date_str}&limit=200"
            resp = requests.get(url, timeout=30)
            
            if resp.status_code != 200:
                logger.warning(f"ESPN returned {resp.status_code} for {date_str}")
                continue
            
            data = resp.json()
            events = data.get("events", [])
            
            for event in events:
                competitions = event.get("competitions", [])
                if not competitions:
                    continue
                    
                comp = competitions[0]
                
                # Only completed games
                status = comp.get("status", {}).get("type", {})
                if status.get("completed") != True:
                    continue
                
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                
                # Parse home/away
                home_team = None
                away_team = None
                home_score = 0
                away_score = 0
                
                for c in competitors:
                    team_data = c.get("team", {})
                    team_name = team_data.get("displayName", team_data.get("shortDisplayName", "Unknown"))
                    score = int(c.get("score", "0"))
                    
                    if c.get("homeAway") == "home":
                        home_team = team_name
                        home_score = score
                    else:
                        away_team = team_name
                        away_score = score
                
                if not home_team or not away_team:
                    continue
                
                game_result = {
                    "event_date": game_date.isoformat(),
                    "season": game_date.year,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "venue": comp.get("venue", {}).get("fullName", ""),
                    "neutral_site": comp.get("neutralSite", False),
                    "espn_id": event.get("id"),
                }
                all_games.append(game_result)
            
            logger.info(f"Fetched {len(events)} events for {date_str}, "
                       f"{sum(1 for e in events if e.get('competitions', [{}])[0].get('status', {}).get('type', {}).get('completed'))} completed")
            
        except Exception as e:
            logger.error(f"Error fetching scores for {date_str}: {e}")
    
    logger.info(f"Total completed games fetched: {len(all_games)}")
    return all_games


async def store_game_results(games: List[Dict[str, Any]], db_url: str = None) -> Dict[str, int]:
    """
    Store game results in the PostgreSQL results table.
    
    Args:
        games: List of game result dicts from fetch_college_baseball_scores
        db_url: Database connection URL
    
    Returns:
        Summary counts with keys: rows, new, updated
    """
    if not games:
        return {"rows": 0, "new": 0, "updated": 0}
    
    if db_url is None:
        try:
            from src.config import DATABASE_URL as CFG_DB
            db_url = CFG_DB
        except Exception:
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://sports_user:sportsbetting2024@localhost:5432/sports_betting"
            )
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        
        # Ensure the sport exists
        sport_id = await conn.fetchval(
            "SELECT id FROM sports WHERE name = 'college_baseball'"
        )
        if not sport_id:
            sport_id = await conn.fetchval(
                "INSERT INTO sports (name, display_name) VALUES ('college_baseball', 'College Baseball') RETURNING id"
            )
        
        new_count = 0
        updated_count = 0
        for game in games:
            game_date_obj = datetime.fromisoformat(game["event_date"]).date()
            metadata = json.dumps({
                "homeTeam": game["home_team"],
                "awayTeam": game["away_team"],
                "homeScore": game["home_score"],
                "awayScore": game["away_score"],
                "venue": game.get("venue", ""),
                "neutralSite": game.get("neutral_site", False),
                "espnId": game.get("espn_id"),
            })
            
            # Use content_hash for better duplicate detection if available in schema
            # But the schema here seems to use (series, game_date, homeTeam, awayTeam) implicitly
            # Let's use a more robust approach: INSERT ... ON CONFLICT (id) is not possible without ID
            # Does results have a unique constraint we can leverage?
            # From previous scripts, it seems we use (content_hash) or similar.
            # If not, we'll keep the manual check but return metrics.
            
            # Check for duplicate (same ESPN ID or same teams + date)
            existing_id = await conn.fetchval(
                """SELECT id FROM results 
                   WHERE series = 'college_baseball' 
                   AND game_date = $1
                   AND metadata->>'homeTeam' = $2
                   AND metadata->>'awayTeam' = $3""",
                game_date_obj,
                game["home_team"],
                game["away_team"]
            )
            
            if existing_id:
                # Update existing
                await conn.execute(
                    """UPDATE results SET home_score = $1, away_score = $2, metadata = $3
                       WHERE id = $4""",
                    game["home_score"], game["away_score"], metadata, existing_id
                )
                updated_count += 1
            else:
                # Insert new
                await conn.execute(
                    """INSERT INTO results (sport_id, season, game_date, 
                       home_score, away_score, metadata, series)
                       VALUES ($1, $2, $3, $4, $5, $6, 'college_baseball')""",
                    sport_id,
                    game["season"],
                    game_date_obj,
                    game["home_score"],
                    game["away_score"],
                    metadata
                )
                new_count += 1
        
        await conn.close()
        logger.info(f"Summary: {new_count} new, {updated_count} updated results")
        return {"rows": new_count + updated_count, "new": new_count, "updated": updated_count}
        
    except Exception as e:
        logger.error(f"Error storing game results: {e}")
        return {"rows": 0, "new": 0, "updated": 0}


async def scrape_and_store(days_back: int = 7) -> Dict[str, Any]:
    """
    Full pipeline: fetch scores from ESPN and store in DB.
    
    Args:
        days_back: How many days of results to fetch
    
    Returns:
        Summary dict with counts
    """
    logger.info(f"Starting college baseball results scrape ({days_back} days back)...")
    
    games = await fetch_college_baseball_scores(days_back=days_back)
    summary = await store_game_results(games)
    
    return {
        "games_fetched": len(games),
        "games_inserted": summary.get("new", 0),
        "games_updated": summary.get("updated", 0),
        "rows": summary.get("rows", 0),
        "new": summary.get("new", 0),
        "updated": summary.get("updated", 0),
        "days_scraped": days_back,
        "scrape_date": datetime.now().isoformat()
    }


async def backfill_season(year: int = 2026) -> Dict[str, Any]:
    """
    Backfill an entire season of game results.
    College baseball season runs roughly Feb 14 - June 30.
    """
    logger.info(f"Backfilling {year} college baseball season...")
    
    season_start = date(year, 2, 14)
    season_end = min(date(year, 6, 30), date.today())
    
    total_days = (season_end - season_start).days + 1
    if total_days <= 0:
        return {"error": f"Season {year} hasn't started yet"}
    
    games = await fetch_college_baseball_scores(
        target_date=season_end,
        days_back=total_days
    )
    
    summary = await store_game_results(games)
    
    return {
        "year": year,
        "games_fetched": len(games),
        "games_inserted": summary.get("new", 0),
        "games_updated": summary.get("updated", 0),
        "rows": summary.get("rows", 0),
        "new": summary.get("new", 0),
        "updated": summary.get("updated", 0),
        "date_range": f"{season_start} to {season_end}"
    }


if __name__ == "__main__":
    import sys
    
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    
    if "--backfill" in sys.argv:
        year = int(sys.argv[sys.argv.index("--backfill") + 1]) if len(sys.argv) > sys.argv.index("--backfill") + 1 else 2026
        result = asyncio.run(backfill_season(year))
    else:
        result = asyncio.run(scrape_and_store(days_back=days))
    
    print(json.dumps(result, indent=2))
