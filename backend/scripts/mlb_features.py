"""
MLB Feature Engine
===================
Builds a ~60-feature vector for each MLB game, suitable for XGBoost/LightGBM models.

Feature categories:
  - Team-level: WPct, PythWPct, RS/G, RA/G, ERA, WHIP, K9, BA, SLG, fielding, baserunning
  - Starting pitcher: SP ERA/WHIP/K9, SP vs opponent
  - Context: park factor, weather (temp, wind), day/night, rest days
  - Matchup: K/BB rates, platoon, bullpen fatigue, differentials

Data sources:
  - mlb_team_stats table (populated by mlb_stats_collector)
  - mlb_pitcher_stats table
  - mlb_context.py (park factors, weather)
  - mlb_stats_collector.fetch_todays_probable_pitchers()
"""

import logging
from datetime import date, datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# FEATURE COLUMN DEFINITIONS
# ============================================================================

TEAM_FEATURES = [
    "home_WPct", "away_WPct", "WPct_diff",
    "home_PythWPct", "away_PythWPct", "PythWPct_diff",
    "home_RS_G", "home_RA_G", "away_RS_G", "away_RA_G",
    "home_RD_G", "away_RD_G",
    "home_ERA", "away_ERA", "ERA_diff",
    "home_WHIP", "away_WHIP", "WHIP_diff",
    "home_K9", "away_K9",
    "home_BA", "away_BA",
    "home_SLG", "away_SLG",
    "home_pyth_diff", "away_pyth_diff",
]

SP_FEATURES = [
    "home_sp_ERA", "away_sp_ERA", "sp_ERA_gap",
    "home_sp_WHIP", "away_sp_WHIP",
    "home_sp_K9", "away_sp_K9",
    "home_sp_vs_opp_ERA", "away_sp_vs_opp_ERA",
    "home_sp_vs_opp_K9", "away_sp_vs_opp_K9",
]

CONTEXT_FEATURES = [
    "temp", "windspeed", "is_day",
    "wind_out", "wind_in", "dome_flag",
    "temp_cold", "temp_hot", "overcast_flag",
    "park_factor",
    "home_days_rest", "away_days_rest",
    "home_back_to_back", "away_back_to_back",
    "is_doubleheader",
]

MATCHUP_FEATURES = [
    "home_K_rate", "away_K_rate",
    "home_BB_rate", "away_BB_rate",
    "home_K_BB_ratio", "away_K_BB_ratio",
    "home_day_WPct", "away_day_WPct",
    "home_night_WPct", "away_night_WPct",
    "home_errors_per_g", "away_errors_per_g",
    "home_dp_rate", "away_dp_rate",
    "home_def_efficiency", "away_def_efficiency",
    "home_sb_success_rate", "away_sb_success_rate",
    "home_sb_rate", "away_sb_rate",
    "home_platoon_adv", "away_platoon_adv",
    "platoon_adv_gap",
    "matchup_k_delta",
]

TOTALS_EXTRA = [
    "home_lob_per_g", "away_lob_per_g",
    "exp_total",
]

MONEYLINE_FEATURES: List[str] = TEAM_FEATURES + SP_FEATURES + CONTEXT_FEATURES + MATCHUP_FEATURES
SPREAD_FEATURES: List[str] = MONEYLINE_FEATURES  # same inputs, different target
TOTALS_FEATURES: List[str] = MONEYLINE_FEATURES + TOTALS_EXTRA
ALL_FEATURE_COLS: List[str] = list(dict.fromkeys(TOTALS_FEATURES))


# ============================================================================
# BUILD FEATURE VECTOR FOR A SINGLE GAME
# ============================================================================

