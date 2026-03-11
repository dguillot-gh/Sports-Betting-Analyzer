"""
ESPN BPI/FPI Integration Endpoints

Fetches predictions from ESPN's hidden API for NBA (BPI) and NFL (FPI).
These endpoints are unofficial and may change without notice.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import httpx
import asyncio
import logging

router = APIRouter(prefix="/espn", tags=["ESPN"])
logger = logging.getLogger(__name__)

# ESPN API URLs
ESPN_NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_NFL_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_NCAAB_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
ESPN_NHL_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
ESPN_PROBABILITIES_BASE = "https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/events/{event_id}/competitions/{event_id}/probabilities"


async def fetch_espn_probabilities(sport: str, league: str, event_id: str) -> dict:
    """Fetch BPI/FPI probabilities for a specific game."""
    url = ESPN_PROBABILITIES_BASE.format(sport=sport, league=league, event_id=event_id)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                # Get the first (pre-game) probability entry
                if data.get("items") and len(data["items"]) > 0:
                    first_item = data["items"][0]
                    return {
                        "home_win_prob": first_item.get("homeWinPercentage", 0.5),
                        "away_win_prob": first_item.get("awayWinPercentage", 0.5),
                        "total_over_prob": first_item.get("totalOverProb", 0.5),
                        "spread_cover_home_prob": first_item.get("spreadCoverProbHome", 0.5)
                    }
    except Exception as e:
        logger.warning(f"Failed to fetch probabilities for {event_id}: {e}")
    
    return None


@router.get("/nba")
async def get_espn_nba_predictions():
    """
    Get ESPN BPI predictions for today's NBA games.
    
    Returns win probabilities, O/U predictions, and spread cover probabilities
    from ESPN's Basketball Power Index model.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch scoreboard
            resp = await client.get(ESPN_NBA_SCOREBOARD)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch ESPN NBA data")
            
            data = resp.json()
            games = []
            
            for event in data.get("events", []):
                event_id = event.get("id")
                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])
                
                if len(competitors) < 2:
                    continue
                
                # Home team is order=0, Away is order=1
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                
                game_info = {
                    "event_id": event_id,
                    "game_time": event.get("date"),
                    "status": competition.get("status", {}).get("type", {}).get("description", "Unknown"),
                    "home_team": home.get("team", {}).get("displayName", "Unknown"),
                    "home_abbrev": home.get("team", {}).get("abbreviation", ""),
                    "home_score": home.get("score", "0"),
                    "home_record": next((r.get("summary") for r in home.get("records", []) if r.get("type") == "total"), ""),
                    "away_team": away.get("team", {}).get("displayName", "Unknown"),
                    "away_abbrev": away.get("team", {}).get("abbreviation", ""),
                    "away_score": away.get("score", "0"),
                    "away_record": next((r.get("summary") for r in away.get("records", []) if r.get("type") == "total"), ""),
                    "venue": competition.get("venue", {}).get("fullName", ""),
                    # Defaults - will be updated with BPI data
                    "home_win_prob": 0.5,
                    "away_win_prob": 0.5,
                    "total_over_prob": 0.5,
                    "spread_cover_home_prob": 0.5,
                    "has_bpi": False
                }
                
                games.append(game_info)
            
            # Fetch BPI probabilities for each game (in parallel, limited concurrency)
            async def enrich_game(game):
                probs = await fetch_espn_probabilities("basketball", "nba", game["event_id"])
                if probs:
                    game.update(probs)
                    game["has_bpi"] = True
                return game
            
            # Limit concurrent requests
            semaphore = asyncio.Semaphore(5)
            async def limited_fetch(game):
                async with semaphore:
                    return await enrich_game(game)
            
            enriched_games = await asyncio.gather(*[limited_fetch(g) for g in games])
            
            return {
                "sport": "NBA",
                "source": "ESPN BPI",
                "games": enriched_games,
                "disclaimer": "ESPN's BPI predictions - unofficial API, may change without notice"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ESPN NBA fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching ESPN data: {str(e)}")


@router.get("/nfl")
async def get_espn_nfl_predictions():
    """
    Get ESPN FPI predictions for current NFL games.
    
    Returns win probabilities, O/U predictions, and spread cover probabilities
    from ESPN's Football Power Index model.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch scoreboard
            resp = await client.get(ESPN_NFL_SCOREBOARD)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch ESPN NFL data")
            
            data = resp.json()
            games = []
            
            for event in data.get("events", []):
                event_id = event.get("id")
                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])
                
                if len(competitors) < 2:
                    continue
                
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                
                # Get odds if available
                odds_data = competition.get("odds", [{}])[0] if competition.get("odds") else {}
                
                game_info = {
                    "event_id": event_id,
                    "game_time": event.get("date"),
                    "status": competition.get("status", {}).get("type", {}).get("description", "Unknown"),
                    "week": event.get("week", {}).get("number"),
                    "home_team": home.get("team", {}).get("displayName", "Unknown"),
                    "home_abbrev": home.get("team", {}).get("abbreviation", ""),
                    "home_score": home.get("score", "0"),
                    "home_record": next((r.get("summary") for r in home.get("records", []) if r.get("type") == "total"), ""),
                    "away_team": away.get("team", {}).get("displayName", "Unknown"),
                    "away_abbrev": away.get("team", {}).get("abbreviation", ""),
                    "away_score": away.get("score", "0"),
                    "away_record": next((r.get("summary") for r in away.get("records", []) if r.get("type") == "total"), ""),
                    "venue": competition.get("venue", {}).get("fullName", ""),
                    "broadcast": competition.get("broadcast", ""),
                    # Odds from ESPN
                    "spread": odds_data.get("details", ""),
                    "over_under": odds_data.get("overUnder"),
                    # Defaults - will be updated with FPI data
                    "home_win_prob": 0.5,
                    "away_win_prob": 0.5,
                    "total_over_prob": 0.5,
                    "spread_cover_home_prob": 0.5,
                    "has_fpi": False
                }
                
                games.append(game_info)
            
            # Fetch FPI probabilities for each game
            async def enrich_game(game):
                probs = await fetch_espn_probabilities("football", "nfl", game["event_id"])
                if probs:
                    game.update(probs)
                    game["has_fpi"] = True
                return game
            
            semaphore = asyncio.Semaphore(5)
            async def limited_fetch(game):
                async with semaphore:
                    return await enrich_game(game)
            
            enriched_games = await asyncio.gather(*[limited_fetch(g) for g in games])
            
            return {
                "sport": "NFL",
                "source": "ESPN FPI", 
                "week": data.get("week", {}).get("number"),
                "games": enriched_games,
                "disclaimer": "ESPN's FPI predictions - unofficial API, may change without notice"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ESPN NFL fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching ESPN data: {str(e)}")

@router.get("/ncaab")
async def get_espn_ncaab_predictions():
    """
    Get ESPN BPI predictions for today's NCAAB games.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ESPN_NCAAB_SCOREBOARD)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch ESPN NCAAB data")
            
            data = resp.json()
            games = []
            
            # NCAAB has many games, filter for Top 25 or major conferences if list is huge? 
            # For now, return all (pagination might be needed later if huge)
            
            for event in data.get("events", []):
                event_id = event.get("id")
                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])
                
                if len(competitors) < 2:
                    continue
                
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                
                game_info = {
                    "event_id": event_id,
                    "game_time": event.get("date"),
                    "status": competition.get("status", {}).get("type", {}).get("description", "Unknown"),
                    "home_team": home.get("team", {}).get("displayName", "Unknown"),
                    "home_abbrev": home.get("team", {}).get("abbreviation", ""),
                    "home_score": home.get("score", "0"),
                    "home_rank": home.get("curatedRank", {}).get("current", ""),
                    "away_team": away.get("team", {}).get("displayName", "Unknown"),
                    "away_abbrev": away.get("team", {}).get("abbreviation", ""),
                    "away_score": away.get("score", "0"),
                    "away_rank": away.get("curatedRank", {}).get("current", ""),
                    "venue": competition.get("venue", {}).get("fullName", ""),
                    "broadcast": competition.get("broadcast", ""),
                    "home_win_prob": 0.5,
                    "away_win_prob": 0.5,
                    "total_over_prob": 0.5,
                    "has_bpi": False
                }
                
                games.append(game_info)
            
            # Limit to Top 50 games or something if too many? 
            # Or just fetch probabilities for all. ESPN API is fast but rate limits exist.
            # Let's limit concurrency.
            
            async def enrich_game(game):
                # For NCAAB, league is mens-college-basketball
                probs = await fetch_espn_probabilities("basketball", "mens-college-basketball", game["event_id"])
                if probs:
                    game.update(probs)
                    game["has_bpi"] = True
                return game
            
            semaphore = asyncio.Semaphore(5)
            async def limited_fetch(game):
                async with semaphore:
                    return await enrich_game(game)
            
            # Enrich all
            enriched_games = await asyncio.gather(*[limited_fetch(g) for g in games])
            
            # Sort by Rank if available, then Time
            def rank_sort(g):
                h_rank = int(g["home_rank"]) if str(g["home_rank"]).isdigit() and int(g["home_rank"]) < 99 else 999
                a_rank = int(g["away_rank"]) if str(g["away_rank"]).isdigit() and int(g["away_rank"]) < 99 else 999
                return min(h_rank, a_rank)
                
            enriched_games.sort(key=rank_sort)

            return {
                "sport": "NCAAB",
                "source": "ESPN BPI",
                "games": enriched_games,
                "disclaimer": "ESPN's BPI predictions - unofficial API"
            }
            
    except Exception as e:
        logger.error(f"ESPN NCAAB fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nhl")
