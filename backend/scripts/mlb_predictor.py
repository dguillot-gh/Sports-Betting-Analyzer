"""
MLB Game Prediction Service — Ensemble
========================================
Multi-model prediction combining:
  1. Pythagorean Expectation (baseline heuristic)
  2. XGBoost Moneyline model (P(home_win))
  3. XGBoost Spread model (P(home covers -1.5))
  4. LightGBM+XGBoost Totals ensemble (P(over))

Falls back to Pythagorean-only when ML models are not yet trained.
"""

import logging
import math
from datetime import datetime, date
from typing import Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import the mlb_scraper library (downloaded from github.com/tnestico/mlb_scraper)
# ---------------------------------------------------------------------------
try:
    from scripts.api_scraper import MLB_Scrape
    _mlb_scraper = MLB_Scrape()
    logger.info("mlb_scraper (api_scraper.py) loaded successfully")
except Exception as e:
    _mlb_scraper = None
    logger.warning(f"mlb_scraper not available: {e}")

# ---------------------------------------------------------------------------
# ML model singletons (lazy-loaded)
# ---------------------------------------------------------------------------
_ml_model = None
_spread_model = None
_totals_model = None
_models_loaded = False


def _load_ml_models():
    """Lazy-load trained ML models from disk."""
    global _ml_model, _spread_model, _totals_model, _models_loaded
    if _models_loaded:
        return

    try:
        from scripts.mlb_moneyline_model import load_moneyline_model
        _ml_model = load_moneyline_model()
        if _ml_model:
            logger.info("MLB moneyline model loaded")
    except Exception as e:
        logger.warning(f"Could not load moneyline model: {e}")

    try:
        from scripts.mlb_spread_model import load_spread_model
        _spread_model = load_spread_model()
        if _spread_model:
            logger.info("MLB spread model loaded")
    except Exception as e:
        logger.warning(f"Could not load spread model: {e}")

    try:
        from scripts.mlb_totals_model import load_totals_model
        _totals_model = load_totals_model()
        if _totals_model:
            logger.info("MLB totals ensemble loaded")
    except Exception as e:
        logger.warning(f"Could not load totals model: {e}")

    _models_loaded = True


def reload_models():
    """Force reload of ML models (e.g. after retraining)."""
    global _models_loaded
    _models_loaded = False
    _load_ml_models()


# MLB Pythagorean exponent (empirically derived)
PYTH_EXPONENT = 1.83
# League-average runs per game (approx 4.5 per team in modern MLB)
LEAGUE_AVG_RPG = 4.5

# Caches
_stats_cache: Dict[str, Dict] = {}
_stats_cache_ts: Optional[datetime] = None
_teams_cache = None
CACHE_TTL_MINUTES = 30

# ---------------------------------------------------------------------------
# Team name normalization (sportsbook names → MLB Stats API names)
# ---------------------------------------------------------------------------
_MLB_NAME_MAP = {
    "Athletics Athletics": "Athletics",
    "Oakland Athletics": "Athletics",
    "Sacramento Athletics": "Athletics",
    "Arizona D-backs": "Arizona Diamondbacks",
    "Chi White Sox": "Chicago White Sox",
    "Chi Cubs": "Chicago Cubs",
}

def normalize_mlb_team(name: str) -> str:
    """Normalize sportsbook team names to MLB Stats API canonical names."""
    if name in _MLB_NAME_MAP:
        return _MLB_NAME_MAP[name]
    # Handle doubled names like "Athletics Athletics" generically
    parts = name.split()
    if len(parts) >= 2 and parts[-1] == parts[-2]:
        return " ".join(parts[:-1])
    return name


