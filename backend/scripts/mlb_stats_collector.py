"""
MLB Stats Collector
====================
Uses tnestico/mlb_scraper (api_scraper.py) and the MLB Stats API to collect,
aggregate, and persist team-level and pitcher-level stats into PostgreSQL.

Designed to run nightly (or on-demand) to keep the feature engine fed with
fresh data for the ML models.
"""

import logging
import math
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import mlb_scraper
# ---------------------------------------------------------------------------
try:
    from scripts.api_scraper import MLB_Scrape
    _scraper = MLB_Scrape()
except Exception as e:
    _scraper = None
    logger.warning(f"mlb_scraper not available for collector: {e}")

PYTH_EXPONENT = 1.83

# ============================================================================
# 1. STANDINGS (from MLB Stats API — same as mlb_predictor, but richer)
# ============================================================================

async def fetch_standings(season: int = None) -> List[Dict[str, Any]]:
    """Fetch full team standings with runs/wins from MLB Stats API."""
    season = season or datetime.utcnow().year
    url = (
        f"https://statsapi.mlb.com/api/v1/standings"
        f"?leagueId=103,104&season={season}"
        f"&standingsTypes=regularSeason&hydrate=team"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch standings: {e}")
        return []

    teams = []
    for record in data.get("records", []):
        for entry in record.get("teamRecords", []):
            team_info = entry.get("team", {})
            wins = entry.get("wins", 0)
            losses = entry.get("losses", 0)
            gp = wins + losses
            if gp == 0:
                continue

            rs = entry.get("runsScored", 0)
            ra = entry.get("runsAllowed", 0)
            rs_g = rs / gp
            ra_g = ra / gp

            # Pythagorean win%
            if rs > 0 or ra > 0:
                pyth = (rs ** PYTH_EXPONENT) / (
                    (rs ** PYTH_EXPONENT) + (ra ** PYTH_EXPONENT)
                )
            else:
                pyth = 0.5

            teams.append({
                "season": season,
                "team_name": team_info.get("name", ""),
                "team_abbr": team_info.get("abbreviation", ""),
                "mlb_team_id": team_info.get("id"),
                "games_played": gp,
                "wins": wins,
                "losses": losses,
                "runs_scored": rs,
                "runs_allowed": ra,
                "rs_per_game": round(rs_g, 3),
                "ra_per_game": round(ra_g, 3),
                "run_diff_per_game": round(rs_g - ra_g, 3),
                "win_pct": round(wins / gp, 3),
                "pyth_win_pct": round(pyth, 3),
            })

    logger.info(f"Fetched standings for {len(teams)} teams (season {season})")
    return teams


# ============================================================================
# 2. TEAM PITCHING & BATTING (from MLB Stats API team stats endpoint)
# ============================================================================

async def fetch_team_pitching_batting(season: int = None) -> Dict[str, Dict]:
    """Fetch team-level pitching and batting stats from MLB Stats API."""
    season = season or datetime.utcnow().year
    stats: Dict[str, Dict] = {}

    # --- Pitching ---
    pitch_url = (
        f"https://statsapi.mlb.com/api/v1/teams/stats"
        f"?stats=season&season={season}&group=pitching"
        f"&sportIds=1&fields=stats,splits,team,name,id,stat,"
        f"era,whip,strikeOuts,baseOnBalls,inningsPitched,"
        f"hits,earnedRuns,strikeoutsPer9Inn,walksPer9Inn"
    )
    # --- Batting ---
    bat_url = (
        f"https://statsapi.mlb.com/api/v1/teams/stats"
        f"?stats=season&season={season}&group=hitting"
        f"&sportIds=1&fields=stats,splits,team,name,id,stat,"
        f"avg,slg,obp,strikeOuts,baseOnBalls,plateAppearances,"
        f"leftOnBase,gamesPlayed,stolenBases,stolenBasePercentage,"
        f"caughtStealing"
    )
    # --- Fielding ---
    field_url = (
        f"https://statsapi.mlb.com/api/v1/teams/stats"
        f"?stats=season&season={season}&group=fielding"
        f"&sportIds=1&fields=stats,splits,team,name,id,stat,"
        f"errors,doublePlays,gamesPlayed,assists,putOuts,chances"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            p_resp, b_resp, f_resp = await asyncio_gather(
                client.get(pitch_url),
                client.get(bat_url),
                client.get(field_url),
            )

            # Parse pitching
            for split in _extract_splits(p_resp.json()):
                name = split.get("_team_name", "")
                s = split.get("stat", {})
                ip = _parse_ip(s.get("inningsPitched", "0"))
                stats.setdefault(name, {})
                stats[name]["era"] = _safe_float(s.get("era"))
                stats[name]["whip"] = _safe_float(s.get("whip"))
                stats[name]["k9"] = _safe_float(s.get("strikeoutsPer9Inn"))
                stats[name]["bb9"] = _safe_float(s.get("walksPer9Inn"))

            # Parse batting
            for split in _extract_splits(b_resp.json()):
                name = split.get("_team_name", "")
                s = split.get("stat", {})
                stats.setdefault(name, {})
                stats[name]["batting_avg"] = _safe_float(s.get("avg"))
                stats[name]["slg"] = _safe_float(s.get("slg"))
                stats[name]["obp"] = _safe_float(s.get("obp"))

                pa = _safe_float(s.get("plateAppearances")) or 1
                gp = _safe_float(s.get("gamesPlayed")) or 1
                stats[name]["k_rate"] = round((_safe_float(s.get("strikeOuts")) or 0) / pa, 3)
                stats[name]["bb_rate"] = round((_safe_float(s.get("baseOnBalls")) or 0) / pa, 3)
                k_r = stats[name]["k_rate"]
                bb_r = stats[name]["bb_rate"]
                stats[name]["k_bb_ratio"] = round(k_r / bb_r, 2) if bb_r > 0 else 0

                lob = _safe_float(s.get("leftOnBase")) or 0
                stats[name]["lob_per_game"] = round(lob / gp, 2)

                sb = _safe_float(s.get("stolenBases")) or 0
                cs = _safe_float(s.get("caughtStealing")) or 0
                stats[name]["sb_success_rate"] = round(sb / (sb + cs), 3) if (sb + cs) > 0 else 0
                stats[name]["sb_rate"] = round(sb / gp, 2)

            # Parse fielding
            for split in _extract_splits(f_resp.json()):
                name = split.get("_team_name", "")
                s = split.get("stat", {})
                stats.setdefault(name, {})
                gp = _safe_float(s.get("gamesPlayed")) or 1
                errors = _safe_float(s.get("errors")) or 0
                dp = _safe_float(s.get("doublePlays")) or 0
                po = _safe_float(s.get("putOuts")) or 0
                a = _safe_float(s.get("assists")) or 0
                ch = _safe_float(s.get("chances")) or 1
                stats[name]["errors_per_game"] = round(errors / gp, 2)
                stats[name]["dp_rate"] = round(dp / gp, 2)
                stats[name]["def_efficiency"] = round((po + a) / ch, 3) if ch > 0 else 0

    except Exception as e:
        logger.error(f"Failed to fetch team pitching/batting/fielding: {e}")

    logger.info(f"Fetched pitching/batting/fielding for {len(stats)} teams")
    return stats


# ============================================================================
# 3. PITCHER-LEVEL STATS (from MLB Stats API)
# ============================================================================

async def fetch_pitcher_stats(season: int = None) -> List[Dict[str, Any]]:
    """
    Fetch individual pitcher season stats.
    Uses the MLB Stats API roster/stats endpoints.
    """
    season = season or datetime.utcnow().year
    pitchers = []

    # Get all team IDs first
    teams_url = f"https://statsapi.mlb.com/api/v1/teams?sportId=1&season={season}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            t_resp = await client.get(teams_url)
            t_resp.raise_for_status()
            team_list = t_resp.json().get("teams", [])

            for team in team_list:
                team_id = team.get("id")
                team_name = team.get("name", "")
                team_abbr = team.get("abbreviation", "")

                roster_url = (
                    f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
                    f"?rosterType=active&season={season}"
                )
                try:
                    r_resp = await client.get(roster_url)
                    if r_resp.status_code != 200:
                        continue
                    roster = r_resp.json().get("roster", [])

                    for player in roster:
                        pos = player.get("position", {}).get("abbreviation", "")
                        if pos != "P":
                            continue

                        person = player.get("person", {})
                        pid = person.get("id")
                        pname = person.get("fullName", "")

                        # Get this pitcher's season stats
                        stat_url = (
                            f"https://statsapi.mlb.com/api/v1/people/{pid}/stats"
                            f"?stats=season&season={season}&group=pitching"
                        )
                        try:
                            s_resp = await client.get(stat_url)
                            if s_resp.status_code != 200:
                                continue
                            stat_data = s_resp.json()
                            splits = stat_data.get("stats", [{}])[0].get("splits", [])
                            if not splits:
                                continue
                            s = splits[0].get("stat", {})

                            ip = _parse_ip(s.get("inningsPitched", "0"))
                            if ip < 1:
                                continue

                            pitchers.append({
                                "season": season,
                                "pitcher_id": pid,
                                "pitcher_name": pname,
                                "team_name": team_name,
                                "team_abbr": team_abbr,
                                "throws": person.get("pitchHand", {}).get("code", "R"),
                                "games": _safe_int(s.get("gamesPlayed")),
                                "games_started": _safe_int(s.get("gamesStarted")),
                                "innings_pitched": round(ip, 1),
                                "earned_runs": _safe_int(s.get("earnedRuns")),
                                "hits_allowed": _safe_int(s.get("hits")),
                                "walks": _safe_int(s.get("baseOnBalls")),
                                "strikeouts": _safe_int(s.get("strikeOuts")),
                                "era": _safe_float(s.get("era")),
                                "whip": _safe_float(s.get("whip")),
                                "k9": _safe_float(s.get("strikeoutsPer9Inn")),
                                "bb9": _safe_float(s.get("walksPer9Inn")),
                            })
                        except Exception:
                            continue
                except Exception:
                    continue

    except Exception as e:
        logger.error(f"Failed to fetch pitcher stats: {e}")

    logger.info(f"Fetched stats for {len(pitchers)} pitchers")
    return pitchers


# ============================================================================
# 4. TODAY'S PROBABLE PITCHERS
# ============================================================================

async def fetch_todays_probable_pitchers() -> Dict[str, Dict]:
    """
    Fetch today's probable starting pitchers from the MLB schedule endpoint.
    Returns dict keyed by "home_team||away_team" -> {home_sp_id, away_sp_id, ...}
    """
    today = date.today()
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={today}&hydrate=probablePitcher,team"
    )
    result = {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for d in data.get("dates", []):
                for game in d.get("games", []):
                    home = game.get("teams", {}).get("home", {})
                    away = game.get("teams", {}).get("away", {})
                    home_name = home.get("team", {}).get("name", "")
                    away_name = away.get("team", {}).get("name", "")

                    home_sp = home.get("probablePitcher", {})
                    away_sp = away.get("probablePitcher", {})

                    key = f"{home_name}||{away_name}"
                    result[key] = {
                        "game_id": game.get("gamePk"),
                        "home_sp_id": home_sp.get("id"),
                        "home_sp_name": home_sp.get("fullName", "TBD"),
                        "away_sp_id": away_sp.get("id"),
                        "away_sp_name": away_sp.get("fullName", "TBD"),
                        "game_time": game.get("gameDate", ""),
                        "day_night": game.get("dayNight", ""),
                        "venue": game.get("venue", {}).get("name", ""),
                        "venue_id": game.get("venue", {}).get("id"),
                    }
    except Exception as e:
        logger.error(f"Failed to fetch probable pitchers: {e}")

    logger.info(f"Fetched probable pitchers for {len(result)} games")
    return result


# ============================================================================
# 5. PERSIST TO DATABASE
# ============================================================================

async def save_team_stats(pool, team_data: List[Dict]) -> int:
    """Upsert team stats into mlb_team_stats."""
    if not team_data:
        return 0
    count = 0
    async with pool.acquire() as conn:
        for t in team_data:
            await conn.execute("""
                INSERT INTO mlb_team_stats (
                    season, team_name, team_abbr, mlb_team_id,
                    games_played, wins, losses,
                    runs_scored, runs_allowed, rs_per_game, ra_per_game, run_diff_per_game,
                    win_pct, pyth_win_pct,
                    era, whip, k9, bb9,
                    batting_avg, slg, obp,
                    k_rate, bb_rate, k_bb_ratio,
                    errors_per_game, dp_rate, def_efficiency,
                    sb_success_rate, sb_rate, lob_per_game,
                    updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7,
                    $8, $9, $10, $11, $12,
                    $13, $14,
                    $15, $16, $17, $18,
                    $19, $20, $21,
                    $22, $23, $24,
                    $25, $26, $27,
                    $28, $29, $30,
                    NOW()
                )
                ON CONFLICT (season, team_name) DO UPDATE SET
                    team_abbr = EXCLUDED.team_abbr,
                    mlb_team_id = EXCLUDED.mlb_team_id,
                    games_played = EXCLUDED.games_played,
                    wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                    runs_scored = EXCLUDED.runs_scored, runs_allowed = EXCLUDED.runs_allowed,
                    rs_per_game = EXCLUDED.rs_per_game, ra_per_game = EXCLUDED.ra_per_game,
                    run_diff_per_game = EXCLUDED.run_diff_per_game,
                    win_pct = EXCLUDED.win_pct, pyth_win_pct = EXCLUDED.pyth_win_pct,
                    era = EXCLUDED.era, whip = EXCLUDED.whip, k9 = EXCLUDED.k9, bb9 = EXCLUDED.bb9,
                    batting_avg = EXCLUDED.batting_avg, slg = EXCLUDED.slg, obp = EXCLUDED.obp,
                    k_rate = EXCLUDED.k_rate, bb_rate = EXCLUDED.bb_rate, k_bb_ratio = EXCLUDED.k_bb_ratio,
                    errors_per_game = EXCLUDED.errors_per_game, dp_rate = EXCLUDED.dp_rate,
                    def_efficiency = EXCLUDED.def_efficiency,
                    sb_success_rate = EXCLUDED.sb_success_rate, sb_rate = EXCLUDED.sb_rate,
                    lob_per_game = EXCLUDED.lob_per_game,
                    updated_at = NOW()
            """,
                t["season"], t["team_name"], t.get("team_abbr"), t.get("mlb_team_id"),
                t["games_played"], t["wins"], t["losses"],
                t["runs_scored"], t["runs_allowed"], t["rs_per_game"], t["ra_per_game"], t["run_diff_per_game"],
                t["win_pct"], t["pyth_win_pct"],
                t.get("era"), t.get("whip"), t.get("k9"), t.get("bb9"),
                t.get("batting_avg"), t.get("slg"), t.get("obp"),
                t.get("k_rate"), t.get("bb_rate"), t.get("k_bb_ratio"),
                t.get("errors_per_game"), t.get("dp_rate"), t.get("def_efficiency"),
                t.get("sb_success_rate"), t.get("sb_rate"), t.get("lob_per_game"),
            )
            count += 1
    logger.info(f"Saved {count} team stat rows")
    return count


async def save_pitcher_stats(pool, pitcher_data: List[Dict]) -> int:
    """Upsert pitcher stats into mlb_pitcher_stats."""
    if not pitcher_data:
        return 0
    count = 0
    async with pool.acquire() as conn:
        for p in pitcher_data:
            await conn.execute("""
                INSERT INTO mlb_pitcher_stats (
                    season, pitcher_id, pitcher_name, team_name, team_abbr, throws,
                    games, games_started, innings_pitched,
                    earned_runs, hits_allowed, walks, strikeouts,
                    era, whip, k9, bb9, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16, $17, NOW()
                )
                ON CONFLICT (season, pitcher_id) DO UPDATE SET
                    pitcher_name = EXCLUDED.pitcher_name,
                    team_name = EXCLUDED.team_name,
                    team_abbr = EXCLUDED.team_abbr,
                    throws = EXCLUDED.throws,
                    games = EXCLUDED.games,
                    games_started = EXCLUDED.games_started,
                    innings_pitched = EXCLUDED.innings_pitched,
                    earned_runs = EXCLUDED.earned_runs,
                    hits_allowed = EXCLUDED.hits_allowed,
                    walks = EXCLUDED.walks,
                    strikeouts = EXCLUDED.strikeouts,
                    era = EXCLUDED.era, whip = EXCLUDED.whip,
                    k9 = EXCLUDED.k9, bb9 = EXCLUDED.bb9,
                    updated_at = NOW()
            """,
                p["season"], p["pitcher_id"], p["pitcher_name"],
                p["team_name"], p.get("team_abbr"), p.get("throws"),
                p.get("games", 0), p.get("games_started", 0), p.get("innings_pitched", 0),
                p.get("earned_runs", 0), p.get("hits_allowed", 0),
                p.get("walks", 0), p.get("strikeouts", 0),
                p.get("era"), p.get("whip"), p.get("k9"), p.get("bb9"),
            )
            count += 1
    logger.info(f"Saved {count} pitcher stat rows")
    return count


# ============================================================================
# 6. FULL COLLECTION PIPELINE
# ============================================================================

async def run_full_collection(pool=None, season: int = None) -> Dict[str, Any]:
    """
    Run the complete MLB data collection pipeline.
    1. Fetch standings (wins, losses, runs)
    2. Fetch team pitching/batting/fielding
    3. Merge into unified team records
    4. Fetch individual pitcher stats
    5. Persist everything to PostgreSQL

    Args:
        pool: asyncpg connection pool (if None, will get from database module)
        season: MLB season year (default: current year)
    """
    season = season or datetime.utcnow().year
    result = {"season": season, "errors": []}

    # Get DB pool
    if pool is None:
        try:
            from src.database import get_pool
            pool = await get_pool()
        except Exception as e:
            result["errors"].append(f"DB pool unavailable: {e}")
            logger.error(f"Cannot get DB pool: {e}")
            return result

    # Ensure schema exists
    try:
        await _ensure_schema(pool)
    except Exception as e:
        result["errors"].append(f"Schema creation failed: {e}")
        logger.error(f"Schema creation error: {e}")

    # Step 1: Standings
    standings = await fetch_standings(season)
    result["teams_from_standings"] = len(standings)

    # Step 2: Team pitching/batting/fielding
    team_detail = await fetch_team_pitching_batting(season)

    # Step 3: Merge
    for team in standings:
        name = team["team_name"]
        if name in team_detail:
            team.update(team_detail[name])

    # Step 4: Save team stats
    try:
        result["team_rows_saved"] = await save_team_stats(pool, standings)
    except Exception as e:
        result["errors"].append(f"Team save error: {e}")
        logger.error(f"Team save error: {e}")
        result["team_rows_saved"] = 0

    # Step 5: Pitcher stats
    try:
        pitchers = await fetch_pitcher_stats(season)
        result["pitchers_fetched"] = len(pitchers)
        result["pitcher_rows_saved"] = await save_pitcher_stats(pool, pitchers)
    except Exception as e:
        result["errors"].append(f"Pitcher collection error: {e}")
        logger.error(f"Pitcher collection error: {e}")
        result["pitchers_fetched"] = 0
        result["pitcher_rows_saved"] = 0

    result["success"] = len(result["errors"]) == 0
    logger.info(f"MLB collection complete: {result}")
    return result


# ============================================================================
# HELPERS
# ============================================================================

import asyncio

async def asyncio_gather(*coros):
    """Simple wrapper for asyncio.gather on awaitables (httpx responses)."""
    return await asyncio.gather(*coros)


def _extract_splits(data: dict) -> List[Dict]:
    """Extract splits from MLB Stats API team stats response, tagging team name."""
    results = []
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            team = split.get("team", {})
            split["_team_name"] = team.get("name", "")
            results.append(split)
    return results


def _parse_ip(ip_str) -> float:
    """Parse innings pitched string (e.g. '123.1' means 123 and 1/3)."""
    try:
        s = str(ip_str)
        if "." in s:
            whole, frac = s.split(".")
            return int(whole) + int(frac) / 3
        return float(s)
    except Exception:
        return 0.0


def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int:
    """Safely convert a value to int."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


async def _ensure_schema(pool):
    """Create MLB tables if they don't exist (idempotent)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mlb_team_stats (
                id SERIAL PRIMARY KEY,
                season INT NOT NULL,
                team_name TEXT NOT NULL,
                team_abbr VARCHAR(10),
                mlb_team_id INT,
                games_played INT DEFAULT 0,
                wins INT DEFAULT 0, losses INT DEFAULT 0,
                runs_scored INT DEFAULT 0, runs_allowed INT DEFAULT 0,
                rs_per_game FLOAT, ra_per_game FLOAT, run_diff_per_game FLOAT,
                win_pct FLOAT, pyth_win_pct FLOAT,
                era FLOAT, whip FLOAT, k9 FLOAT, bb9 FLOAT,
                batting_avg FLOAT, slg FLOAT, obp FLOAT,
                k_rate FLOAT, bb_rate FLOAT, k_bb_ratio FLOAT,
                errors_per_game FLOAT, dp_rate FLOAT, def_efficiency FLOAT,
                sb_success_rate FLOAT, sb_rate FLOAT, lob_per_game FLOAT,
                day_win_pct FLOAT, night_win_pct FLOAT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(season, team_name)
            );

            CREATE TABLE IF NOT EXISTS mlb_pitcher_stats (
                id SERIAL PRIMARY KEY,
                season INT NOT NULL,
                pitcher_id INT NOT NULL,
                pitcher_name TEXT,
                team_name TEXT,
                team_abbr VARCHAR(10),
                throws VARCHAR(1),
                games INT DEFAULT 0,
                games_started INT DEFAULT 0,
                innings_pitched FLOAT DEFAULT 0,
                earned_runs INT DEFAULT 0,
                hits_allowed INT DEFAULT 0,
                walks INT DEFAULT 0,
                strikeouts INT DEFAULT 0,
                era FLOAT, whip FLOAT, k9 FLOAT, bb9 FLOAT,
                avg_velocity FLOAT, avg_spin_rate FLOAT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(season, pitcher_id)
            );

            CREATE TABLE IF NOT EXISTS mlb_game_features (
                id SERIAL PRIMARY KEY,
                game_id INT,
                game_date DATE NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_sp_id INT, away_sp_id INT,
                home_sp_name TEXT, away_sp_name TEXT,
                features JSONB,
                prediction JSONB,
                actual_home_runs INT, actual_away_runs INT,
                actual_winner TEXT, actual_total INT,
                home_moneyline INT, away_moneyline INT,
                spread FLOAT, over_under FLOAT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(game_date, home_team, away_team)
            );

            CREATE TABLE IF NOT EXISTS mlb_model_runs (
                id SERIAL PRIMARY KEY,
                model_name VARCHAR(50) NOT NULL,
                trained_at TIMESTAMPTZ DEFAULT NOW(),
                train_size INT, test_size INT,
                roc_auc FLOAT, accuracy FLOAT,
                brier_score FLOAT, log_loss FLOAT,
                feature_importances JSONB,
                hyperparameters JSONB,
                model_path TEXT
            );
        """)
    logger.info("MLB schema ensured")


# ============================================================================
# DB QUERY HELPERS (used by feature engine and predictor)
# ============================================================================

async def get_team_stats(pool, season: int, team_name: str) -> Optional[Dict]:
    """Fetch one team's stats from the DB."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mlb_team_stats WHERE season = $1 AND team_name = $2",
            season, team_name,
        )
        return dict(row) if row else None


async def get_all_team_stats(pool, season: int) -> Dict[str, Dict]:
    """Fetch all team stats for a season, keyed by team_name."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM mlb_team_stats WHERE season = $1", season
        )
        return {dict(r)["team_name"]: dict(r) for r in rows}


async def get_pitcher_by_id(pool, season: int, pitcher_id: int) -> Optional[Dict]:
    """Fetch a pitcher's season stats."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mlb_pitcher_stats WHERE season = $1 AND pitcher_id = $2",
            season, pitcher_id,
        )
        return dict(row) if row else None


async def get_team_pitchers(pool, season: int, team_name: str) -> List[Dict]:
    """Fetch all pitchers for a team."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM mlb_pitcher_stats WHERE season = $1 AND team_name = $2 ORDER BY games_started DESC",
            season, team_name,
        )
        return [dict(r) for r in rows]