async def get_espn_nhl_scoreboard():
    """
    Get ESPN NHL scoreboard for today's games with scores and status.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ESPN_NHL_SCOREBOARD)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch ESPN NHL data")
            
            data = resp.json()
            games = []
            
            for event in data.get("events", []):
                event_id = event.get("id")
                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])
                
                if len(competitors) < 2:
                    continue
                
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                
                odds_data = competition.get("odds", [{}])[0] if competition.get("odds") else {}
                
                game_info = {
                    "event_id": event_id,
                    "game_time": event.get("date"),
                    "status": competition.get("status", {}).get("type", {}).get("description", "Unknown"),
                    "home_team": home.get("team", {}).get("displayName", "Unknown"),
                    "home_abbrev": home.get("team", {}).get("abbreviation", ""),
                    "home_score": home.get("score", "0"),
                    "home_record": next((r.get("summary") for r in home.get("records", []) if r.get("type") == "total"), ""),
                    "away_team": away.get("team", {}).get("displayName", "Unknown"),
                    "away_abbrev": away.get("team", {}).get("abbreviation", ""),
                    "away_score": away.get("score", "0"),
                    "away_record": next((r.get("summary") for r in away.get("records", []) if r.get("type") == "total"), ""),
                    "venue": competition.get("venue", {}).get("fullName", ""),
                    "spread": odds_data.get("details", ""),
                    "over_under": odds_data.get("overUnder"),
                }
                
                games.append(game_info)
            
            return {
                "sport": "NHL",
                "source": "ESPN",
                "games": games,
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ESPN NHL fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching ESPN NHL data: {str(e)}")