# ---------------------------------------------------------------------------
# Team metadata via mlb_scraper
# ---------------------------------------------------------------------------
def _get_mlb_teams():
    """Use MLB_Scrape.get_teams() to build a team-name lookup."""
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache
    if _mlb_scraper is None:
        return {}
    try:
        teams_df = _mlb_scraper.get_teams()
        _teams_cache = {}
        for row in teams_df.iter_rows(named=True):
            full_name = row.get("city") or row.get("franchise") or ""
            abbr = row.get("abbreviation", "")
            team_id = row.get("team_id")
            if full_name:
                _teams_cache[full_name] = {"abbreviation": abbr, "team_id": team_id}
        logger.info(f"Loaded {len(_teams_cache)} MLB teams from mlb_scraper")
        return _teams_cache
    except Exception as e:
        logger.warning(f"mlb_scraper get_teams() failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Standings / stats from MLB Stats API
# ---------------------------------------------------------------------------
async def _fetch_mlb_standings() -> Dict[str, Dict]:
    """
    Fetch current MLB team standings from the public MLB Stats API.
    Returns a dict keyed by team full name with runs scored/allowed/win pct.
    """
    global _stats_cache, _stats_cache_ts

    now = datetime.utcnow()
    if _stats_cache and _stats_cache_ts and (now - _stats_cache_ts).total_seconds() < CACHE_TTL_MINUTES * 60:
        return _stats_cache

    season = now.year
    url = f"https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={season}&standingsTypes=regularSeason&hydrate=team"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch MLB standings: {e}")
        return _stats_cache

    stats: Dict[str, Dict] = {}

    for record in data.get("records", []):
        for entry in record.get("teamRecords", []):
            team_info = entry.get("team", {})
            team_name = team_info.get("name", "")
            wins = entry.get("wins", 0)
            losses = entry.get("losses", 0)
            games_played = wins + losses

            runs_scored = entry.get("runsScored", 0)
            runs_allowed = entry.get("runsAllowed", 0)

            if games_played == 0:
                continue

            stats[team_name] = {
                "wins": wins,
                "losses": losses,
                "games_played": games_played,
                "win_pct": wins / games_played if games_played else 0.5,
                "runs_scored": runs_scored,
                "runs_allowed": runs_allowed,
                "rpg": runs_scored / games_played,
                "rapg": runs_allowed / games_played,
            }

    teams_meta = _get_mlb_teams()
    for name, st in stats.items():
        meta = teams_meta.get(name, {})
        st["abbreviation"] = meta.get("abbreviation", "")
        st["mlb_team_id"] = meta.get("team_id")

    if stats:
        _stats_cache = stats
        _stats_cache_ts = now
        logger.info(f"Cached MLB standings for {len(stats)} teams")

    return stats


def _pyth_win_prob(home_rpg: float, home_rapg: float,
                   away_rpg: float, away_rapg: float,
                   home_advantage: float = 0.3):
    """
    Pythagorean Expectation matchup probability.
    Adjusts for home-field advantage (~54% home win rate in MLB).
    """
    home_expected = max(0.5, (LEAGUE_AVG_RPG * (home_rpg / LEAGUE_AVG_RPG) * (away_rapg / LEAGUE_AVG_RPG)) + home_advantage / 2)
    away_expected = max(0.5, (LEAGUE_AVG_RPG * (away_rpg / LEAGUE_AVG_RPG) * (home_rapg / LEAGUE_AVG_RPG)) - home_advantage / 2)

    prob = (home_expected ** PYTH_EXPONENT) / (
        (home_expected ** PYTH_EXPONENT) + (away_expected ** PYTH_EXPONENT)
    )
    return prob, home_expected, away_expected


def _implied_prob(odds: int) -> float:
    """Convert American odds to implied probability (0-1)."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def _edge_signal(edge_pct: float) -> str:
    """Determine betting signal from edge percentage."""
    if abs(edge_pct) >= 8.0:
        return "BET"
    elif abs(edge_pct) >= 4.0:
        return "LEAN"
    else:
        return "PASS"


async def analyze_mlb_matchup(
    home_team: str,
    away_team: str,
    spread: float = None,
    over_under: float = None,
    home_ml: int = None,
    away_ml: int = None,
    pool=None,
    home_sp_id: int = None,
    away_sp_id: int = None,
    venue_name: str = None,
    is_day_game: bool = False,
) -> Dict[str, Any]:
    """
    Predict an MLB game using the multi-model ensemble.
    Falls back to Pythagorean-only when ML models aren't available.
    Returns a prediction dict compatible with the frontend contract.
    """
    # Lazy-load ML models
    _load_ml_models()

    standings = await _fetch_mlb_standings()

    # Normalize team names from sportsbook to MLB Stats API format
    home_team_norm = normalize_mlb_team(home_team)
    away_team_norm = normalize_mlb_team(away_team)

    home_stats = standings.get(home_team_norm) or standings.get(home_team)
    away_stats = standings.get(away_team_norm) or standings.get(away_team)

    if not home_stats or not away_stats:
        for name, st in standings.items():
            if not home_stats and (home_team_norm.lower() in name.lower() or name.lower() in home_team_norm.lower()):
                home_stats = st
            if not away_stats and (away_team_norm.lower() in name.lower() or name.lower() in away_team_norm.lower()):
                away_stats = st

    if not home_stats or not away_stats:
        logger.warning(f"Missing MLB stats for {home_team} or {away_team}")
        return {
            "home_team": home_team,
            "away_team": away_team,
            "error": "Insufficient data",
            "description": "Team stats not found. Season may not have started yet.",
            "home_win_probability": 0.5,
            "away_win_probability": 0.5,
            "predicted_winner": home_team,
            "predicted_total": None,
            "has_value": False,
            "value_bets": [],
        }

    # ===== 1. Pythagorean prediction (always available) =====
    pyth_prob, home_expected, away_expected = _pyth_win_prob(
        home_stats["rpg"], home_stats["rapg"],
        away_stats["rpg"], away_stats["rapg"],
    )

    predicted_total = max(5.0, min(20.0, home_expected + away_expected))
    predicted_margin = home_expected - away_expected
    confidence = min(0.80, 0.5 + abs(predicted_margin) * 0.06)

    # Models sub-dict for multi-model display
    models: Dict[str, Any] = {
        "pythagorean": {
            "home_win_prob": round(pyth_prob, 4),
            "predicted_total": round(predicted_total, 1),
            "predicted_margin": round(predicted_margin, 1),
        }
    }

    # ===== 2. XGBoost models (if trained and feature data available) =====
    ml_prob = None
    spread_result = None
    totals_result = None

    features = None
    if pool and (_ml_model or _spread_model or _totals_model):
        try:
            from scripts.mlb_features import build_game_features, fill_missing_features
            raw_features = await build_game_features(
                pool, home_team, away_team,
                home_sp_id=home_sp_id,
                away_sp_id=away_sp_id,
                venue_name=venue_name,
                is_day_game=is_day_game,
            )
            features = fill_missing_features(raw_features)
        except Exception as e:
            logger.warning(f"Feature build failed for {home_team} vs {away_team}: {e}")

    if features and _ml_model:
        try:
            from scripts.mlb_moneyline_model import predict_moneyline
            ml_result = predict_moneyline(_ml_model, features)
            ml_prob = ml_result["home_win_prob"]
            models["moneyline_xgb"] = ml_result
        except Exception as e:
            logger.warning(f"Moneyline prediction failed: {e}")

    if features and _spread_model:
        try:
            from scripts.mlb_spread_model import predict_spread
            spread_result = predict_spread(_spread_model, features)
            models["spread_xgb"] = spread_result
        except Exception as e:
            logger.warning(f"Spread prediction failed: {e}")

    if features and _totals_model:
        try:
            from scripts.mlb_totals_model import predict_totals
            totals_result = predict_totals(_totals_model, features)
            models["totals_ensemble"] = totals_result
        except Exception as e:
            logger.warning(f"Totals prediction failed: {e}")

    # ===== 3. Ensemble blend =====
    if ml_prob is not None:
        # Weighted blend: 40% XGBoost + 30% Pythagorean + 30% regression to implied
        implied_home = _implied_prob(home_ml) if home_ml else 0.5
        ensemble_prob = 0.4 * ml_prob + 0.3 * pyth_prob + 0.3 * implied_home
        active_model = "ensemble"
    else:
        ensemble_prob = pyth_prob
        active_model = "pythagorean"

    # ===== 4. Build result (backward-compatible + new fields) =====
    result: Dict[str, Any] = {
        "home_team": home_team,
        "away_team": away_team,
        "predicted_winner": home_team if ensemble_prob > 0.5 else away_team,
        "home_win_probability": round(ensemble_prob, 3),
        "away_win_probability": round(1 - ensemble_prob, 3),
        "predicted_margin": round(predicted_margin, 1),
        "predicted_total": round(predicted_total, 1),
        "home_expected_runs": round(home_expected, 1),
        "away_expected_runs": round(away_expected, 1),
        "confidence": round(confidence, 2),
        "confidence_level": "high" if confidence >= 0.65 else "medium" if confidence >= 0.55 else "low",
        "model": active_model,
        "home_record": f"{home_stats['wins']}-{home_stats['losses']}",
        "away_record": f"{away_stats['wins']}-{away_stats['losses']}",
        # New: multi-model breakdown
        "models": models,
    }

    # ===== 5. Context info (if available) =====
    context = {}
    if home_sp_id or away_sp_id:
        if features:
            context["home_sp_era"] = features.get("home_sp_ERA")
            context["away_sp_era"] = features.get("away_sp_ERA")
        context["park_factor"] = features.get("park_factor") if features else None
    if venue_name:
        context["venue"] = venue_name
    if context:
        result["context"] = context

    # ===== 6. Moneyline edge + signal =====
    if home_ml and away_ml:
        home_implied = _implied_prob(home_ml)
        away_implied = _implied_prob(away_ml)
        home_edge = ensemble_prob - home_implied
        edge_pct = round(home_edge * 100, 1)

        result["home_implied_prob"] = round(home_implied, 3)
        result["away_implied_prob"] = round(away_implied, 3)
        result["home_ml_edge"] = edge_pct
        result["ml_pick"] = home_team if home_edge > 0 else away_team
        result["ml_signal"] = _edge_signal(edge_pct)
        result["ml_value"] = abs(home_edge) >= 0.05

        # EV calculation
        if home_edge > 0 and home_ml:
            decimal_odds = (home_ml / 100) + 1 if home_ml > 0 else (100 / abs(home_ml)) + 1
            result["ev_home"] = round((ensemble_prob * (decimal_odds - 1) - (1 - ensemble_prob)) * 100, 1)
        else:
            result["ev_home"] = None

        if home_edge < 0 and away_ml:
            decimal_odds = (away_ml / 100) + 1 if away_ml > 0 else (100 / abs(away_ml)) + 1
            result["ev_away"] = round(((1 - ensemble_prob) * (decimal_odds - 1) - ensemble_prob) * 100, 1)
        else:
            result["ev_away"] = None

    # ===== 7. Spread analysis =====
    if spread is not None:
        line_margin = -spread
        model_edge = predicted_margin - line_margin
        result["spread"] = spread
        result["spread_pick"] = "HOME" if predicted_margin > line_margin else "AWAY"
        result["spread_edge"] = round(model_edge, 1)
        result["spread_value"] = abs(model_edge) >= 0.5

        # XGBoost spread signal
        if spread_result:
            result["spread_xgb_pick"] = spread_result["pick"]
            result["spread_signal"] = _edge_signal(
                (spread_result["home_cover_prob"] - 0.5) * 100
            )
        else:
            result["spread_signal"] = _edge_signal(model_edge * 10)

    # ===== 8. Over/Under analysis =====
    if over_under is not None:
        ou_edge = predicted_total - over_under
        result["over_under"] = over_under
        result["ou_pick"] = "OVER" if predicted_total > over_under else "UNDER"
        result["ou_edge"] = round(ou_edge, 1)
        result["ou_value"] = abs(ou_edge) >= 1.0

        # Totals ensemble signal
        if totals_result:
            result["ou_ensemble_pick"] = totals_result["pick"]
            result["ou_signal"] = _edge_signal(
                (totals_result["over_prob"] - 0.5) * 100
            )
        else:
            result["ou_signal"] = _edge_signal(ou_edge * 5)

    # ===== 9. Value summary with signals =====
    value_bets = []
    if result.get("ml_value"):
        signal = result.get("ml_signal", "")
        value_bets.append(f"ML: {result['ml_pick']} ({signal})")
    if result.get("spread_value"):
        signal = result.get("spread_signal", "")
        value_bets.append(f"Spread: {result['spread_pick']} ({signal})")
    if result.get("ou_value"):
        signal = result.get("ou_signal", "")
        value_bets.append(f"Total: {result['ou_pick']} ({signal})")

    result["value_bets"] = value_bets
    result["has_value"] = len(value_bets) > 0

    return result
