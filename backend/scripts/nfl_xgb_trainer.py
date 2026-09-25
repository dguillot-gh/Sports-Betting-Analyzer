"""Train and serve NFL XGBoost models from the application's imported data."""

import asyncio
import json
import logging
import math
import os
import tempfile
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.config import DATABASE_URL

logger = logging.getLogger(__name__)

try:
    import asyncpg
    import numpy as np
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    asyncpg = None
    np = None
    xgb = None
    XGB_AVAILABLE = False
    logger.warning("NFL XGBoost training unavailable: asyncpg, numpy, or xgboost is missing")

MODELS_DIR = Path(os.getenv("NFL_MODELS_DIR", "models/nfl"))
MODEL_VERSION = "db_rolling_v2"
MIN_HISTORY_GAMES = 2
ROLLING_WINDOW = 8

# Keep this order identical in feature creation, training, and inference.
FEATURE_NAMES = [
    "home_ppg", "home_opp_ppg", "away_ppg", "away_opp_ppg",
    "home_win_pct", "away_win_pct",
    "home_last5_wins", "away_last5_wins",
    "home_epa_per_play", "away_epa_per_play",
    "home_pass_yds_per_game", "away_pass_yds_per_game",
    "home_rush_yds_per_game", "away_rush_yds_per_game",
    "home_td_per_game", "away_td_per_game",
    "home_turnovers_per_game", "away_turnovers_per_game",
]

TEAM_ALIASES = {
    "arizona cardinals": "ARI", "atlanta falcons": "ATL", "baltimore ravens": "BAL",
    "buffalo bills": "BUF", "carolina panthers": "CAR", "chicago bears": "CHI",
    "cincinnati bengals": "CIN", "cleveland browns": "CLE", "dallas cowboys": "DAL",
    "denver broncos": "DEN", "detroit lions": "DET", "green bay packers": "GB",
    "houston texans": "HOU", "indianapolis colts": "IND", "jacksonville jaguars": "JAX",
    "kansas city chiefs": "KC", "las vegas raiders": "LV", "oakland raiders": "LV",
    "los angeles chargers": "LAC", "san diego chargers": "LAC",
    "los angeles rams": "LAR", "st. louis rams": "LAR", "miami dolphins": "MIA",
    "minnesota vikings": "MIN", "new england patriots": "NE", "new orleans saints": "NO",
    "new york giants": "NYG", "new york jets": "NYJ", "philadelphia eagles": "PHI",
    "pittsburgh steelers": "PIT", "san francisco 49ers": "SF", "seattle seahawks": "SEA",
    "tampa bay buccaneers": "TB", "tennessee titans": "TEN",
    "washington commanders": "WAS", "washington football team": "WAS",
    "washington redskins": "WAS", "jacksonville": "JAX", "washington": "WAS",
}


