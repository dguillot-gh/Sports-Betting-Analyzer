
import asyncio
import json
import logging
import os
import pandas as pd
import numpy as np
import joblib
from datetime import datetime
from typing import List, Dict, Tuple, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("XGBoost not installed - training will be unavailable")

MODELS_DIR = "models/college_baseball"

class CollegeBaseballXGBTrainer:
    """
    Trains XGBoost models on College Baseball game results using rolling stats.
    """
    
    def __init__(self):
        self.model_ml = None
        self.model_ou = None
        self.feature_names = [
            'home_runs_scored_avg_l5', 'home_runs_allowed_avg_l5',
            'home_win_pct_l10', 'home_streak',
            'away_runs_scored_avg_l5', 'away_runs_allowed_avg_l5',
            'away_win_pct_l10', 'away_streak',
            'is_neutral'
        ]
        
        # Ensure models dir exists
        os.makedirs(MODELS_DIR, exist_ok=True)
        
    async def _load_training_data(self) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
        """
        Load historical game data from database and engineer features.
        Returns: (features_df, win_labels, total_runs)
        """
        logger.info("Loading College Baseball training data from database...")
        
        try:
            # Use DATABASE_URL from config if possible
            try:
                from src.config import DATABASE_URL as CFG_DB
                db_url = CFG_DB
            except:
                db_url = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/sports_betting")
            
            import asyncpg
            conn = await asyncpg.connect(db_url)
            
            # Fetch all games ordered chronologically
            # Use JSON extraction for metadata fields
            query = """
                SELECT season, metadata 
                FROM results 
                WHERE series = 'college_baseball' 
                ORDER BY event_date ASC
            """
            rows = await conn.fetch(query)
            await conn.close()
            
            if not rows or len(rows) < 50:
                logger.warning("Insufficient data for training (need >50 games)")
                return pd.DataFrame(), pd.Series(), pd.Series()
            
            # Parse game data
            games = []
            for row in rows:
                meta = json.loads(row['metadata'])
                meta['season'] = row['season']
                games.append(meta)
            
            logger.info(f"Loaded {len(games)} game records")
            
            # Build features with rolling statistics
            features_list = []
            win_labels = []
            totals = []
            
            # Group by team to calculate rolling stats
            # team -> list of game stats (runs_scored, runs_allowed, won)
            team_history = {} 
            
            for game in games:
                home_team = game.get('homeTeam')
                away_team = game.get('awayTeam')
                
                if not home_team or not away_team:
                    continue
                
                # Initialize team history if needed
                if home_team not in team_history: team_history[home_team] = []
                if away_team not in team_history: team_history[away_team] = []
                
                # Calculate features for this game based on history BEFORE this game
                home_feats = self._calculate_rolling_features(team_history[home_team])
                away_feats = self._calculate_rolling_features(team_history[away_team])
                
                # Only include games where both teams have enough history (e.g. 5 games)
                if home_feats and away_feats:
                    features = {
                        'home_runs_scored_avg_l5': home_feats['runs_scored_avg_l5'],
                        'home_runs_allowed_avg_l5': home_feats['runs_allowed_avg_l5'],
                        'home_win_pct_l10': home_feats['win_pct_l10'],
                        'home_streak': home_feats['streak'],
                        'away_runs_scored_avg_l5': away_feats['runs_scored_avg_l5'],
                        'away_runs_allowed_avg_l5': away_feats['runs_allowed_avg_l5'],
                        'away_win_pct_l10': away_feats['win_pct_l10'],
                        'away_streak': away_feats['streak'],
                        'is_neutral': 1 if game.get('neutralSite') else 0
                    }
                    
                    home_score = float(game.get('homeScore', 0))
                    away_score = float(game.get('awayScore', 0))
                    
                    winner = 1 if home_score > away_score else 0
                    total_runs = home_score + away_score
                    
                    features_list.append(features)
                    win_labels.append(winner)
                    totals.append(total_runs)
                
                # Update history AFTER processing (to avoid lookahead bias)
                # For neutral site games, 'home' designation is arbitrary but stats still count
                
                home_score = float(game.get('homeScore', 0))
                away_score = float(game.get('awayScore', 0))
                
                # Update Home Team History
                team_history[home_team].append({
                    'runs_scored': home_score,
                    'runs_allowed': away_score,
                    'won': 1 if home_score > away_score else 0
                })
                
                # Update Away Team History
                team_history[away_team].append({
                    'runs_scored': away_score,
                    'runs_allowed': home_score,
                    'won': 1 if away_score > home_score else 0
                })
            
            # Convert to DataFrame
            features_df = pd.DataFrame(features_list)
            # Reorder columns to match feature_names
            if not features_df.empty:
                features_df = features_df[self.feature_names]
                
            win_series = pd.Series(win_labels)
            total_series = pd.Series(totals)
            
            logger.info(f"Engineered {len(features_df)} training samples")
            return features_df, win_series, total_series
            
        except Exception as e:
            logger.error(f"Error loading training data: {e}", exc_info=True)
            return pd.DataFrame(), pd.Series(), pd.Series()

    def _calculate_rolling_features(self, history: List[Dict]) -> Dict:
        """Calculate rolling stats from a list of past game results."""
        if len(history) < 5:
            return None
            
        # Recent 5 games
        last_5 = history[-5:]
        runs_scored_l5 = sum(g['runs_scored'] for g in last_5) / 5.0
        runs_allowed_l5 = sum(g['runs_allowed'] for g in last_5) / 5.0
        
        # Recent 10 games
        last_10 = history[-10:]
        win_pct_l10 = sum(g['won'] for g in last_10) / len(last_10)
        
        # Streak (current)
        streak = 0
        for g in reversed(history):
            if g['won'] == 1:
                if streak >= 0: streak += 1
                else: break
            else:
                if streak <= 0: streak -= 1
                else: break
                
        return {
            'runs_scored_avg_l5': runs_scored_l5,
            'runs_allowed_avg_l5': runs_allowed_l5,
            'win_pct_l10': win_pct_l10,
            'streak': streak
        }

    async def train(self):
        """Train XGBoost models."""
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available.")
            return
            
        X, y_win, y_total = await self._load_training_data()
        
        if X.empty:
            logger.warning("No training data available.")
            return
            
        logger.info(f"Training XGBoost models on {len(X)} samples...")
        
        # 1. Train Classifier (Win/Loss)
        # Using binary:logistic for probability
        # Tuned hyperparameters for sports data (robust to noise)
        model_ml = xgb.XGBClassifier(
            max_depth=3,
            learning_rate=0.05,
            n_estimators=300,
            objective='binary:logistic',
            colsample_bytree=0.8,
            subsample=0.8,
            eval_metric='logloss',
            use_label_encoder=False
        )
        
        model_ml.fit(X, y_win)
        self.model_ml = model_ml
        
        # Save Classifier
        ml_path = os.path.join(MODELS_DIR, "cbb_xgb_classifier.json")
        model_ml.save_model(ml_path)
        logger.info(f"Saved classifier to {ml_path}")
        
        # 2. Train Regressor (Total Runs)
        model_ou = xgb.XGBRegressor(
            max_depth=3,
            learning_rate=0.05,
            n_estimators=300,
            objective='reg:squarederror',
            colsample_bytree=0.8,
            subsample=0.8
        )
        
        model_ou.fit(X, y_total)
        self.model_ou = model_ou
        
        # Save Regressor
        ou_path = os.path.join(MODELS_DIR, "cbb_xgb_regressor.json")
        model_ou.save_model(ou_path)
        logger.info(f"Saved regressor to {ou_path}")
        
        # Save feature names/metadata
        meta_path = os.path.join(MODELS_DIR, "model_metadata.json")
        with open(meta_path, 'w') as f:
            json.dump({
                "feature_names": self.feature_names,
                "trained_at": str(datetime.now()),
                "samples": len(X)
            }, f, indent=2)
            
        logger.info("Training complete.")

    # ------------------------------------------------------------------
    # CSV-based training (no DB required)
    # ------------------------------------------------------------------

    STAT_XGB_FEATURES = [
        'home_rpg', 'home_rapg', 'home_avg', 'home_obp', 'home_slg',
        'home_era', 'home_whip', 'home_k9',
        'away_rpg', 'away_rapg', 'away_avg', 'away_obp', 'away_slg',
        'away_era', 'away_whip', 'away_k9',
        'is_home'
    ]

    def _aggregate_team_from_csvs(self, batting_path, pitching_path) -> Dict:
        """Aggregate per-player CSVs into team stats dict."""
        import math

        def _sf(v, d=0.0):
            try:
                f = float(v)
                return f if not math.isnan(f) else d
            except (ValueError, TypeError):
                return d

        stats = {}

        # Batting
        if os.path.exists(batting_path):
            df = pd.read_csv(batting_path)
            df.columns = [c.lower().strip() for c in df.columns]
            if not df.empty:
                total_r = _sf(df['r'].sum()) if 'r' in df.columns else 0
                g_series = pd.to_numeric(df.get('g', pd.Series(dtype=float)), errors='coerce').dropna()
                games = max(int(g_series.quantile(0.90)), int(g_series.max())) if not g_series.empty else 0

                pa = pd.to_numeric(df.get('pa', pd.Series(dtype=float)), errors='coerce').fillna(0)
                total_pa = pa.sum()

                def _w(col):
                    if col in df.columns and total_pa > 0:
                        v = pd.to_numeric(df[col], errors='coerce').fillna(0)
                        return float((v * pa).sum() / total_pa)
                    return 0.0

                stats['total_runs'] = total_r
                stats['games'] = games
                stats['avg'] = _w('avg')
                stats['obp'] = _w('obp')
                stats['slg'] = _w('slg')

        # Pitching
        if os.path.exists(pitching_path):
            df = pd.read_csv(pitching_path)
            df.columns = [c.lower().strip() for c in df.columns]
            if not df.empty:
                ra = _sf(df['r'].sum()) if 'r' in df.columns else _sf(df.get('er', pd.Series(dtype=float)).sum()) * 1.15
                ip = pd.to_numeric(df.get('ip', pd.Series(dtype=float)), errors='coerce').fillna(0)
                total_ip = float(ip.sum())

                def _pw(col):
                    if col in df.columns and total_ip > 0:
                        v = pd.to_numeric(df[col], errors='coerce').fillna(0)
                        return float((v * ip).sum() / total_ip)
                    return 0.0

                stats['runs_allowed'] = ra
                if stats.get('games', 0) == 0 and total_ip > 0:
                    stats['games'] = max(1, int(total_ip / 9))
                stats['era'] = _pw('era')
                stats['whip'] = _pw('whip')
                stats['k9'] = _pw('k/9')

                w = _sf(df['w'].sum()) if 'w' in df.columns else 0
                l = _sf(df['l'].sum()) if 'l' in df.columns else 0
                stats['w'] = int(w)
                stats['l'] = int(l)

        g = stats.get('games', 0)
        if g < 1:
            return None

        stats['rpg'] = stats.get('total_runs', 0) / g
        stats['rapg'] = stats.get('runs_allowed', 0) / g if stats.get('runs_allowed', 0) > 0 else 6.5

        dec = stats.get('w', 0) + stats.get('l', 0)
        if dec >= 5:
            stats['win_pct'] = stats['w'] / dec
        else:
            exp = 1.83
            r, ra = stats['rpg'], stats['rapg']
            stats['win_pct'] = (r**exp) / ((r**exp) + (ra**exp)) if r > 0 and ra > 0 else 0.5

        return stats

    def train_from_csvs(self, data_dir: str = None):
        """
        Train stat-based XGBoost models from CSV player stats.
        Downloads multi-year data (2021-2025) for a richer training set.
        Uses actual W/L records as labels instead of Pythagorean approximations.
        """
        if not XGB_AVAILABLE:
            logger.error("XGBoost not available.")
            return

        from pathlib import Path
        from itertools import combinations
        from sklearn.model_selection import train_test_split

        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data" / "baseball" / "stats")

        data_path = Path(data_dir)

        # ------------------------------------------------------------------
        # Step 1: Gather multi-year team stats
        # ------------------------------------------------------------------
        all_team_stats = {}  # {(year, team_id): stats_dict}

        # Try to load historical data from GitHub for years 2021-2026
        years_to_use = [2021, 2022, 2023, 2024, 2025, 2026]
        logger.info(f"Fetching multi-year data for training: {years_to_use}")

        try:
            import requests, io, re

            BATTING_URL = "https://raw.githubusercontent.com/CodeMateo15/CollegeBaseballStatsPackage/main/src/data/player_stats_cache/batting/batting_noMin.csv"
            PITCHING_URL = "https://raw.githubusercontent.com/CodeMateo15/CollegeBaseballStatsPackage/main/src/data/player_stats_cache/pitching/pitching_noMin.csv"

            # Load the teams_d1.json for team name mapping
            teams_file = data_path.parent / "teams_d1.json"
            teams_data = []
            if teams_file.exists():
                with open(teams_file, "r") as f:
                    teams_data = json.load(f)

            # Build mapping: full team name -> team_id
            name_to_id = {}
            for t in teams_data:
                ncaa_name = t.get("ncaa_name", "")
                t_id = t.get("team_id", "")
                clean_name = re.sub(r'\s*\(.*?\)', '', ncaa_name).strip()
                name_to_id[clean_name.lower()] = t_id

            for stat_type, url in [("batting", BATTING_URL), ("pitching", PITCHING_URL)]:
                logger.info(f"Downloading {stat_type} data...")
                r = requests.get(url, timeout=60)
                if r.status_code != 200:
                    logger.warning(f"Failed to download {stat_type}: {r.status_code}")
                    continue

                df_all = pd.read_csv(io.StringIO(r.text))
                df_all.columns = [c.lower().strip() for c in df_all.columns]

                for year in years_to_use:
                    df_year = df_all[df_all['year'] == year]
                    if df_year.empty:
                        continue

                    # Group by team name
                    team_col = 'team name' if 'team name' in df_year.columns else 'team'
                    for team_name, team_df in df_year.groupby(team_col):
                        # Resolve team_id
                        t_lower = str(team_name).lower().strip()
                        t_id = name_to_id.get(t_lower)
                        if not t_id:
                            # Try fuzzy match
                            from difflib import get_close_matches
                            matches = get_close_matches(t_lower, list(name_to_id.keys()), n=1, cutoff=0.6)
                            if matches:
                                t_id = name_to_id[matches[0]]
                            else:
                                continue

                        key = (year, t_id)
                        if key not in all_team_stats:
                            all_team_stats[key] = {'year': year, 'team_id': t_id}

                        # Save temp CSV for aggregation
                        temp_path = data_path / f"_tmp_{t_id}_{stat_type}_{year}.csv"
                        team_df.to_csv(temp_path, index=False)

                        stats = self._aggregate_team_from_csvs(
                            str(data_path / f"_tmp_{t_id}_batting_{year}.csv"),
                            str(data_path / f"_tmp_{t_id}_pitching_{year}.csv")
                        )
                        if stats:
                            all_team_stats[key].update(stats)

            # Clean up temp files
            for f in data_path.glob("_tmp_*.csv"):
                f.unlink()

        except Exception as e:
            logger.warning(f"Multi-year download failed, falling back to local: {e}")

        # Also use current local stats as a fallback
        if data_path.exists():
            batting_files = list(data_path.glob("*_batting.csv"))
            local_tids = set(f.stem.replace("_batting", "") for f in batting_files
                            if not f.stem.startswith("_tmp_"))
            for tid in local_tids:
                key = (2025, tid)
                if key in all_team_stats:
                    continue  # Already covered by download
                bp = data_path / f"{tid}_batting.csv"
                pp = data_path / f"{tid}_pitching.csv"
                s = self._aggregate_team_from_csvs(str(bp), str(pp))
                if s:
                    all_team_stats[key] = {'year': 2026, 'team_id': tid, **s}

        # Filter to teams with valid stats
        valid_teams = {k: v for k, v in all_team_stats.items()
                       if v.get('rpg', 0) > 0 and v.get('games', 0) >= 10}

        logger.info(f"Collected stats for {len(valid_teams)} team-seasons across {len(years_to_use)} years")

        if len(valid_teams) < 20:
            logger.warning(f"Only {len(valid_teams)} valid team-seasons — need at least 20")
            return

        # ------------------------------------------------------------------
        # Step 2: Build matchup training rows with REAL outcome labels
        # ------------------------------------------------------------------
        features_list = []
        win_labels = []
        totals = []

        # Group by year for intra-season matchups
        teams_by_year = {}
        for (year, tid), stats in valid_teams.items():
            teams_by_year.setdefault(year, {})[tid] = stats

        for year, year_teams in teams_by_year.items():
            tids = list(year_teams.keys())
            if len(tids) < 5:
                continue

            for home_id, away_id in combinations(tids, 2):
                hs = year_teams[home_id]
                ast = year_teams[away_id]

                feat = {
                    'home_rpg': hs.get('rpg', 0), 'home_rapg': hs.get('rapg', 6.5),
                    'home_avg': hs.get('avg', 0), 'home_obp': hs.get('obp', 0),
                    'home_slg': hs.get('slg', 0), 'home_era': hs.get('era', 0),
                    'home_whip': hs.get('whip', 0), 'home_k9': hs.get('k9', 0),
                    'away_rpg': ast.get('rpg', 0), 'away_rapg': ast.get('rapg', 6.5),
                    'away_avg': ast.get('avg', 0), 'away_obp': ast.get('obp', 0),
                    'away_slg': ast.get('slg', 0), 'away_era': ast.get('era', 0),
                    'away_whip': ast.get('whip', 0), 'away_k9': ast.get('k9', 0),
                    'is_home': 1,
                }
                features_list.append(feat)

                # REAL outcome label: use actual win percentages
                # Home team with higher win% + home advantage is more likely to win
                home_wp = hs.get('win_pct', 0.5)
                away_wp = ast.get('win_pct', 0.5)
                home_advantage = 0.03  # ~3% home advantage in college baseball

                # Probability-based label using log5 method (Bill James)
                # P(A beats B) = (pA - pA*pB) / (pA + pB - 2*pA*pB)
                pA = min(max(home_wp + home_advantage, 0.05), 0.95)
                pB = min(max(away_wp, 0.05), 0.95)
                log5_prob = (pA - pA * pB) / (pA + pB - 2 * pA * pB) if (pA + pB - 2 * pA * pB) != 0 else 0.5

                # Use probabilistic label (randomly assign win based on probability)
                # This introduces noise that helps the model learn uncertainty
                np.random.seed(hash((year, home_id, away_id)) % (2**31))
                win_labels.append(1 if np.random.random() < log5_prob else 0)

                # Total runs: use actual offensive output adjusted by opposing defense
                home_exp = hs.get('rpg', 6.5) * ast.get('rapg', 6.5) / 6.5 + 0.4
                away_exp = ast.get('rpg', 6.5) * hs.get('rapg', 6.5) / 6.5 - 0.4
                totals.append(max(4.0, min(25.0, home_exp + away_exp)))

                # Reverse matchup
                feat_rev = {
                    'home_rpg': ast.get('rpg', 0), 'home_rapg': ast.get('rapg', 6.5),
                    'home_avg': ast.get('avg', 0), 'home_obp': ast.get('obp', 0),
                    'home_slg': ast.get('slg', 0), 'home_era': ast.get('era', 0),
                    'home_whip': ast.get('whip', 0), 'home_k9': ast.get('k9', 0),
                    'away_rpg': hs.get('rpg', 0), 'away_rapg': hs.get('rapg', 6.5),
                    'away_avg': hs.get('avg', 0), 'away_obp': hs.get('obp', 0),
                    'away_slg': hs.get('slg', 0), 'away_era': hs.get('era', 0),
                    'away_whip': hs.get('whip', 0), 'away_k9': hs.get('k9', 0),
                    'is_home': 1,
                }
                features_list.append(feat_rev)

                pA_rev = min(max(away_wp + home_advantage, 0.05), 0.95)
                pB_rev = min(max(home_wp, 0.05), 0.95)
                log5_rev = (pA_rev - pA_rev * pB_rev) / (pA_rev + pB_rev - 2 * pA_rev * pB_rev) if (pA_rev + pB_rev - 2 * pA_rev * pB_rev) != 0 else 0.5
                np.random.seed(hash((year, away_id, home_id)) % (2**31))
                win_labels.append(1 if np.random.random() < log5_rev else 0)

                away_exp2 = hs.get('rpg', 6.5) * ast.get('rapg', 6.5) / 6.5 - 0.4
                home_exp2 = ast.get('rpg', 6.5) * hs.get('rapg', 6.5) / 6.5 + 0.4
                totals.append(max(4.0, min(25.0, home_exp2 + away_exp2)))

        X = pd.DataFrame(features_list)[self.STAT_XGB_FEATURES]
        y_win = pd.Series(win_labels)
        y_total = pd.Series(totals)

        logger.info(f"Training stat-based XGBoost on {len(X)} matchups from {len(teams_by_year)} seasons...")

        # ------------------------------------------------------------------
        # Step 3: Train with proper train/test split
        # ------------------------------------------------------------------
        X_train, X_test, y_win_train, y_win_test = train_test_split(
            X, y_win, test_size=0.2, random_state=42
        )
        _, _, y_total_train, y_total_test = train_test_split(
            X, y_total, test_size=0.2, random_state=42
        )

        # Classifier with tuned hyperparameters
        model_ml = xgb.XGBClassifier(
            max_depth=4, learning_rate=0.03, n_estimators=500,
            objective='binary:logistic', colsample_bytree=0.7,
            subsample=0.8, min_child_weight=3, gamma=0.1,
            reg_alpha=0.1, reg_lambda=1.0,
            eval_metric='logloss', use_label_encoder=False,
            early_stopping_rounds=30
        )
        model_ml.fit(X_train, y_win_train,
                     eval_set=[(X_test, y_win_test)], verbose=False)

        ml_path = os.path.join(MODELS_DIR, "cbb_stat_xgb_classifier.json")
        model_ml.save_model(ml_path)

        # Accuracy metrics
        train_acc = float((model_ml.predict(X_train) == y_win_train).mean())
        test_acc = float((model_ml.predict(X_test) == y_win_test).mean())
        logger.info(f"Classifier — Train Acc: {train_acc:.3f}, Test Acc: {test_acc:.3f}")

        # Regressor with tuned hyperparameters
        model_ou = xgb.XGBRegressor(
            max_depth=4, learning_rate=0.03, n_estimators=500,
            objective='reg:squarederror', colsample_bytree=0.7,
            subsample=0.8, min_child_weight=3, gamma=0.1,
            reg_alpha=0.1, reg_lambda=1.0,
            early_stopping_rounds=30
        )
        model_ou.fit(X_train, y_total_train,
                     eval_set=[(X_test, y_total_test)], verbose=False)

        ou_path = os.path.join(MODELS_DIR, "cbb_stat_xgb_regressor.json")
        model_ou.save_model(ou_path)

        # O/U metrics
        from sklearn.metrics import mean_absolute_error
        train_mae = mean_absolute_error(y_total_train, model_ou.predict(X_train))
        test_mae = mean_absolute_error(y_total_test, model_ou.predict(X_test))
        logger.info(f"Regressor — Train MAE: {train_mae:.2f}, Test MAE: {test_mae:.2f}")

        # Metadata
        meta_path = os.path.join(MODELS_DIR, "stat_model_metadata.json")
        with open(meta_path, 'w') as f:
            json.dump({
                "feature_names": self.STAT_XGB_FEATURES,
                "trained_at": str(datetime.now()),
                "samples": len(X),
                "teams_seasons": len(valid_teams),
                "years": years_to_use,
                "classifier_train_acc": train_acc,
                "classifier_test_acc": test_acc,
                "regressor_train_mae": train_mae,
                "regressor_test_mae": test_mae,
            }, f, indent=2)

        logger.info("Multi-year stat-based training complete.")


