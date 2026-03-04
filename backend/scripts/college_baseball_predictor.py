"""
College Baseball Game Prediction Service
Analyzes team statistics to predict game outcomes and over/under.
Uses Pythagorean Expectation as baseline and XGBoost for enhanced modeling.
"""

import logging
import os
import json
import math
import re
from difflib import get_close_matches
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from pathlib import Path

import pandas as pd
import numpy as np

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer
except ImportError:
    CollegeBaseballXGBTrainer = None

logger = logging.getLogger(__name__)

# Map sportsbook names to Odds API format
SPORTSBOOK_MAP = {
    "fanduel": "fanduel",
    "draftkings": "draftkings",
    "betmgm": "betmgm",
    "pointsbet": "pointsbetus",
    "caesars": "williamhill_us",
}

# Explicit aliases: Odds API name fragment -> NCAA base name (without conference)
# Handles cases where fuzzy matching alone can't bridge the gap.
ODDS_TO_NCAA_ALIASES = {
    "florida int'l": "FIU",
    "florida international": "FIU",
    "western kentucky": "Western Ky.",
    "oklahoma state": "Oklahoma St.",
    "oklahoma st": "Oklahoma St.",
    "missouri state": "Missouri St.",
    "missouri st": "Missouri St.",
    "mississippi state": "Mississippi St.",
    "mississippi st": "Mississippi St.",
    "nc state": "NC State",
    "north carolina state": "NC State",
    "central arkansas": "Central Ark.",
    "kent state": "Kent St.",
    "kent st": "Kent St.",
    "ball state": "Ball St.",
    "ball st": "Ball St.",
    "penn state": "Penn St.",
    "penn st": "Penn St.",
    "arizona state": "Arizona St.",
    "arizona st": "Arizona St.",
    "florida state": "Florida St.",
    "florida st": "Florida St.",
    "oregon state": "Oregon St.",
    "oregon st": "Oregon St.",
    "michigan state": "Michigan St.",
    "michigan st": "Michigan St.",
    "jacksonville state": "Jacksonville St.",
    "jacksonville st": "Jacksonville St.",
    "kansas state": "Kansas St.",
    "kansas st": "Kansas St.",
    "wright state": "Wright St.",
    "wright st": "Wright St.",
    "sacramento state": "Sacramento St.",
    "sacramento st": "Sacramento St.",
    "murray state": "Murray St.",
    "murray st": "Murray St.",
    "kennesaw state": "Kennesaw St.",
    "kennesaw st": "Kennesaw St.",
    "southeast missouri": "Southeast Mo. St.",
    "southeastern louisiana": "Southeastern La.",
    "northwestern state": "Northwestern St.",
    "eastern illinois": "Eastern Ill.",
    "southern illinois": "Southern Ill.",
    "southern miss": "Southern Miss.",
    "south florida": "South Fla.",
    "florida atlantic": "Fla. Atlantic",
    "fau": "Fla. Atlantic",
    "charleston southern": "Charleston So.",
    "northern kentucky": "Northern Ky.",
    "central connecticut": "Central Conn. St.",
    "boston college": "Boston College",
    "usc": "Southern California",
    "ole miss": "Ole Miss",
    "lsu": "LSU",
    "ucf": "UCF",
    "byu": "BYU",
    "tcu": "TCU",
    "utsa": "UTSA",
    "uconn": "UConn",
    "fiu": "FIU",
    "liu": "LIU",
    "unlv": "UNLV",
}

# XGBoost stat-based feature names (must match trainer)
STAT_XGB_FEATURES = [
    'home_rpg', 'home_rapg', 'home_avg', 'home_obp', 'home_slg',
    'home_era', 'home_whip', 'home_k9',
    'away_rpg', 'away_rapg', 'away_avg', 'away_obp', 'away_slg',
    'away_era', 'away_whip', 'away_k9',
    'is_home'
]


def _decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def _safe_float(val, default=0.0) -> float:
    """Safely convert a value to float."""
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (ValueError, TypeError):
        return default


def _find_data_dir() -> Path:
    """Locate the baseball data directory."""
    data_dir = Path("/app/data/baseball/stats")
    if not data_dir.exists():
        data_dir = Path(__file__).parent.parent / "data" / "baseball" / "stats"
    return data_dir