def _canonical_team(value: Any) -> Optional[str]:
    if value is None:
        return None
    team = str(value).strip()
    if not team:
        return None
    upper = team.upper()
    aliases = {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS"}
    if upper in set(TEAM_ALIASES.values()) | {"JAC", "LA", "STL", "SD", "OAK", "WSH"}:
        return aliases.get(upper, upper)
    return TEAM_ALIASES.get(team.lower())


def _metadata(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _american_implied_probability(value: Optional[float]) -> Optional[float]:
    if value is None or value == 0:
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _normalize_schedule_rows(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    games = []
    for row in rows:
        meta = _metadata(row["metadata"])
        game_date = _as_date(meta.get("gameday") or row.get("game_date"))
        home = _canonical_team(meta.get("home_team"))
        away = _canonical_team(meta.get("away_team"))
        home_score_value = meta.get("home_score")
        away_score_value = meta.get("away_score")
        if home_score_value is None:
            home_score_value = row.get("home_score")
        if away_score_value is None:
            away_score_value = row.get("away_score")
        home_score = _number(home_score_value)
        away_score = _number(away_score_value)
        if not game_date or not home or not away:
            continue
        games.append({
            "date": game_date,
            "season": int(row["season"] or meta.get("season") or game_date.year),
            "home": home,
            "away": away,
            "week": int(meta["week"]) if _number(meta.get("week")) is not None else None,
            "home_score": home_score,
            "away_score": away_score,
            "home_moneyline": _number(meta.get("home_moneyline")),
            "away_moneyline": _number(meta.get("away_moneyline")),
            "game_type": str(meta.get("game_type") or "REG").upper(),
        })
    return sorted(games, key=lambda game: (game["date"], game["season"], game["home"], game["away"]))


def _team_features(history: Sequence[Tuple[float, float, int]]) -> Optional[Dict[str, float]]:
    if len(history) < MIN_HISTORY_GAMES:
        return None
    recent = list(history)[-ROLLING_WINDOW:]
    ppg = sum(game[0] for game in recent) / len(recent)
    oppg = sum(game[1] for game in recent) / len(recent)
    win_pct = sum(game[2] for game in recent) / len(recent)
    last5_wins = sum(game[2] for game in recent[-5:])
    return {
        "ppg": ppg,
        "oppg": oppg,
        "win_pct": win_pct,
        "last5_wins": float(last5_wins),
        # Scoring differential proxy retained as part of this model's feature contract.
        "epa_proxy": max(-0.35, min(0.35, (ppg - oppg) / 25.0)),
    }


def _matchup_features(home_stats: Dict[str, float], away_stats: Dict[str, float],
                      home_weekly: Optional[Dict[str, float]] = None,
                      away_weekly: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    home_weekly = home_weekly or {}
    away_weekly = away_weekly or {}
    return {
        "home_ppg": home_stats["ppg"],
        "home_opp_ppg": home_stats["oppg"],
        "away_ppg": away_stats["ppg"],
        "away_opp_ppg": away_stats["oppg"],
        "home_win_pct": home_stats["win_pct"],
        "away_win_pct": away_stats["win_pct"],
        "home_last5_wins": home_stats["last5_wins"],
        "away_last5_wins": away_stats["last5_wins"],
        "home_epa_per_play": home_stats["epa_proxy"],
        "away_epa_per_play": away_stats["epa_proxy"],
        "home_pass_yds_per_game": home_weekly.get("pass_yds_per_game", 0.0),
        "away_pass_yds_per_game": away_weekly.get("pass_yds_per_game", 0.0),
        "home_rush_yds_per_game": home_weekly.get("rush_yds_per_game", 0.0),
        "away_rush_yds_per_game": away_weekly.get("rush_yds_per_game", 0.0),
        "home_td_per_game": home_weekly.get("td_per_game", 0.0),
        "away_td_per_game": away_weekly.get("td_per_game", 0.0),
        "home_turnovers_per_game": home_weekly.get("turnovers_per_game", 0.0),
        "away_turnovers_per_game": away_weekly.get("turnovers_per_game", 0.0),
    }


def _weekly_team_games(rows: Sequence[Any]) -> Dict[str, List[Tuple[int, int, Dict[str, float]]]]:
    """Aggregate player-week rows into team-week totals from the nightly import."""
    buckets: Dict[Tuple[int, int, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        meta = _metadata(row["metadata"])
        team = _canonical_team(meta.get("team"))
        season_value = _number(row["season"] or meta.get("season"))
        week_value = _number(meta.get("week"))
        if not team or season_value is None or week_value is None:
            continue
        key = (int(season_value), int(week_value), team)
        for target, source in (
            ("pass_yds", "pass_yds"), ("rush_yds", "rush_yds"),
            ("pass_td", "pass_td"), ("rush_td", "rush_td"), ("turnovers", "pass_int"),
        ):
            buckets[key][target] += _number(meta.get(source)) or 0.0

    by_team: Dict[str, List[Tuple[int, int, Dict[str, float]]]] = defaultdict(list)
    for (season, week, team), totals in buckets.items():
        game_stats = {
            "pass_yds": totals["pass_yds"],
            "rush_yds": totals["rush_yds"],
            "td": totals["pass_td"] + totals["rush_td"],
            "turnovers": totals["turnovers"],
        }
        by_team[team].append((season, week, game_stats))
    for team_games in by_team.values():
        team_games.sort(key=lambda item: (item[0], item[1]))
    return by_team


def _recent_player_features(team: str, season: int, week: Optional[int], weekly_games) -> Dict[str, float]:
    team_games = weekly_games.get(team, [])
    if week is not None:
        team_games = [game for game in team_games if game[0] < season or (game[0] == season and game[1] < week)]
    recent = [game[2] for game in team_games[-ROLLING_WINDOW:]]
    if not recent:
        return {}
    n_games = len(recent)
    return {
        "pass_yds_per_game": sum(game["pass_yds"] for game in recent) / n_games,
        "rush_yds_per_game": sum(game["rush_yds"] for game in recent) / n_games,
        "td_per_game": sum(game["td"] for game in recent) / n_games,
        "turnovers_per_game": sum(game["turnovers"] for game in recent) / n_games,
    }


def build_training_examples(rows: Sequence[Any], weekly_rows: Sequence[Any] = ()) -> Tuple[List[Dict[str, float]], List[int], List[float], List[date], List[Optional[float]]]:
    """Build pregame-only rolling features; all games on a date share prior-day history."""
    games = _normalize_schedule_rows(rows)
    weekly_games = _weekly_team_games(weekly_rows)
    histories: Dict[str, deque] = defaultdict(lambda: deque(maxlen=ROLLING_WINDOW))
    features: List[Dict[str, float]] = []
    labels: List[int] = []
    totals: List[float] = []
    game_dates: List[date] = []
    market_probabilities: List[Optional[float]] = []

    index = 0
    while index < len(games):
        day = games[index]["date"]
        end = index
        while end < len(games) and games[end]["date"] == day:
            end += 1
        same_day_games = games[index:end]

        # Features for every game date are captured before adding any same-day outcomes.
        for game in same_day_games:
            home_stats = _team_features(histories[game["home"]])
            away_stats = _team_features(histories[game["away"]])
            if (game["game_type"] == "REG" and game["home_score"] is not None
                    and game["away_score"] is not None and home_stats and away_stats):
                home_weekly = _recent_player_features(game["home"], game["season"], game["week"], weekly_games)
                away_weekly = _recent_player_features(game["away"], game["season"], game["week"], weekly_games)
                features.append(_matchup_features(home_stats, away_stats, home_weekly, away_weekly))
                labels.append(int(game["home_score"] > game["away_score"]))
                totals.append(game["home_score"] + game["away_score"])
                game_dates.append(day)
                home_market = _american_implied_probability(game["home_moneyline"])
                away_market = _american_implied_probability(game["away_moneyline"])
                if home_market is not None and away_market is not None and home_market + away_market > 0:
                    market_probabilities.append(home_market / (home_market + away_market))
                else:
                    market_probabilities.append(None)

        # Completed regular/postseason games update form for later dates.
        for game in same_day_games:
            if game["game_type"] not in {"REG", "POST"} or game["home_score"] is None or game["away_score"] is None:
                continue
            home_win = int(game["home_score"] > game["away_score"])
            histories[game["home"]].append((game["home_score"], game["away_score"], home_win))
            histories[game["away"]].append((game["away_score"], game["home_score"], 1 - home_win))
        index = end

    return features, labels, totals, game_dates, market_probabilities


def build_live_features(rows: Sequence[Any], home_team: str, away_team: str, weekly_rows: Sequence[Any] = (),
                        as_of: Optional[date] = None) -> Dict[str, float]:
    """Use the same schedule-based feature contract as training for a live matchup."""
    home = _canonical_team(home_team)
    away = _canonical_team(away_team)
    if not home or not away:
        raise ValueError(f"Unrecognized NFL team name: {home_team!r} or {away_team!r}")
    cutoff = as_of or date.today()
    games = _normalize_schedule_rows(rows)
    histories: Dict[str, deque] = defaultdict(lambda: deque(maxlen=ROLLING_WINDOW))
    target_game = next((game for game in games if game["date"] >= cutoff
                        and {game["home"], game["away"]} == {home, away}), None)
    if target_game is None:
        target_game = next((game for game in games if game["date"] >= cutoff), None)
    target_season = target_game["season"] if target_game else cutoff.year
    target_week = target_game["week"] if target_game else None
    for game in games:
        if game["date"] >= cutoff:
            continue
        if game["game_type"] not in {"REG", "POST"} or game["home_score"] is None or game["away_score"] is None:
            continue
        home_win = int(game["home_score"] > game["away_score"])
        histories[game["home"]].append((game["home_score"], game["away_score"], home_win))
        histories[game["away"]].append((game["away_score"], game["home_score"], 1 - home_win))

    home_stats = _team_features(histories[home])
    away_stats = _team_features(histories[away])
    if home_stats is None or away_stats is None:
        raise ValueError(
            f"Insufficient imported NFL game history for {home_team} vs {away_team}; "
            f"at least {MIN_HISTORY_GAMES} completed games per team are required"
        )
    weekly_games = _weekly_team_games(weekly_rows)
    home_weekly = _recent_player_features(home, target_season, target_week, weekly_games)
    away_weekly = _recent_player_features(away, target_season, target_week, weekly_games)
    return _matchup_features(home_stats, away_stats, home_weekly, away_weekly)


async def _fetch_schedule_rows(conn) -> List[Any]:
    return await conn.fetch("""
        SELECT r.season, r.game_date, r.home_score, r.away_score, r.metadata
        FROM results r
        JOIN sports s ON s.id = r.sport_id
        WHERE s.name = 'nfl' AND r.series = 'nfl_schedule'
        ORDER BY r.season, r.game_date
    """)


async def _fetch_weekly_rows(conn) -> List[Any]:
    return await conn.fetch("""
        SELECT r.season, r.metadata
        FROM results r
        JOIN sports s ON s.id = r.sport_id
        WHERE s.name = 'nfl' AND r.series = 'nfl_weekly'
        ORDER BY r.season
    """)


_live_data_cache: Optional[Tuple[float, List[Any], List[Any]]] = None
_live_data_cache_lock = asyncio.Lock()


async def fetch_live_features(home_team: str, away_team: str, as_of: Optional[date] = None) -> Dict[str, float]:
    if not XGB_AVAILABLE:
        raise RuntimeError("NFL XGBoost prediction dependencies are unavailable")
    global _live_data_cache
    async with _live_data_cache_lock:
        now = asyncio.get_running_loop().time()
        if _live_data_cache is None or now - _live_data_cache[0] > 60:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                schedules = await _fetch_schedule_rows(conn)
                weekly = await _fetch_weekly_rows(conn)
                _live_data_cache = (now, schedules, weekly)
            finally:
                await conn.close()
        _, schedules, weekly = _live_data_cache
    return build_live_features(schedules, home_team, away_team, weekly, as_of)


class NFLXGBTrainer:
    """Moneyline and total models trained only from imported PostgreSQL schedules."""

    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.feature_names = FEATURE_NAMES.copy()
        self.loaded_training_metadata: Dict[str, Any] = {}
        if XGB_AVAILABLE:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)

    def _features_to_matrix(self, features: Sequence[Dict[str, float]]):
        matrix = np.array([[feature[name] for name in self.feature_names] for feature in features], dtype=np.float32)
        if not np.isfinite(matrix).all():
            raise ValueError("NFL feature matrix contains missing or non-finite values")
        return matrix

    @staticmethod
    def _atomic_save_model(model, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".json", dir=destination.parent)
        os.close(fd)
        try:
            model.save_model(temp_path)
            os.replace(temp_path, destination)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def train(self, epochs: int = 500) -> Dict[str, Any]:
        if not XGB_AVAILABLE:
            return {"error": "asyncpg, numpy, or xgboost is not installed"}

        conn = await asyncpg.connect(DATABASE_URL)
        try:
            rows = await _fetch_schedule_rows(conn)
            weekly_rows = await _fetch_weekly_rows(conn)
        finally:
            await conn.close()

        features, labels, totals, game_dates, market_probabilities = build_training_examples(rows, weekly_rows)
        if len(features) < 200:
            raise ValueError(
                f"Only {len(features)} usable NFL training games found in imported schedules; "
                "need at least 200. No model was written."
            )

        X = self._features_to_matrix(features)
        y_win = np.asarray(labels, dtype=np.float32)
        y_total = np.asarray(totals, dtype=np.float32)
        unique_dates = sorted(set(game_dates))
        if len(unique_dates) < 6:
            raise ValueError("Imported NFL data does not span enough game dates for walk-forward validation")

        # Expanding chronological folds split by full date, never between same-day games.
        date_chunks = np.array_split(np.asarray(unique_dates, dtype=object), min(5, len(unique_dates) - 1))
        oof_probs: List[float] = []
        oof_labels: List[int] = []
        oof_totals: List[float] = []
        total_errors: List[float] = []
        market_oof: List[Tuple[float, int]] = []
        model_market_oof: List[Tuple[float, int]] = []
        rounds = max(50, min(int(epochs), 500))
        params_ml = {
            "max_depth": 3, "eta": 0.03, "objective": "binary:logistic",
            "eval_metric": "logloss", "subsample": 0.85, "colsample_bytree": 0.9,
            "lambda": 2.0, "seed": 42, "nthread": 2,
        }
        params_ou = {
            "max_depth": 3, "eta": 0.03, "objective": "reg:squarederror",
            "subsample": 0.85, "colsample_bytree": 0.9,
            "lambda": 2.0, "seed": 42, "nthread": 2,
        }

        day_values = np.asarray(game_dates, dtype=object)
        for fold_index in range(1, len(date_chunks)):
            train_end_day = date_chunks[fold_index][0]
            train_idx = np.flatnonzero(day_values < train_end_day)
            test_idx = np.flatnonzero(np.isin(day_values, date_chunks[fold_index]))
            if len(train_idx) < 100 or not len(test_idx):
                continue
            model_ml = xgb.train(params_ml, xgb.DMatrix(X[train_idx], label=y_win[train_idx]), rounds)
            model_ou = xgb.train(params_ou, xgb.DMatrix(X[train_idx], label=y_total[train_idx]), rounds)
            probs = model_ml.predict(xgb.DMatrix(X[test_idx]))
            totals_pred = model_ou.predict(xgb.DMatrix(X[test_idx]))
            oof_probs.extend(float(value) for value in probs)
            oof_labels.extend(int(value) for value in y_win[test_idx])
            oof_totals.extend(float(value) for value in y_total[test_idx])
            total_errors.extend(abs(float(pred) - float(actual)) for pred, actual in zip(totals_pred, y_total[test_idx]))
            for test_position, idx in enumerate(test_idx):
                market_prob = market_probabilities[int(idx)]
                if market_prob is not None:
                    market_oof.append((float(market_prob), int(y_win[int(idx)])))
                    model_market_oof.append((float(probs[test_position]), int(y_win[int(idx)])))

        if not oof_probs:
            raise ValueError("Walk-forward validation produced no held-out predictions; no model was written")

        probabilities = np.clip(np.asarray(oof_probs), 1e-7, 1 - 1e-7)
        actuals = np.asarray(oof_labels)
        brier = float(np.mean((probabilities - actuals) ** 2))
        log_loss = float(-np.mean(actuals * np.log(probabilities) + (1 - actuals) * np.log(1 - probabilities)))
        accuracy = float(np.mean((probabilities >= 0.5) == actuals))
        ou_mae = float(np.mean(total_errors)) if total_errors else None
        market_metrics = None
        if market_oof:
            market_probs = np.clip(np.asarray([item[0] for item in market_oof]), 1e-7, 1 - 1e-7)
            market_actuals = np.asarray([item[1] for item in market_oof])
            market_metrics = {
                "samples": len(market_oof),
                "brier_score": float(np.mean((market_probs - market_actuals) ** 2)),
                "log_loss": float(-np.mean(market_actuals * np.log(market_probs) + (1 - market_actuals) * np.log(1 - market_probs))),
                "accuracy": float(np.mean((market_probs >= 0.5) == market_actuals)),
            }
            model_probs_same_games = np.clip(np.asarray([item[0] for item in model_market_oof]), 1e-7, 1 - 1e-7)
            market_metrics["xgboost_on_same_games"] = {
                "brier_score": float(np.mean((model_probs_same_games - market_actuals) ** 2)),
                "log_loss": float(-np.mean(market_actuals * np.log(model_probs_same_games) + (1 - market_actuals) * np.log(1 - model_probs_same_games))),
                "accuracy": float(np.mean((model_probs_same_games >= 0.5) == market_actuals)),
            }

        final_ml = xgb.train(params_ml, xgb.DMatrix(X, label=y_win), rounds)
        final_ou = xgb.train(params_ou, xgb.DMatrix(X, label=y_total), rounds)
        self._atomic_save_model(final_ml, MODELS_DIR / "xgb_moneyline.json")
        self._atomic_save_model(final_ou, MODELS_DIR / "xgb_overunder.json")

        latest_game_day = max(game_dates).isoformat()
        metadata = {
            "model_version": MODEL_VERSION,
            "trained_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "data_source": "postgresql.results where series in (nfl_schedule, nfl_weekly)",
            "seasons": sorted({int(row["season"]) for row in rows if row["season"] is not None}),
            "latest_training_game_date": latest_game_day,
            "training_samples": int(len(X)),
            "validation_samples": int(len(oof_probs)),
            "validation_dates": len(unique_dates),
            "validation_method": "expanding walk-forward, split by full game date",
            "validation_accuracy": accuracy,
            "validation_brier_score": brier,
            "validation_log_loss": log_loss,
            "validation_total_mae": ou_mae,
            "market_baseline": market_metrics,
            "features": self.feature_names,
            "minimum_history_games": MIN_HISTORY_GAMES,
            "rolling_window_games": ROLLING_WINDOW,
            "boost_rounds": rounds,
        }
        metadata_path = MODELS_DIR / "training_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.model_ml = final_ml
        self.model_ou = final_ou
        self.loaded_training_metadata = metadata
        logger.info(
            "NFL XGBoost trained from %s imported games; walk-forward accuracy %.3f, Brier %.4f, log-loss %.4f",
            len(X), accuracy, brier, log_loss,
        )
        return {
            "status": "success",
            "samples_trained": int(len(X)),
            "validation_samples": int(len(oof_probs)),
            "validation_accuracy": round(accuracy, 4),
            "validation_brier_score": round(brier, 5),
            "validation_log_loss": round(log_loss, 5),
            "validation_total_mae": round(ou_mae, 3) if ou_mae is not None else None,
            "market_baseline": ({
                "samples": market_metrics["samples"],
                "brier_score": round(market_metrics["brier_score"], 5),
                "log_loss": round(market_metrics["log_loss"], 5),
                "accuracy": round(market_metrics["accuracy"], 4),
                "xgboost_on_same_games": {
                    "brier_score": round(market_metrics["xgboost_on_same_games"]["brier_score"], 5),
                    "log_loss": round(market_metrics["xgboost_on_same_games"]["log_loss"], 5),
                    "accuracy": round(market_metrics["xgboost_on_same_games"]["accuracy"], 4),
                },
            } if market_metrics else None),
            "latest_training_game_date": latest_game_day,
            "model_version": MODEL_VERSION,
            "model_path": str(MODELS_DIR),
        }

    def load_models(self) -> bool:
        if not XGB_AVAILABLE:
            return False
        ml_path = MODELS_DIR / "xgb_moneyline.json"
        ou_path = MODELS_DIR / "xgb_overunder.json"
        if not ml_path.exists():
            return False
        try:
            candidate_ml = xgb.Booster()
            candidate_ml.load_model(str(ml_path))
            candidate_ou = None
            if ou_path.exists():
                candidate_ou = xgb.Booster()
                candidate_ou.load_model(str(ou_path))
            metadata_path = MODELS_DIR / "training_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            if metadata.get("model_version") != MODEL_VERSION or metadata.get("features") != self.feature_names:
                logger.warning("Ignoring NFL XGBoost artifact with missing or incompatible feature metadata")
                return False
            self.model_ml = candidate_ml
            self.model_ou = candidate_ou
            self.loaded_training_metadata = metadata
            return True
        except Exception:
            logger.exception("Failed loading NFL XGBoost model artifacts")
            return False

    def predict(self, features: Dict[str, float]) -> Dict[str, Any]:
        if not XGB_AVAILABLE:
            return {"error": "NFL XGBoost dependencies are unavailable"}
        if self.model_ml is None and not self.load_models():
            return {"error": "No compatible NFL XGBoost model is trained from imported data"}
        matrix = self._features_to_matrix([features])
        dmatrix = xgb.DMatrix(matrix, feature_names=self.feature_names)
        home_probability = float(self.model_ml.predict(dmatrix)[0])
        total = float(self.model_ou.predict(dmatrix)[0]) if self.model_ou is not None else None
        result = {
            "home_win_probability": round(home_probability, 4),
            "away_win_probability": round(1 - home_probability, 4),
            "model_version": self.loaded_training_metadata.get("model_version", MODEL_VERSION),
            "training_samples": self.loaded_training_metadata.get("training_samples"),
            "latest_training_game_date": self.loaded_training_metadata.get("latest_training_game_date"),
        }
        if total is not None:
            result["predicted_total"] = round(total, 1)
        return result


_trainer: Optional[NFLXGBTrainer] = None


def get_trainer() -> NFLXGBTrainer:
    global _trainer
    if _trainer is None:
        _trainer = NFLXGBTrainer()
    return _trainer


async def train_nfl_model(epochs: int = 250) -> Dict[str, Any]:
    return await get_trainer().train(epochs)


async def predict_nfl_xgb(home_team: str, away_team: str, *_legacy_stats) -> Optional[Dict[str, Any]]:
    """Predict from current imported game history using the training feature builder."""
    trainer = get_trainer()
    try:
        features = await fetch_live_features(home_team, away_team)
        result = trainer.predict(features)
        if "error" not in result:
            result["model"] = "xgboost"
            result["home_team"] = home_team
            result["away_team"] = away_team
            result["features"] = features
            result["feature_source"] = "nightly imported NFL schedules and weekly player stats in PostgreSQL"
        return result
    except Exception as exc:
        logger.warning("NFL XGBoost prediction unavailable for %s vs %s: %s", home_team, away_team, exc)
        return {"model": "xgboost", "error": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(train_nfl_model()), indent=2))