async def build_game_features(
    pool,
    home_team: str,
    away_team: str,
    season: int = None,
    home_sp_id: int = None,
    away_sp_id: int = None,
    venue_name: str = None,
    game_date: date = None,
    is_day_game: bool = False,
    is_doubleheader: bool = False,
) -> Dict[str, Any]:
    """
    Build the full feature vector for one MLB game.

    Returns a dict with all feature columns (missing values set to None).
    """
    from scripts.mlb_stats_collector import get_team_stats, get_pitcher_by_id
    from scripts.mlb_context import get_park_factor, is_dome, fetch_game_weather

    season = season or datetime.utcnow().year
    game_date = game_date or date.today()
    features: Dict[str, Any] = {}

    # ----- Team stats -----
    from scripts.mlb_predictor import normalize_mlb_team
    home_norm = normalize_mlb_team(home_team)
    away_norm = normalize_mlb_team(away_team)

    home_ts = await get_team_stats(pool, season, home_norm) or await get_team_stats(pool, season, home_team)
    away_ts = await get_team_stats(pool, season, away_norm) or await get_team_stats(pool, season, away_team)

    if home_ts and away_ts:
        features.update(_build_team_features(home_ts, away_ts))
    else:
        logger.warning(f"Missing team stats for {home_team} ({home_norm}) or {away_team} ({away_norm})")

    # ----- Starting pitcher stats -----
    home_sp = await get_pitcher_by_id(pool, season, home_sp_id) if home_sp_id else None
    away_sp = await get_pitcher_by_id(pool, season, away_sp_id) if away_sp_id else None
    features.update(_build_sp_features(home_sp, away_sp, home_ts, away_ts))

    # ----- Context features -----
    pf = get_park_factor(venue_name) if venue_name else 1.0
    weather = await fetch_game_weather(venue_name, game_date) if venue_name else {}

    features["park_factor"] = pf
    features["temp"] = weather.get("temp_f", 72.0)
    features["windspeed"] = weather.get("windspeed_mph", 5.0)
    features["is_day"] = 1.0 if is_day_game else 0.0
    features["wind_out"] = 1.0 if weather.get("wind_out") else 0.0
    features["wind_in"] = 1.0 if weather.get("wind_in") else 0.0
    features["dome_flag"] = 1.0 if weather.get("is_dome") or is_dome(venue_name or "") else 0.0
    features["temp_cold"] = 1.0 if weather.get("temp_cold") else 0.0
    features["temp_hot"] = 1.0 if weather.get("temp_hot") else 0.0
    features["overcast_flag"] = 1.0 if weather.get("is_overcast") else 0.0
    features["is_doubleheader"] = 1.0 if is_doubleheader else 0.0

    # Rest days — would need schedule data; default to 1
    features["home_days_rest"] = 1.0
    features["away_days_rest"] = 1.0
    features["home_back_to_back"] = 0.0
    features["away_back_to_back"] = 0.0

    # ----- Matchup features -----
    features.update(_build_matchup_features(home_ts, away_ts, home_sp, away_sp))

    # ----- Totals extras -----
    features["home_lob_per_g"] = home_ts.get("lob_per_game") if home_ts else None
    features["away_lob_per_g"] = away_ts.get("lob_per_game") if away_ts else None
    features["exp_total"] = (
        (features.get("home_RS_G") or 4.5) + (features.get("away_RS_G") or 4.5)
    )

    return features


# ============================================================================
# FEATURE BUILDING HELPERS
# ============================================================================

def _build_team_features(home: Dict, away: Dict) -> Dict[str, Any]:
    """Build team-level differential features."""
    f = {}

    f["home_WPct"] = home.get("win_pct")
    f["away_WPct"] = away.get("win_pct")
    f["WPct_diff"] = _safe_diff(f["home_WPct"], f["away_WPct"])

    f["home_PythWPct"] = home.get("pyth_win_pct")
    f["away_PythWPct"] = away.get("pyth_win_pct")
    f["PythWPct_diff"] = _safe_diff(f["home_PythWPct"], f["away_PythWPct"])

    f["home_RS_G"] = home.get("rs_per_game")
    f["home_RA_G"] = home.get("ra_per_game")
    f["away_RS_G"] = away.get("rs_per_game")
    f["away_RA_G"] = away.get("ra_per_game")
    f["home_RD_G"] = home.get("run_diff_per_game")
    f["away_RD_G"] = away.get("run_diff_per_game")

    f["home_ERA"] = home.get("era")
    f["away_ERA"] = away.get("era")
    f["ERA_diff"] = _safe_diff(f["away_ERA"], f["home_ERA"])  # positive = home advantage

    f["home_WHIP"] = home.get("whip")
    f["away_WHIP"] = away.get("whip")
    f["WHIP_diff"] = _safe_diff(f["away_WHIP"], f["home_WHIP"])

    f["home_K9"] = home.get("k9")
    f["away_K9"] = away.get("k9")

    f["home_BA"] = home.get("batting_avg")
    f["away_BA"] = away.get("batting_avg")
    f["home_SLG"] = home.get("slg")
    f["away_SLG"] = away.get("slg")

    # Pythagorean diff = actual W% - Pythagorean W% (luck factor)
    f["home_pyth_diff"] = _safe_diff(f["home_WPct"], f["home_PythWPct"])
    f["away_pyth_diff"] = _safe_diff(f["away_WPct"], f["away_PythWPct"])

    return f