class CollegeBaseballPredictor:
    """
    College baseball predictor using team statistics.
    Two-layer model:
      1) Pythagorean Expectation (always available when CSV stats exist)
      2) XGBoost (when trained models exist — stat-based and/or rolling-DB-based)
    """

    def __init__(self, db_connection=None):
        self.db = db_connection
        self._team_stats_cache: Dict[str, Dict] = {}
        self._team_name_map: Dict[str, str] = {}
        self.LEAGUE_AVG_RUNS = 6.5  # D1 college baseball league average

        # XGBoost model slots
        self.model_ml = None        # Classifier: home win prob
        self.model_ou = None        # Regressor: total runs
        self.model_stat_ml = None   # Stat-based classifier
        self.model_stat_ou = None   # Stat-based regressor
        self.use_xgb = False
        self.use_stat_xgb = False

        if xgb:
            self._load_xgb_models()

    def _load_xgb_models(self):
        """Load XGBoost models from disk."""
        models_dir = Path("models/college_baseball")
        if not models_dir.exists():
            models_dir = Path(__file__).parent.parent / "models" / "college_baseball"

        # Rolling-stats models (DB-trained)
        ml_path = models_dir / "cbb_xgb_classifier.json"
        ou_path = models_dir / "cbb_xgb_regressor.json"
        if ml_path.exists() and ou_path.exists():
            try:
                self.model_ml = xgb.XGBClassifier()
                self.model_ml.load_model(str(ml_path))
                self.model_ou = xgb.XGBRegressor()
                self.model_ou.load_model(str(ou_path))
                self.use_xgb = True
                logger.info("Loaded rolling-stats XGBoost models")
            except Exception as e:
                logger.warning(f"Failed to load rolling-stats XGBoost models: {e}")

        # Stat-based models (CSV-trained)
        stat_ml_path = models_dir / "cbb_stat_xgb_classifier.json"
        stat_ou_path = models_dir / "cbb_stat_xgb_regressor.json"
        if stat_ml_path.exists() and stat_ou_path.exists():
            try:
                self.model_stat_ml = xgb.XGBClassifier()
                self.model_stat_ml.load_model(str(stat_ml_path))
                self.model_stat_ou = xgb.XGBRegressor()
                self.model_stat_ou.load_model(str(stat_ou_path))
                self.use_stat_xgb = True
                logger.info("Loaded stat-based XGBoost models")
            except Exception as e:
                logger.warning(f"Failed to load stat-based XGBoost models: {e}")

    # ------------------------------------------------------------------
    # Team stat aggregation from per-player CSVs
    # ------------------------------------------------------------------

    def _resolve_team_id(self, team_name: str) -> str:
        """Resolve a mascot-based team name to the NCAA team_id used for CSVs.
        
        Strategy order:
        1. Cache hit
        2. Explicit alias table (ODDS_TO_NCAA_ALIASES)
        3. Direct match against NCAA names (without conference)
        4. Drop mascot (last word) and match
        5. Fuzzy match full input
        6. Fuzzy match without mascot
        7. Fallback to sanitized input
        """
        if team_name in self._team_name_map:
            return self._team_name_map[team_name]

        data_dir = _find_data_dir()
        teams_file = data_dir.parent / "teams_d1.json"
        if not teams_file.exists():
            teams_file = Path("/app/data/baseball/teams_d1.json")

        if teams_file.exists():
            try:
                with open(teams_file, "r") as f:
                    teams_data = json.load(f)
                
                # Build mapping: NCAA base name (no conference) -> team_id
                valid_ids = {}
                for t in teams_data:
                    ncaa_name = t.get("ncaa_name", "")
                    t_id = t.get("team_id", "")
                    clean_name = re.sub(r'\s*\(.*?\)', '', ncaa_name).strip()
                    valid_ids[clean_name] = t_id

                def _cache_and_return(resolved_id):
                    self._team_name_map[team_name] = resolved_id
                    return resolved_id

                clean_input = re.sub(r'\s*\(.*?\)', '', team_name).strip()

                # --- Step 1: Alias table lookup ---
                input_lower = clean_input.lower()
                # Check full input (without mascot variants)
                for alias_key, ncaa_name in ODDS_TO_NCAA_ALIASES.items():
                    if input_lower == alias_key or input_lower.startswith(alias_key + " "):
                        if ncaa_name in valid_ids:
                            return _cache_and_return(valid_ids[ncaa_name])

                # Also try dropping the last word (mascot) and checking aliases
                parts = clean_input.split()
                if len(parts) > 1:
                    no_mascot_lower = " ".join(parts[:-1]).lower()
                    for alias_key, ncaa_name in ODDS_TO_NCAA_ALIASES.items():
                        if no_mascot_lower == alias_key:
                            if ncaa_name in valid_ids:
                                return _cache_and_return(valid_ids[ncaa_name])

                # --- Step 2: Direct match ---
                if clean_input in valid_ids:
                    return _cache_and_return(valid_ids[clean_input])

                # --- Step 3: Drop mascot, direct match ---
                if len(parts) > 1:
                    no_mascot = " ".join(parts[:-1])
                    if no_mascot in valid_ids:
                        return _cache_and_return(valid_ids[no_mascot])

                # --- Step 4: Fuzzy match (full input) ---
                choices = list(valid_ids.keys())
                matches = get_close_matches(clean_input, choices, n=1, cutoff=0.55)
                if matches:
                    return _cache_and_return(valid_ids[matches[0]])

                # --- Step 5: Fuzzy match (without mascot) ---
                if len(parts) > 1:
                    no_mascot = " ".join(parts[:-1])
                    matches = get_close_matches(no_mascot, choices, n=1, cutoff=0.55)
                    if matches:
                        return _cache_and_return(valid_ids[matches[0]])

                # --- Step 6: Try dropping TWO last words (e.g. "Golden Panthers") ---
                if len(parts) > 2:
                    no_mascot_2 = " ".join(parts[:-2])
                    if no_mascot_2 in valid_ids:
                        return _cache_and_return(valid_ids[no_mascot_2])
                    matches = get_close_matches(no_mascot_2, choices, n=1, cutoff=0.55)
                    if matches:
                        return _cache_and_return(valid_ids[matches[0]])

                logger.warning(f"Could not resolve team: '{team_name}' -> tried '{clean_input}'")

            except Exception as e:
                logger.warning(f"Error resolving team_id via teams_d1.json: {e}")

        # Fallback to the simplistic mapping
        safe_id = "".join([c if c.isalnum() else "_" for c in team_name]).strip("_")
        self._team_name_map[team_name] = safe_id
        return safe_id

    async def get_team_stats(self, team_name: str) -> Optional[Dict[str, float]]:
        """
        Aggregate team statistics from per-player batting and pitching CSVs.
        Returns a dict with runs_per_game, runs_allowed, win_pct, plus
        extended rate stats for XGBoost features.  Returns None if data
        is unavailable.
        """
        if team_name in self._team_stats_cache:
            return self._team_stats_cache[team_name]

        try:
            safe_id = self._resolve_team_id(team_name)
            data_dir = _find_data_dir()

            batting_file = data_dir / f"{safe_id}_batting.csv"
            pitching_file = data_dir / f"{safe_id}_pitching.csv"

            if not batting_file.exists() and not pitching_file.exists():
                logger.debug(f"No CSV files found for {team_name} (tried {safe_id})")
                return None

            # ---- Batting aggregation ----
            total_runs = 0
            team_games = 0
            team_avg = 0.0
            team_obp = 0.0
            team_slg = 0.0
            team_ops = 0.0
            team_wrc_plus = 0.0
            team_hr = 0

            if batting_file.exists():
                df_bat = pd.read_csv(batting_file)
                df_bat.columns = [c.lower().strip() for c in df_bat.columns]

                if not df_bat.empty:
                    # Total runs scored = sum of all player runs
                    total_runs = _safe_float(df_bat['r'].sum()) if 'r' in df_bat.columns else 0

                    # Team games: use 90th percentile of player games played
                    if 'g' in df_bat.columns:
                        g_series = pd.to_numeric(df_bat['g'], errors='coerce').dropna()
                        if not g_series.empty:
                            team_games = max(int(g_series.quantile(0.90)), int(g_series.max()))

                    # Weighted-average rate stats (weight by plate appearances)
                    if 'pa' in df_bat.columns:
                        pa = pd.to_numeric(df_bat['pa'], errors='coerce').fillna(0)
                        total_pa = pa.sum()
                        if total_pa > 0:
                            def _wavg(col):
                                if col in df_bat.columns:
                                    vals = pd.to_numeric(df_bat[col], errors='coerce').fillna(0)
                                    return float((vals * pa).sum() / total_pa)
                                return 0.0

                            team_avg = _wavg('avg')
                            team_obp = _wavg('obp')
                            team_slg = _wavg('slg')
                            team_ops = _wavg('ops')
                            team_wrc_plus = _wavg('wrc+')

                    # Total HR
                    if 'hr' in df_bat.columns:
                        team_hr = int(_safe_float(df_bat['hr'].sum()))

            # ---- Pitching aggregation ----
            total_runs_allowed = 0
            team_era = 0.0
            team_whip = 0.0
            team_fip = 0.0
            team_k9 = 0.0
            team_bb9 = 0.0
            team_pitch_ip = 0.0
            pitch_wins = 0
            pitch_losses = 0

            if pitching_file.exists():
                df_pitch = pd.read_csv(pitching_file)
                df_pitch.columns = [c.lower().strip() for c in df_pitch.columns]

                if not df_pitch.empty:
                    # Total runs allowed
                    if 'r' in df_pitch.columns:
                        total_runs_allowed = _safe_float(df_pitch['r'].sum())
                    elif 'er' in df_pitch.columns:
                        # Fallback: earned runs * 1.15 to approximate total runs
                        total_runs_allowed = _safe_float(df_pitch['er'].sum()) * 1.15

                    # Total IP for weighting
                    if 'ip' in df_pitch.columns:
                        ip_series = pd.to_numeric(df_pitch['ip'], errors='coerce').fillna(0)
                        team_pitch_ip = float(ip_series.sum())

                    # If we didn't get games from batting, estimate from IP
                    if team_games == 0 and team_pitch_ip > 0:
                        team_games = max(1, int(team_pitch_ip / 9))

                    # Weighted-average rate stats (weight by IP)
                    if team_pitch_ip > 0 and 'ip' in df_pitch.columns:
                        ip = pd.to_numeric(df_pitch['ip'], errors='coerce').fillna(0)

                        def _pwavg(col):
                            if col in df_pitch.columns:
                                vals = pd.to_numeric(df_pitch[col], errors='coerce').fillna(0)
                                return float((vals * ip).sum() / team_pitch_ip)
                            return 0.0

                        team_era = _pwavg('era')
                        team_whip = _pwavg('whip')
                        team_fip = _pwavg('fip') if 'fip' in df_pitch.columns else team_era
                        team_k9 = _pwavg('k/9')
                        team_bb9 = _pwavg('bb/9')

                    # Win/Loss record
                    if 'w' in df_pitch.columns:
                        pitch_wins = int(_safe_float(df_pitch['w'].sum()))
                    if 'l' in df_pitch.columns:
                        pitch_losses = int(_safe_float(df_pitch['l'].sum()))

            # ---- Derived stats ----
            if team_games < 1:
                logger.warning(f"Could not determine games played for {team_name}")
                return None

            rpg = total_runs / team_games
            rapg = total_runs_allowed / team_games if total_runs_allowed > 0 else self.LEAGUE_AVG_RUNS

            # Win percentage: prefer W-L record from pitching; fallback to Pythagorean
            total_decisions = pitch_wins + pitch_losses
            if total_decisions >= 5:
                win_pct = pitch_wins / total_decisions
            else:
                # Pythagorean expectation (exponent 1.83 for baseball)
                exp = 1.83
                if rpg > 0 and rapg > 0:
                    win_pct = (rpg ** exp) / ((rpg ** exp) + (rapg ** exp))
                else:
                    win_pct = 0.5

            stats = {
                # Core
                'runs_per_game': round(rpg, 3),
                'runs_allowed': round(rapg, 3),
                'win_pct': round(win_pct, 3),
                'sample_size': team_games,
                # Batting rate stats
                'avg': round(team_avg, 3),
                'obp': round(team_obp, 3),
                'slg': round(team_slg, 3),
                'ops': round(team_ops, 3),
                'wrc_plus': round(team_wrc_plus, 1),
                'hr': team_hr,
                # Pitching rate stats
                'era': round(team_era, 3),
                'whip': round(team_whip, 3),
                'fip': round(team_fip, 3),
                'k9': round(team_k9, 2),
                'bb9': round(team_bb9, 2),
                'ip': round(team_pitch_ip, 1),
                'w': pitch_wins,
                'l': pitch_losses,
                # Splits (defaults — not available in player CSVs)
                'home_win_pct': 0.65,
                'away_win_pct': 0.45,
            }

            self._team_stats_cache[team_name] = stats
            return stats

        except Exception as e:
            logger.warning(f"Could not load stats for {team_name}: {e}")
            return None

    # ------------------------------------------------------------------
    # XGBoost feature builders
    # ------------------------------------------------------------------

    def _build_stat_xgb_features(self, home_stats: Dict, away_stats: Dict) -> Optional[pd.DataFrame]:
        """Build feature vector from aggregated season stats for XGBoost."""
        try:
            features = pd.DataFrame([{
                'home_rpg': home_stats['runs_per_game'],
                'home_rapg': home_stats['runs_allowed'],
                'home_avg': home_stats.get('avg', 0.0),
                'home_obp': home_stats.get('obp', 0.0),
                'home_slg': home_stats.get('slg', 0.0),
                'home_era': home_stats.get('era', 0.0),
                'home_whip': home_stats.get('whip', 0.0),
                'home_k9': home_stats.get('k9', 0.0),
                'away_rpg': away_stats['runs_per_game'],
                'away_rapg': away_stats['runs_allowed'],
                'away_avg': away_stats.get('avg', 0.0),
                'away_obp': away_stats.get('obp', 0.0),
                'away_slg': away_stats.get('slg', 0.0),
                'away_era': away_stats.get('era', 0.0),
                'away_whip': away_stats.get('whip', 0.0),
                'away_k9': away_stats.get('k9', 0.0),
                'is_home': 1,
            }])
            return features[STAT_XGB_FEATURES]
        except Exception as e:
            logger.warning(f"Failed to build stat XGB features: {e}")
            return None

    # ------------------------------------------------------------------
    # Rolling stats from DB (existing path)
    # ------------------------------------------------------------------

    async def _get_rolling_stats(self, team_name: str) -> Optional[Dict]:
        """Fetch rolling stats from DB for a team."""
        try:
            conn = self.db
            should_close = False

            if not conn:
                try:
                    from src.config import DATABASE_URL as CFG_DB
                    db_url = CFG_DB
                except Exception:
                    db_url = os.environ.get("DATABASE_URL",
                                            "postgresql://user:password@localhost:5432/sports_betting")
                import asyncpg
                conn = await asyncpg.connect(db_url)
                should_close = True

            query = """
                SELECT metadata
                FROM results
                WHERE series = 'college_baseball'
                  AND (metadata->>'homeTeam' = $1 OR metadata->>'awayTeam' = $1)
                ORDER BY event_date DESC
                LIMIT 20
            """
            rows = await conn.fetch(query, team_name)

            if should_close:
                await conn.close()

            if not rows or len(rows) < 5:
                return None

            history = []
            for row in rows:
                meta = json.loads(row['metadata'])
                is_home = meta.get('homeTeam') == team_name
                runs_for = float(meta.get('homeScore', 0) if is_home else meta.get('awayScore', 0))
                runs_against = float(meta.get('awayScore', 0) if is_home else meta.get('homeScore', 0))
                history.append({
                    'runs_scored': runs_for,
                    'runs_allowed': runs_against,
                    'won': 1 if runs_for > runs_against else 0
                })

            # Last 5
            l5 = history[:5]
            runs_scored_l5 = sum(g['runs_scored'] for g in l5) / 5.0
            runs_allowed_l5 = sum(g['runs_allowed'] for g in l5) / 5.0

            # Last 10
            l10 = history[:10]
            win_pct_l10 = sum(g['won'] for g in l10) / len(l10)

            # Streak
            streak = 0
            for g in history:
                if g['won'] == 1:
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                else:
                    if streak <= 0:
                        streak -= 1
                    else:
                        break

            return {
                'runs_scored_avg_l5': runs_scored_l5,
                'runs_allowed_avg_l5': runs_allowed_l5,
                'win_pct_l10': win_pct_l10,
                'streak': streak
            }

        except Exception as e:
            logger.warning(f"Error fetching rolling stats for {team_name}: {e}")
            return None

    # ------------------------------------------------------------------
    # Prediction engine
    # ------------------------------------------------------------------

    async def predict_game(self, home_team: str, away_team: str,
                           spread: float = None, over_under: float = None) -> Dict[str, Any]:
        """
        Predict game outcome using team statistics.
        Model layers (blended when available):
          1) Pythagorean Expectation (baseline, always runs if stats exist)
          2) Stat-based XGBoost (CSV aggregate features)
          3) Rolling-stats XGBoost (DB game history)
        """

        # --- Load team stats ---
        home_stats = await self.get_team_stats(home_team)
        away_stats = await self.get_team_stats(away_team)

        if not home_stats or not away_stats:
            logger.warning(f"Missing stats for {home_team} or {away_team}")
            return {
                'home_team': home_team,
                'away_team': away_team,
                'error': 'Insufficient data',
                'description': 'Team stats not found in database. Please run import.'
            }

        # --- Layer 1: Pythagorean Expectation ---
        home_advantage = 0.8

        home_off_strength = home_stats['runs_per_game'] / self.LEAGUE_AVG_RUNS
        home_def_strength = home_stats['runs_allowed'] / self.LEAGUE_AVG_RUNS
        away_off_strength = away_stats['runs_per_game'] / self.LEAGUE_AVG_RUNS
        away_def_strength = away_stats['runs_allowed'] / self.LEAGUE_AVG_RUNS

        home_expected = (self.LEAGUE_AVG_RUNS * home_off_strength * away_def_strength) + (home_advantage / 2)
        away_expected = (self.LEAGUE_AVG_RUNS * away_off_strength * home_def_strength) - (home_advantage / 2)

        # Clamp to prevent negative expected runs (would cause complex numbers in Pythagorean)
        home_expected = max(home_expected, 0.5)
        away_expected = max(away_expected, 0.5)

        predicted_margin = home_expected - away_expected
        predicted_total = home_expected + away_expected

        exponent = 1.83
        pyth_prob = (home_expected ** exponent) / ((home_expected ** exponent) + (away_expected ** exponent))

        # --- Layer 2: Stat-based XGBoost ---
        stat_xgb_pred = None
        if self.use_stat_xgb and self.model_stat_ml and self.model_stat_ou:
            features = self._build_stat_xgb_features(home_stats, away_stats)
            if features is not None:
                try:
                    stat_win_prob = float(self.model_stat_ml.predict_proba(features)[0][1])
                    stat_total = float(self.model_stat_ou.predict(features)[0])
                    stat_xgb_pred = {'win_prob': stat_win_prob, 'total_runs': stat_total}
                except Exception as e:
                    logger.error(f"Stat XGBoost prediction failed: {e}")

        # --- Layer 3: Rolling-stats XGBoost (DB) ---
        rolling_xgb_pred = None
        if self.use_xgb and self.model_ml and self.model_ou:
            home_rolling = await self._get_rolling_stats(home_team)
            away_rolling = await self._get_rolling_stats(away_team)

            if home_rolling and away_rolling:
                try:
                    features = pd.DataFrame([{
                        'home_runs_scored_avg_l5': home_rolling['runs_scored_avg_l5'],
                        'home_runs_allowed_avg_l5': home_rolling['runs_allowed_avg_l5'],
                        'home_win_pct_l10': home_rolling['win_pct_l10'],
                        'home_streak': home_rolling['streak'],
                        'away_runs_scored_avg_l5': away_rolling['runs_scored_avg_l5'],
                        'away_runs_allowed_avg_l5': away_rolling['runs_allowed_avg_l5'],
                        'away_win_pct_l10': away_rolling['win_pct_l10'],
                        'away_streak': away_rolling['streak'],
                        'is_neutral': 0
                    }])
                    rolling_xgb_pred = {
                        'win_prob': float(self.model_ml.predict_proba(features)[0][1]),
                        'total_runs': float(self.model_ou.predict(features)[0])
                    }
                except Exception as e:
                    logger.error(f"Rolling XGBoost prediction failed: {e}")

        # --- Blend predictions ---
        final_prob = pyth_prob
        final_total = predicted_total
        model_used = 'pythagorean'

        if rolling_xgb_pred and stat_xgb_pred:
            # All three layers available: 40% rolling, 30% stat, 30% pyth
            final_prob = (rolling_xgb_pred['win_prob'] * 0.40 +
                          stat_xgb_pred['win_prob'] * 0.30 +
                          pyth_prob * 0.30)
            final_total = (rolling_xgb_pred['total_runs'] * 0.40 +
                           stat_xgb_pred['total_runs'] * 0.30 +
                           predicted_total * 0.30)
            model_used = 'xgb_rolling+stat+pyth'
        elif rolling_xgb_pred:
            # Rolling XGBoost + Pythagorean: 70/30
            final_prob = rolling_xgb_pred['win_prob'] * 0.70 + pyth_prob * 0.30
            final_total = rolling_xgb_pred['total_runs'] * 0.70 + predicted_total * 0.30
            model_used = 'xgb_rolling+pyth'
        elif stat_xgb_pred:
            # Stat XGBoost + Pythagorean: 60/40
            final_prob = stat_xgb_pred['win_prob'] * 0.60 + pyth_prob * 0.40
            final_total = stat_xgb_pred['total_runs'] * 0.60 + predicted_total * 0.40
            model_used = 'xgb_stat+pyth'

        # --- Sanity bounds ---
        # College baseball totals realistically range from ~4 to ~25
        final_total = max(4.0, min(25.0, final_total))
        # Clamp win probability away from exact 50/50 when there is a real stat differential
        if abs(final_prob - 0.5) < 0.01 and abs(predicted_margin) > 0.5:
            final_prob = pyth_prob  # fall back to Pythagorean which is more decisive

        final_margin = (final_prob - 0.5) * 10  # approximate runs margin from prob
        if model_used == 'pythagorean':
            final_margin = predicted_margin  # use exact Pythagorean margin

        confidence = min(0.80, 0.5 + abs(final_margin) * 0.05)

        result = {
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': home_team if final_prob > 0.5 else away_team,
            'home_win_probability': round(final_prob, 3),
            'away_win_probability': round(1 - final_prob, 3),
            'predicted_margin': round(final_margin, 1),
            'predicted_total': round(final_total, 1),
            'home_expected_runs': round(home_expected, 1),
            'away_expected_runs': round(away_expected, 1),
            'confidence': round(confidence, 2),
            'confidence_level': 'high' if confidence >= 0.65 else 'medium' if confidence >= 0.55 else 'low',
            'model': model_used,
        }

        # Add XGBoost detail if available
        if stat_xgb_pred:
            result['xgb_stat_prob'] = round(stat_xgb_pred['win_prob'], 3)
            result['xgb_stat_total'] = round(stat_xgb_pred['total_runs'], 1)
        if rolling_xgb_pred:
            result['xgb_rolling_prob'] = round(rolling_xgb_pred['win_prob'], 3)
            result['xgb_rolling_total'] = round(rolling_xgb_pred['total_runs'], 1)
        result['xgb_available'] = bool(stat_xgb_pred or rolling_xgb_pred)

        # --- Compare to betting lines ---
        if spread is not None:
            line_margin = -spread
            model_edge = final_margin - line_margin
            result['spread'] = spread
            result['spread_pick'] = 'HOME' if final_margin > line_margin else 'AWAY'
            result['spread_edge'] = round(model_edge, 1)
            result['spread_value'] = abs(model_edge) >= 1.5

        if over_under is not None:
            ou_edge = final_total - over_under
            result['over_under'] = over_under
            result['ou_pick'] = 'OVER' if final_total > over_under else 'UNDER'
            result['ou_edge'] = round(ou_edge, 1)
            result['ou_value'] = abs(ou_edge) >= 1.5

        return result


