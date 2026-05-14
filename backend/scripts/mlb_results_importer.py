"""
MLB Results Importer
====================
Imports completed MLB game results from the MLB Stats API into the results
table for bet grading, CLV calculation, and model backtesting.

Data Source: https://statsapi.mlb.com/api/v1/schedule
Covers: 2024 season onward (configurable).

Scheduler integration: runs as part of the daily pipeline.
"""

import hashlib
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_BOXSCORE_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
SEASONS = [2024, 2025, 2026]  # Adjust as needed

UPSERT_SQL = """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                VALUES ($1, $2, 'mlb', $3, $4)
                ON CONFLICT (content_hash)
                DO UPDATE SET metadata = EXCLUDED.metadata"""


def compute_hash(data: dict) -> str:
    """Compute MD5 hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fetch completed games from MLB Stats API schedule
# ---------------------------------------------------------------------------
async def fetch_completed_games(season: int, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
    """
    Fetch all completed (Final) MLB games for a season or date range.
    Returns a list of game dicts with scores, teams, venue, pitchers.
    """
    if not start_date:
        start_date = f"{season}-02-20"
    if not end_date:
        # Use today or end of season
        today = date.today()
        season_end = date(season, 11, 15)
        end_date = str(min(today, season_end))

    games = []
    # MLB schedule API accepts max ~6 month ranges, so chunk by month
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    async with httpx.AsyncClient(timeout=20.0) as client:
        while current <= end:
            chunk_end = min(current + timedelta(days=30), end)
            url = (
                f"{MLB_SCHEDULE_URL}"
                f"?sportId=1&season={season}"
                f"&startDate={current}&endDate={chunk_end}"
                f"&gameType=R,F,D,L,W"  # Regular, Wild Card, Divisional, LCS, WS
                f"&hydrate=team,probablePitcher,linescore,decisions,venue"
            )

            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                for game_date in data.get("dates", []):
                    for game in game_date.get("games", []):
                        status = game.get("status", {}).get("detailedState", "")
                        if status not in ("Final", "Game Over", "Completed Early"):
                            continue

                        parsed = _parse_game(game, season)
                        if parsed:
                            games.append(parsed)

            except Exception as e:
                logger.warning(f"MLB schedule fetch error ({current} to {chunk_end}): {e}")

            current = chunk_end + timedelta(days=1)

    logger.info(f"Fetched {len(games)} completed MLB games for {season}")
    return games


def _parse_game(game: Dict[str, Any], season: int) -> Optional[Dict[str, Any]]:
    """Parse a single game from the MLB Stats API schedule response."""
    try:
        game_pk = game.get("gamePk")
        game_date = game.get("officialDate") or game.get("gameDate", "")[:10]
        game_type = game.get("gameType", "R")

        # Teams
        teams = game.get("teams", {})
        away_data = teams.get("away", {})
        home_data = teams.get("home", {})

        away_team_info = away_data.get("team", {})
        home_team_info = home_data.get("team", {})

        away_team = away_team_info.get("name", "")
        home_team = home_team_info.get("name", "")
        away_score = _safe_int(away_data.get("score"))
        home_score = _safe_int(home_data.get("score"))

        if not away_team or not home_team:
            return None

        # Winner
        if home_score is not None and away_score is not None:
            winner = home_team if home_score > away_score else away_team
            margin = abs(home_score - away_score)
            total_runs = home_score + away_score
        else:
            winner = None
            margin = None
            total_runs = None

        # Linescore (innings detail)
        linescore = game.get("linescore", {})
        innings = linescore.get("scheduledInnings", 9)
        current_inning = linescore.get("currentInning")

        home_hits = _safe_int(linescore.get("teams", {}).get("home", {}).get("hits"))
        away_hits = _safe_int(linescore.get("teams", {}).get("away", {}).get("hits"))
        home_errors = _safe_int(linescore.get("teams", {}).get("home", {}).get("errors"))
        away_errors = _safe_int(linescore.get("teams", {}).get("away", {}).get("errors"))

        # Decisions (W/L/S pitchers)
        decisions = game.get("decisions", {})
        winning_pitcher = decisions.get("winner", {}).get("fullName")
        losing_pitcher = decisions.get("loser", {}).get("fullName")
        save_pitcher = decisions.get("save", {}).get("fullName")

        # Probable pitchers
        away_sp = away_data.get("probablePitcher", {}).get("fullName")
        home_sp = home_data.get("probablePitcher", {}).get("fullName")

        # Venue
        venue = game.get("venue", {}).get("name")

        # Records
        away_record = f"{away_data.get('leagueRecord', {}).get('wins', 0)}-{away_data.get('leagueRecord', {}).get('losses', 0)}"
        home_record = f"{home_data.get('leagueRecord', {}).get('wins', 0)}-{home_data.get('leagueRecord', {}).get('losses', 0)}"

        return {
            "game_pk": game_pk,
            "game_date": game_date,
            "game_type": game_type,
            "season": season,
            "away_team": away_team,
            "home_team": home_team,
            "away_score": away_score,
            "home_score": home_score,
            "winner": winner,
            "margin": margin,
            "total_runs": total_runs,
            "innings": current_inning or innings,
            "away_hits": away_hits,
            "home_hits": home_hits,
            "away_errors": away_errors,
            "home_errors": home_errors,
            "away_sp": away_sp,
            "home_sp": home_sp,
            "winning_pitcher": winning_pitcher,
            "losing_pitcher": losing_pitcher,
            "save_pitcher": save_pitcher,
            "venue": venue,
            "away_record": away_record,
            "home_record": home_record,
        }
    except Exception as e:
        logger.warning(f"Error parsing MLB game: {e}")
        return None


# ---------------------------------------------------------------------------
# Import into database
# ---------------------------------------------------------------------------
async def import_mlb_results(conn, sport_id: int, season: int,
                              progress_callback=None) -> Dict[str, int]:
    """
    Import completed MLB game results for a season into the results table.
    """
    from scripts.batch_db import batch_upsert

    games = await fetch_completed_games(season)

    if progress_callback:
        progress_callback(f"Processing {len(games)} MLB games for {season}...")

    records: List[Tuple] = []
    for game in games:
        content_hash = compute_hash({
            "sport": "mlb",
            "game_pk": game["game_pk"],
        })

        metadata = {
            # Standardized keys (for API/frontend)
            "game_pk": game["game_pk"],
            "game_date": game["game_date"],
            "game_type": game["game_type"],
            "season": season,
            "away_team": game["away_team"],
            "home_team": game["home_team"],
            "away_score": game["away_score"],
            "home_score": game["home_score"],
            "winner": game["winner"],
            "margin": game["margin"],
            "total_runs": game["total_runs"],
            "innings": game["innings"],
            "away_hits": game["away_hits"],
            "home_hits": game["home_hits"],
            "away_errors": game["away_errors"],
            "home_errors": game["home_errors"],
            "away_sp": game["away_sp"],
            "home_sp": game["home_sp"],
            "winning_pitcher": game["winning_pitcher"],
            "losing_pitcher": game["losing_pitcher"],
            "save_pitcher": game["save_pitcher"],
            "venue": game["venue"],
            "away_record": game["away_record"],
            "home_record": game["home_record"],
        }

        # Strip None values for cleaner JSON
        metadata = {k: v for k, v in metadata.items() if v is not None}

        records.append((sport_id, season, json.dumps(metadata), content_hash))

    if not records:
        logger.info(f"No MLB game records to import for {season}")
        return {"imported": 0, "season": season}

    imported = await batch_upsert(
        conn, UPSERT_SQL, records,
        progress_callback=progress_callback,
        label=f"MLB {season} results"
    )

    logger.info(f"Imported {imported} MLB game results for {season}")
    return {"imported": imported, "season": season}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
async def run_import(progress_callback=None) -> Dict[str, Any]:
    """
    Import MLB results for all configured seasons.
    Called by the scheduler or manually via API.
    """
    import os
    import asyncpg

    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sports_betting")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # Get or create MLB sport
        sport_id = await conn.fetchval(
            "SELECT id FROM sports WHERE LOWER(name) = 'mlb'"
        )
        if not sport_id:
            sport_id = await conn.fetchval(
                """INSERT INTO sports (name, config) VALUES ('mlb', '{}')
                   ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                   RETURNING id"""
            )

        total_imported = 0
        results_by_season = {}

        for season in SEASONS:
            if progress_callback:
                progress_callback(f"MLB results: importing {season}...")
            result = await import_mlb_results(conn, sport_id, season, progress_callback)
            total_imported += result["imported"]
            results_by_season[season] = result["imported"]

        return {
            "total_imported": total_imported,
            "seasons": results_by_season,
        }
    finally:
        await conn.close()