def _build_sp_features(
    home_sp: Optional[Dict],
    away_sp: Optional[Dict],
    home_ts: Optional[Dict],
    away_ts: Optional[Dict],
) -> Dict[str, Any]:
    """Build starting pitcher features with team-average fallbacks."""
    f = {}

    # Home SP
    f["home_sp_ERA"] = home_sp.get("era") if home_sp else (home_ts.get("era") if home_ts else None)
    f["home_sp_WHIP"] = home_sp.get("whip") if home_sp else (home_ts.get("whip") if home_ts else None)
    f["home_sp_K9"] = home_sp.get("k9") if home_sp else (home_ts.get("k9") if home_ts else None)

    # Away SP
    f["away_sp_ERA"] = away_sp.get("era") if away_sp else (away_ts.get("era") if away_ts else None)
    f["away_sp_WHIP"] = away_sp.get("whip") if away_sp else (away_ts.get("whip") if away_ts else None)
    f["away_sp_K9"] = away_sp.get("k9") if away_sp else (away_ts.get("k9") if away_ts else None)

    f["sp_ERA_gap"] = _safe_diff(f["away_sp_ERA"], f["home_sp_ERA"])

    # SP vs opponent — will be populated when we have that data
    f["home_sp_vs_opp_ERA"] = None
    f["away_sp_vs_opp_ERA"] = None
    f["home_sp_vs_opp_K9"] = None
    f["away_sp_vs_opp_K9"] = None

    return f


def _build_matchup_features(
    home_ts: Optional[Dict],
    away_ts: Optional[Dict],
    home_sp: Optional[Dict],
    away_sp: Optional[Dict],
) -> Dict[str, Any]:
    """Build matchup-specific features."""
    f = {}

    h = home_ts or {}
    a = away_ts or {}

    # Plate discipline
    f["home_K_rate"] = h.get("k_rate")
    f["away_K_rate"] = a.get("k_rate")
    f["home_BB_rate"] = h.get("bb_rate")
    f["away_BB_rate"] = a.get("bb_rate")
    f["home_K_BB_ratio"] = h.get("k_bb_ratio")
    f["away_K_BB_ratio"] = a.get("k_bb_ratio")

    # Day/night splits
    f["home_day_WPct"] = h.get("day_win_pct")
    f["away_day_WPct"] = a.get("day_win_pct")
    f["home_night_WPct"] = h.get("night_win_pct")
    f["away_night_WPct"] = a.get("night_win_pct")

    # Fielding
    f["home_errors_per_g"] = h.get("errors_per_game")
    f["away_errors_per_g"] = a.get("errors_per_game")
    f["home_dp_rate"] = h.get("dp_rate")
    f["away_dp_rate"] = a.get("dp_rate")
    f["home_def_efficiency"] = h.get("def_efficiency")
    f["away_def_efficiency"] = a.get("def_efficiency")

    # Baserunning
    f["home_sb_success_rate"] = h.get("sb_success_rate")
    f["away_sb_success_rate"] = a.get("sb_success_rate")
    f["home_sb_rate"] = h.get("sb_rate")
    f["away_sb_rate"] = a.get("sb_rate")

    # Platoon advantage (1 if SP throws opposite of team's dominant hand)
    home_sp_hand = (home_sp.get("throws") or "R") if home_sp else "R"
    away_sp_hand = (away_sp.get("throws") or "R") if away_sp else "R"
    # Simplified: left-handed SPs are rarer, so facing one is an advantage for teams
    f["home_platoon_adv"] = 1.0 if away_sp_hand == "L" else 0.0
    f["away_platoon_adv"] = 1.0 if home_sp_hand == "L" else 0.0
    f["platoon_adv_gap"] = f["home_platoon_adv"] - f["away_platoon_adv"]

    # Matchup K delta: away SP K9 vs home team K rate, and vice versa
    away_sp_k9 = f.get("away_sp_K9") or 0
    home_sp_k9 = f.get("home_sp_K9") or 0
    home_k_rate = (h.get("k_rate") or 0.2) * 27  # rough K/game
    away_k_rate = (a.get("k_rate") or 0.2) * 27
    f["matchup_k_delta"] = (away_sp_k9 - home_k_rate) - (home_sp_k9 - away_k_rate)

    return f