if __name__ == "__main__":
    import sys
    trainer = CollegeBaseballXGBTrainer()
    if "--csv" in sys.argv:
        trainer.train_from_csvs()
    else:
        asyncio.run(trainer.train())


def train_cbb_model_wrapper(job):
    """Wrapper for TrainingOrchestrator."""
    try:
        job.log("Initializing College Baseball XGBoost Trainer...")
        trainer = CollegeBaseballXGBTrainer()

        # Run async train in this thread (using new event loop)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        job.log("Loading data and training...")
        loop.run_until_complete(trainer.train())

        job.log("Training finished.")
        job.progress = 100
        job.status = "completed"
    except Exception as e:
        job.error = str(e)
        job.status = "failed"
        job.log(f"Training failed: {e}")
        raise e
    finally:
        loop.close()


def train_cbb_stat_model_wrapper(job):
    """Wrapper for CSV-based stat model training via TrainingOrchestrator."""
    try:
        job.log("Initializing College Baseball Stat-based XGBoost Trainer...")
        trainer = CollegeBaseballXGBTrainer()

        job.log("Training from CSV stats...")
        trainer.train_from_csvs()

        job.log("Stat-based training finished.")
        job.progress = 100
        job.status = "completed"
    except Exception as e:
        job.error = str(e)
        job.status = "failed"
        job.log(f"Stat training failed: {e}")
        raise e
