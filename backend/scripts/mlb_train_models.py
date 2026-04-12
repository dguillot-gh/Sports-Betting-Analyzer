"""
MLB Model Training Pipeline
==============================
Collects historical game data, builds feature matrices, and trains
all three MLB prediction models (moneyline, spread, totals).

Can be run as a standalone script or triggered via API endpoint.
"""

import asyncio
import logging
import json
from datetime import datetime, date
from typing import Dict, Any, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def build_historical_features(
    pool,
    start_year: int = 2021,
    end_year: int = None,
) -> pd.DataFrame:
    """
    Build a feature matrix from historical MLB game data stored in the DB.
    Each row = one game with features + targets.

    If we don't have enough DB data yet, falls back to MLB Stats API
    game results to build a simpler feature set.
    """
    end_year = end_year or datetime.utcnow().year

    # Try to load from mlb_game_features first (if backfill has been run)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT game_date, home_team, away_team, features,
                   actual_home_runs, actual_away_runs, actual_total,
                   over_under
            FROM mlb_game_features
            WHERE actual_home_runs IS NOT NULL
              AND features IS NOT NULL
              AND EXTRACT(YEAR FROM game_date) BETWEEN $1 AND $2
            ORDER BY game_date
        """, start_year, end_year)

    if rows and len(rows) >= 100:
        logger.info(f"Building from {len(rows)} stored game features")
        return _rows_to_dataframe(rows)

    # Fallback: build from team stats + schedule
    logger.info("Not enough stored features, building from team stats + MLB API schedule")
    return await _build_from_standings(pool, start_year, end_year)


async def _build_from_standings(pool, start_year: int, end_year: int) -> pd.DataFrame:
    """
    Build a simpler feature matrix using team season stats and historical
    game results from MLB Stats API.
    """
    import httpx
    from scripts.mlb_features import (
        ALL_FEATURE_COLS, fill_missing_features,
        _build_team_features, _build_sp_features, _build_matchup_features,
    )
    from scripts.mlb_stats_collector import get_all_team_stats

    all_games = []

    for season in range(start_year, end_year + 1):
        # Get team stats for this season
        team_stats = await get_all_team_stats(pool, season)
        if not team_stats:
            logger.warning(f"No team stats for {season}, skipping")
            continue

        # Fetch completed games from MLB API
        url = (
            f"https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&season={season}&gameType=R"
            f"&fields=dates,date,games,gamePk,teams,home,away,team,name,"
            f"score,isWinner,leagueRecord,wins,losses,gameDate,dayNight,"
            f"status,detailedState"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch {season} schedule: {e}")
            continue

        for d in data.get("dates", []):
            game_date_str = d.get("date", "")
            for game in d.get("games", []):
                status = game.get("status", {}).get("detailedState", "")
                if status != "Final":
                    continue

                home = game.get("teams", {}).get("home", {})
                away = game.get("teams", {}).get("away", {})
                home_name = home.get("team", {}).get("name", "")
                away_name = away.get("team", {}).get("name", "")
                home_runs = home.get("score", 0)
                away_runs = away.get("score", 0)

                if not home_name or not away_name:
                    continue

                home_ts = team_stats.get(home_name, {})
                away_ts = team_stats.get(away_name, {})

                if not home_ts or not away_ts:
                    continue

                # Build features
                features = {}
                features.update(_build_team_features(home_ts, away_ts))
                features.update(_build_sp_features(None, None, home_ts, away_ts))
                features.update(_build_matchup_features(home_ts, away_ts, None, None))

                # Context defaults
                is_day = 1.0 if game.get("dayNight") == "day" else 0.0
                features.update({
                    "temp": 72.0, "windspeed": 5.0, "is_day": is_day,
                    "wind_out": 0.0, "wind_in": 0.0, "dome_flag": 0.0,
                    "temp_cold": 0.0, "temp_hot": 0.0, "overcast_flag": 0.0,
                    "park_factor": 1.0,
                    "home_days_rest": 1.0, "away_days_rest": 1.0,
                    "home_back_to_back": 0.0, "away_back_to_back": 0.0,
                    "is_doubleheader": 0.0,
                    "home_lob_per_g": home_ts.get("lob_per_game"),
                    "away_lob_per_g": away_ts.get("lob_per_game"),
                    "exp_total": (home_ts.get("rs_per_game") or 4.5) + (away_ts.get("rs_per_game") or 4.5),
                })

                features = fill_missing_features(features)

                # Targets
                total_runs = (home_runs or 0) + (away_runs or 0)
                exp_total = features["exp_total"]

                features["date"] = game_date_str
                features["home_team"] = home_name
                features["away_team"] = away_name
                features["home_runs"] = home_runs
                features["away_runs"] = away_runs
                features["home_win"] = 1 if (home_runs or 0) > (away_runs or 0) else 0
                features["home_cover"] = 1 if ((home_runs or 0) - (away_runs or 0)) >= 2 else 0
                features["went_over"] = 1 if total_runs > exp_total else 0
                features["total_runs"] = total_runs

                all_games.append(features)

    if not all_games:
        logger.warning("No historical games collected")
        return pd.DataFrame()

    df = pd.DataFrame(all_games)
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"Built feature matrix: {len(df)} games, {len(df.columns)} columns")
    return df


def _rows_to_dataframe(rows) -> pd.DataFrame:
    """Convert DB rows (with JSONB features) to a flat DataFrame."""
    records = []
    for row in rows:
        r = dict(row)
        features = r.get("features", {})
        if isinstance(features, str):
            features = json.loads(features)

        flat = dict(features)
        flat["date"] = r["game_date"]
        flat["home_team"] = r["home_team"]
        flat["away_team"] = r["away_team"]

        home_runs = r.get("actual_home_runs") or 0
        away_runs = r.get("actual_away_runs") or 0
        ou = r.get("over_under") or flat.get("exp_total", 9.0)

        flat["home_win"] = 1 if home_runs > away_runs else 0
        flat["home_cover"] = 1 if (home_runs - away_runs) >= 2 else 0
        flat["went_over"] = 1 if (home_runs + away_runs) > ou else 0

        records.append(flat)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df


async def train_all_models(pool=None, start_year: int = 2021) -> Dict[str, Any]:
    """
    Full training pipeline: collect features, train all 3 models, save results.

    Returns dict with metrics for each model.
    """
    if pool is None:
        from src.database import get_pool
        pool = await get_pool()

    result = {"trained_at": datetime.utcnow().isoformat(), "models": {}}

    # Build feature matrix
    features_df = await build_historical_features(pool, start_year)

    if features_df.empty or len(features_df) < 50:
        result["error"] = f"Not enough data to train ({len(features_df)} games). Need at least 50."
        logger.warning(result["error"])
        return result

    logger.info(f"Training on {len(features_df)} games from {start_year}+")

    # Train moneyline
    try:
        from scripts.mlb_moneyline_model import train_moneyline_model
        ml_result = train_moneyline_model(features_df)
        result["models"]["moneyline"] = ml_result["metrics"]
        result["models"]["moneyline"]["train_size"] = ml_result["train_size"]
        result["models"]["moneyline"]["test_size"] = ml_result["test_size"]
        await _save_model_run(pool, "moneyline", ml_result)
    except Exception as e:
        logger.error(f"Moneyline training failed: {e}")
        result["models"]["moneyline"] = {"error": str(e)}

    # Train spread
    try:
        from scripts.mlb_spread_model import train_spread_model
        sp_result = train_spread_model(features_df)
        result["models"]["spread"] = sp_result["metrics"]
        result["models"]["spread"]["train_size"] = sp_result["train_size"]
        result["models"]["spread"]["test_size"] = sp_result["test_size"]
        await _save_model_run(pool, "spread", sp_result)
    except Exception as e:
        logger.error(f"Spread training failed: {e}")
        result["models"]["spread"] = {"error": str(e)}

    # Train totals
    try:
        from scripts.mlb_totals_model import train_totals_model
        ou_result = train_totals_model(features_df)
        result["models"]["totals"] = ou_result["metrics"]
        result["models"]["totals"]["train_size"] = ou_result["train_size"]
        result["models"]["totals"]["test_size"] = ou_result["test_size"]
        await _save_model_run(pool, "totals", ou_result)
    except Exception as e:
        logger.error(f"Totals training failed: {e}")
        result["models"]["totals"] = {"error": str(e)}

    result["success"] = all(
        "error" not in result["models"].get(m, {})
        for m in ["moneyline", "spread", "totals"]
    )

    logger.info(f"Training pipeline complete: {result}")
    return result


async def _save_model_run(pool, model_name: str, result: Dict):
    """Save training run metrics to mlb_model_runs table."""
    try:
        metrics = result.get("metrics", {})
        importances = result.get("importances")
        imp_json = importances.to_dict("records") if importances is not None else []

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO mlb_model_runs
                    (model_name, train_size, test_size,
                     roc_auc, accuracy, brier_score, log_loss,
                     feature_importances, trained_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            """,
                model_name,
                result.get("train_size", 0),
                result.get("test_size", 0),
                metrics.get("roc_auc"),
                metrics.get("accuracy"),
                metrics.get("brier_score"),
                metrics.get("log_loss"),
                json.dumps(imp_json),
            )
    except Exception as e:
        logger.warning(f"Failed to save model run for {model_name}: {e}")