def _safe_diff(a, b) -> Optional[float]:
    """Return a - b, or None if either is None."""
    if a is not None and b is not None:
        return round(a - b, 4)
    return None


# ============================================================================
# CONVERT FEATURES DICT TO ORDERED ARRAY (for model input)
# ============================================================================

def features_to_array(features: Dict[str, Any], feature_cols: List[str]) -> List[Optional[float]]:
    """Convert feature dict to ordered list matching model's expected columns."""
    return [features.get(col) for col in feature_cols]


def fill_missing_features(features: Dict[str, Any], defaults: Dict[str, float] = None) -> Dict[str, Any]:
    """Fill None values with defaults (league averages)."""
    league_defaults = {
        "home_WPct": 0.5, "away_WPct": 0.5, "WPct_diff": 0.0,
        "home_PythWPct": 0.5, "away_PythWPct": 0.5, "PythWPct_diff": 0.0,
        "home_RS_G": 4.5, "home_RA_G": 4.5, "away_RS_G": 4.5, "away_RA_G": 4.5,
        "home_RD_G": 0.0, "away_RD_G": 0.0,
        "home_ERA": 4.20, "away_ERA": 4.20, "ERA_diff": 0.0,
        "home_WHIP": 1.30, "away_WHIP": 1.30, "WHIP_diff": 0.0,
        "home_K9": 8.5, "away_K9": 8.5,
        "home_BA": 0.250, "away_BA": 0.250,
        "home_SLG": 0.400, "away_SLG": 0.400,
        "home_pyth_diff": 0.0, "away_pyth_diff": 0.0,
        "home_sp_ERA": 4.20, "away_sp_ERA": 4.20, "sp_ERA_gap": 0.0,
        "home_sp_WHIP": 1.30, "away_sp_WHIP": 1.30,
        "home_sp_K9": 8.5, "away_sp_K9": 8.5,
        "home_sp_vs_opp_ERA": 4.20, "away_sp_vs_opp_ERA": 4.20,
        "home_sp_vs_opp_K9": 8.5, "away_sp_vs_opp_K9": 8.5,
        "temp": 72.0, "windspeed": 5.0, "is_day": 0.0,
        "wind_out": 0.0, "wind_in": 0.0, "dome_flag": 0.0,
        "temp_cold": 0.0, "temp_hot": 0.0, "overcast_flag": 0.0,
        "park_factor": 1.0,
        "home_days_rest": 1.0, "away_days_rest": 1.0,
        "home_back_to_back": 0.0, "away_back_to_back": 0.0,
        "is_doubleheader": 0.0,
        "home_K_rate": 0.22, "away_K_rate": 0.22,
        "home_BB_rate": 0.08, "away_BB_rate": 0.08,
        "home_K_BB_ratio": 2.75, "away_K_BB_ratio": 2.75,
        "home_day_WPct": 0.5, "away_day_WPct": 0.5,
        "home_night_WPct": 0.5, "away_night_WPct": 0.5,
        "home_errors_per_g": 0.5, "away_errors_per_g": 0.5,
        "home_dp_rate": 0.5, "away_dp_rate": 0.5,
        "home_def_efficiency": 0.97, "away_def_efficiency": 0.97,
        "home_sb_success_rate": 0.75, "away_sb_success_rate": 0.75,
        "home_sb_rate": 0.5, "away_sb_rate": 0.5,
        "home_platoon_adv": 0.0, "away_platoon_adv": 0.0,
        "platoon_adv_gap": 0.0,
        "matchup_k_delta": 0.0,
        "home_lob_per_g": 6.0, "away_lob_per_g": 6.0,
        "exp_total": 9.0,
    }
    if defaults:
        league_defaults.update(defaults)

    filled = {}
    for k, v in features.items():
        if v is None and k in league_defaults:
            filled[k] = league_defaults[k]
        else:
            filled[k] = v

    # Ensure all expected columns exist
    for col in ALL_FEATURE_COLS:
        if col not in filled:
            filled[col] = league_defaults.get(col, 0.0)

    return filled