# ======================================================================
# Odds API fetcher
# ======================================================================

async def get_todays_college_baseball_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """Fetch today's College Baseball odds from The Odds API."""
    today = date.today()
    try:
        import sys
        from pathlib import Path as P

        current_dir = P(__file__).resolve().parent
        backend_dir = current_dir.parent
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        from src.config import ODDS_API_KEY
        odds_api_key = ODDS_API_KEY
        logger.info(f"Loaded ODDS_API_KEY from src.config. Starting with: "
                     f"{odds_api_key[:4] if odds_api_key else 'None'}")
    except ImportError as e:
        logger.warning(f"Failed to import ODDS_API_KEY from src.config: {e}")
        odds_api_key = os.environ.get("ODDS_API_KEY")

    if odds_api_key:
        try:
            # Monkeypatch for Python 3.13 compatibility before importing httpx
            import collections
            import collections.abc
            for name in ['MutableSet', 'MutableMapping', 'Mapping',
                         'Iterable', 'Callable', 'Sequence']:
                if not hasattr(collections, name):
                    setattr(collections, name, getattr(collections.abc, name))

            import httpx

            book = SPORTSBOOK_MAP.get(sportsbook, "fanduel")
            url = "https://api.the-odds-api.com/v4/sports/baseball_ncaa/odds"
            params = {
                "apiKey": odds_api_key,
                "regions": "us",
                "markets": "h2h,totals",
                "bookmakers": book,
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    games = []
                    for event in data:
                        try:
                            home_team = event.get("home_team", "")
                            away_team = event.get("away_team", "")
                            game_data = {
                                "home_team": home_team,
                                "away_team": away_team,
                                "game_time": event.get("commence_time", ""),
                                "status": "scheduled",
                            }
                            for bookmaker in event.get("bookmakers", []):
                                if bookmaker.get("key") == book:
                                    for market in bookmaker.get("markets", []):
                                        if market.get("key") == "h2h":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == home_team:
                                                    game_data["home_moneyline"] = _decimal_to_american(
                                                        outcome.get("price", 2.0))
                                                elif outcome.get("name") == away_team:
                                                    game_data["away_moneyline"] = _decimal_to_american(
                                                        outcome.get("price", 2.0))
                                        elif market.get("key") == "totals":
                                            for outcome in market.get("outcomes", []):
                                                if outcome.get("name") == "Over":
                                                    game_data["over_under"] = outcome.get("point", 9.5)
                                                    break
                            games.append(game_data)
                        except Exception as e:
                            logger.warning(f"Error parsing College Baseball Odds API game: {e}")

                    if games:
                        logger.info(f"Loaded {len(games)} College Baseball games from The Odds API")
                        api_quota = {
                            "requests_remaining": int(response.headers.get("x-requests-remaining", 0)),
                            "requests_used": int(response.headers.get("x-requests-used", 0)),
                        }
                        return {
                            "date": str(today),
                            "sportsbook": sportsbook,
                            "games": games,
                            "count": len(games),
                            "source": "the-odds-api",
                            "api_quota": api_quota
                        }
                else:
                    logger.warning(f"Odds API returned {response.status_code}")

        except Exception as e:
            logger.warning(f"The Odds API failed for College Baseball: {e}")

    return {
        "date": str(today),
        "sportsbook": sportsbook,
        "games": [],
        "message": "No College Baseball games found for today"
    }


# ======================================================================
# Matchup analysis facade
# ======================================================================

async def analyze_college_baseball_matchup(home_team: str, away_team: str,
                                           spread: float = None, over_under: float = None,
                                           home_ml: int = None, away_ml: int = None) -> Dict[str, Any]:
    """Comprehensive College Baseball matchup analysis."""
    predictor = CollegeBaseballPredictor()
    prediction = await predictor.predict_game(home_team, away_team, spread, over_under)

    # If prediction failed (missing stats), return early with safe defaults
    if prediction.get('error'):
        prediction.setdefault('home_win_probability', 0.5)
        prediction.setdefault('away_win_probability', 0.5)
        prediction.setdefault('predicted_winner', home_team)
        prediction.setdefault('predicted_margin', 0.0)
        prediction.setdefault('predicted_total', 0.0)
        prediction.setdefault('confidence', 0.0)
        prediction.setdefault('confidence_level', 'low')
        prediction['value_bets'] = []
        prediction['has_value'] = False
        prediction['model'] = 'none'
        return prediction

    # Add moneyline analysis if provided
    if home_ml and away_ml:
        def implied_prob(odds):
            if odds > 0:
                return 100 / (odds + 100)
            else:
                return abs(odds) / (abs(odds) + 100)

        home_implied = implied_prob(home_ml)
        away_implied = implied_prob(away_ml)

        prediction['home_moneyline'] = home_ml
        prediction['away_moneyline'] = away_ml
        prediction['home_implied_prob'] = round(home_implied, 3)
        prediction['away_implied_prob'] = round(away_implied, 3)

        home_edge = prediction['home_win_probability'] - home_implied
        prediction['home_ml_edge'] = round(home_edge * 100, 1)
        prediction['ml_pick'] = home_team if home_edge > 0 else away_team
        prediction['ml_value'] = abs(home_edge) >= 0.05

    # Value bets summary
    value_bets = []
    if prediction.get('ml_value'):
        value_bets.append(f"ML: {prediction['ml_pick']}")
    if prediction.get('spread_value'):
        value_bets.append(f"Spread: {prediction['spread_pick']}")
    if prediction.get('ou_value'):
        value_bets.append(f"Total: {prediction['ou_pick']}")

    prediction['value_bets'] = value_bets
    prediction['has_value'] = len(value_bets) > 0

    return prediction
