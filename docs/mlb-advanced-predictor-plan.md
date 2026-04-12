# MLB Advanced Predictor — Implementation Plan

> **Goal**: Upgrade the MLB predictor from a simple Pythagorean Expectation model to a
> full-featured, multi-model ensemble using real-time data from `mlb_scraper` (api_scraper.py)
> and feature engineering patterns from [gmalbert/baseball-predictions](https://github.com/gmalbert/baseball-predictions).

---

## Current State

| Component | Status |
|---|---|
| `backend/scripts/mlb_odds.py` | ✅ Live FanDuel odds via sbrscrape |
| `backend/scripts/mlb_predictor.py` | ✅ Pythagorean Expectation (baseline) |
| `backend/scripts/api_scraper.py` | ✅ Downloaded from tnestico/mlb_scraper |
| `backend/api/odds_endpoints.py` | ✅ `/odds/mlb` and `/odds/mlb/analyze-all` |
| `shared/Components/MlbOdds.razor` | ✅ Mobile component |
| `frontend/.../MlbLiveOdds.razor` | ✅ Web page |
| Nav links (web + mobile) | ✅ Added |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                   MLB Data Pipeline                          │
│                                                              │
│  api_scraper.py ──► mlb_stats_collector.py ──► PostgreSQL    │
│  (tnestico)         (new: nightly aggregator)   mlb_* tables │
│                                                              │
│  MLB Stats API ──► standings, team stats (runs, ERA, etc.)   │
│  sbrscrape ──────► live odds (FanDuel, DK, BetMGM)          │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────┐
│                   Feature Engine                             │
│                   mlb_features.py                            │
│                                                              │
│  Team Stats: WPct, PythWPct, RS/G, RA/G, ERA, WHIP, K9,    │
│              BA, SLG, fielding %, LOB/G                      │
│                                                              │
│  Pitcher Stats: SP ERA, SP WHIP, SP K9, SP vs. opponent,    │
│                 bullpen IP last 3 days, bullpen arms used    │
│                                                              │
│  Context: park factor, day/night, rest days, back-to-back,  │
│           weather (temp, wind dir, dome), platoon advantage  │
│                                                              │
│  Differentials: WPct_diff, ERA_diff, WHIP_diff, sp_ERA_gap, │
│                 matchup K/BB delta                           │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────┐
│                   Model Layer                                │
│                                                              │
│  Model 1: Moneyline XGBoost (P(home_win))                   │
│  Model 2: Spread XGBoost (P(home covers -1.5))              │
│  Model 3: Totals LightGBM+XGBoost ensemble (P(over))        │
│  Model 4: Pythagorean Expectation (current baseline)         │
│                                                              │
│  Ensemble: weighted blend of models 1-4                      │
│  Output: win prob, spread pick, O/U pick, confidence, edge   │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────┐
│                   API + Frontend                             │
│                                                              │
│  POST /odds/mlb/analyze-all → enriched predictions           │
│  MlbLiveOdds.razor (web) + MlbOdds.razor (mobile)           │
│  Updated UI: multi-model display, edge signals, confidence   │
└──────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Data Collection & Storage

### 1.1 MLB Stats Collector Service
**File**: `backend/scripts/mlb_stats_collector.py`

Uses `api_scraper.py` (`MLB_Scrape`) to collect and aggregate:
- Season schedule with game results via `get_schedule()`
- Pitch-by-pitch data via `get_data()` for completed games
- Aggregated into team-level and pitcher-level stats via `get_data_df()`

**Key aggregations** (derived from pitch-by-pitch data):

| Stat | Source Column(s) | Aggregation |
|---|---|---|
| Team batting average | `event_type` = hit / at-bat events | hits / at-bats per team |
| Team ERA | `pitcher_team`, `is_out`, inning data | earned runs / innings per team staff |
| SP ERA / WHIP / K9 | `pitcher_id`, filter starters | per-pitcher season aggregates |
| Bullpen IP last 3 days | `pitcher_id`, `game_date`, non-starters | sum IP in rolling 3-day window |
| Strikeout rate | `is_strike`, `is_whiff` | K/PA per team |
| Launch speed / angle | `launch_speed`, `launch_angle` | team averages (Savant-equivalent) |

### 1.2 Database Tables
**File**: `db/init/02_mlb_schema.sql`

- `mlb_team_stats` — season-level team batting/pitching/fielding/baserunning
- `mlb_pitcher_stats` — per-pitcher season stats (ERA, WHIP, K9, handedness)
- `mlb_game_features` — per-game feature vectors + predictions + actuals

### 1.3 Scheduled Nightly Job
Add to `backend/services/scheduler.py`:
- **2:00 AM ET**: Ingest yesterday's completed games
- **6:00 AM ET**: Build feature vectors for today's scheduled games
- **On-demand**: `/odds/mlb/refresh-stats` endpoint

---

## Phase 2 — Feature Engineering

### 2.1 Feature Engine
**File**: `backend/scripts/mlb_features.py`

Port from `baseball-predictions/src/models/features.py` + `extra_features.py`, adapted to use our live data instead of Retrosheet CSVs.

#### Team-Level (14 features)
- `home_WPct`, `away_WPct`, `WPct_diff`
- `home_PythWPct`, `away_PythWPct`, `PythWPct_diff`
- `home_RS_G`, `home_RA_G`, `away_RS_G`, `away_RA_G`, `home_RD_G`, `away_RD_G`
- `home_ERA`, `away_ERA`, `ERA_diff`, `home_WHIP`, `away_WHIP`, `WHIP_diff`
- `home_K9`, `away_K9`, `home_BA`, `away_BA`, `home_SLG`, `away_SLG`

#### Starting Pitcher (9 features)
- `home_sp_ERA`, `away_sp_ERA`, `sp_ERA_gap`
- `home_sp_WHIP`, `away_sp_WHIP`, `home_sp_K9`, `away_sp_K9`
- `home_sp_vs_opp_ERA`, `away_sp_vs_opp_ERA`

#### Context (15 features)
- `temp`, `windspeed`, `is_day`
- `wind_out`, `wind_in`, `dome_flag`, `temp_cold`, `temp_hot`, `overcast_flag`
- `home_days_rest`, `away_days_rest`
- `home_back_to_back`, `away_back_to_back`, `is_doubleheader`
- Park factor (runs environment per venue)

#### Matchup (18 features)
- `home_K_rate`, `away_K_rate`, `home_BB_rate`, `away_BB_rate`, `home_K_BB_ratio`, `away_K_BB_ratio`
- `home_day_WPct`, `away_day_WPct`, `home_night_WPct`, `away_night_WPct`
- `home_errors_per_g`, `away_errors_per_g`, `home_dp_rate`, `away_dp_rate`
- `home_def_efficiency`, `away_def_efficiency`
- `home_sb_success_rate`, `away_sb_success_rate`
- `home_bullpen_ip_3d`, `away_bullpen_ip_3d`
- `home_platoon_adv`, `away_platoon_adv`, `platoon_adv_gap`, `matchup_k_delta`

#### Totals-Specific (3 features)
- `home_lob_per_g`, `away_lob_per_g`, `exp_total`

### 2.2 Data Sources for Each Feature

| Feature Group | Source | Method |
|---|---|---|
| Team W/L, RS, RA | MLB Stats API standings | `_fetch_mlb_standings()` (exists) |
| Team ERA, WHIP, K9, BA, SLG | `api_scraper.get_data_df()` aggregated | New collector |
| SP stats | `api_scraper.get_data_df()` filtered to starters | New collector |
| Bullpen fatigue | `get_data_df()` 3-day rolling non-starters | New collector |
| Weather | Open-Meteo API (free, no key needed) | New fetcher |
| Park factors | Static lookup table (30 venues) | Hardcoded dict |
| Rest days | Schedule gap from `get_schedule()` | Calculated |
| Day/night | Game time from schedule | From schedule |
| Platoon | SP handedness vs lineup handedness | From pitcher data |

---

## Phase 3 — ML Models

### 3.1 Moneyline Model (P(home_win))
**File**: `backend/scripts/mlb_moneyline_model.py`

- XGBClassifier: 300 trees, max_depth=5, lr=0.05, StandardScaler pipeline
- **Target**: `home_win` (binary)
- **Features**: Team + SP + Context + Matchup (~56 features)
- **Output**: P(home_win) → compare against implied probability for edge

### 3.2 Spread Model (P(home covers -1.5))
**File**: `backend/scripts/mlb_spread_model.py`

- **Target**: `home_cover` = `(home_runs - away_runs) >= 2` (binary)
- **Features**: Same as moneyline
- **Use case**: Run line (-1.5 / +1.5) predictions

### 3.3 Totals Model (P(over))
**File**: `backend/scripts/mlb_totals_model.py`

- LightGBM + XGBoost ensemble (0.5/0.5 blend)
- **Target**: `went_over` = `(total_runs > posted_total)` (binary)
- **Features**: Team + SP + Context + Matchup + LOB + exp_total (~60 features)

### 3.4 Training Pipeline
**File**: `backend/scripts/mlb_train_models.py`

- Trains all 3 models on historical data (2021+)
- Saves to `backend/models/mlb/` as joblib files
- Logs metrics (ROC-AUC, accuracy, Brier score) to DB `models` table
- Triggered nightly or on-demand via API

### 3.5 Ensemble Predictor
**File**: Update `backend/scripts/mlb_predictor.py`

```
Ensemble blend:
  home_win_prob = 0.4 * xgb_ml + 0.3 * pythagorean + 0.3 * implied_regression

Signal logic:
  |edge| >= 8%  → BET
  |edge| >= 4%  → LEAN
  |edge| < 4%   → PASS
```

---

## Phase 4 — API Enhancements

### New Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `POST /odds/mlb/analyze-all` | POST | Existing — upgraded to return multi-model |
| `GET /odds/mlb/team-stats` | GET | Team-level stats for UI detail panels |
| `GET /odds/mlb/pitcher/{id}` | GET | Pitcher stats + vs-opponent history |
| `POST /odds/mlb/refresh-stats` | POST | Trigger data collection on-demand |
| `POST /odds/mlb/train` | POST | Trigger model retraining |
| `GET /odds/mlb/model-metrics` | GET | Latest ROC-AUC, accuracy, Brier score |

### Updated Response Shape

```json
{
  "games": [{
    "home_team": "New York Yankees",
    "away_team": "Boston Red Sox",
    "home_moneyline": -150, "away_moneyline": 130,
    "spread": -1.5, "over_under": 8.5,

    "models": {
      "pythagorean":     { "home_win_prob": 0.58, "predicted_total": 8.9 },
      "moneyline_xgb":   { "home_win_prob": 0.62, "confidence": 0.71 },
      "spread_xgb":      { "home_cover_prob": 0.45, "pick": "AWAY +1.5" },
      "totals_ensemble":  { "over_prob": 0.56, "pick": "OVER", "confidence": 0.63 }
    },

    "consensus": {
      "home_win_prob": 0.60,
      "ml_pick": "NYY", "ml_edge": 5.2, "ml_signal": "LEAN",
      "spread_pick": "BOS +1.5", "spread_signal": "BET",
      "ou_pick": "OVER 8.5", "ou_signal": "LEAN"
    },

    "context": {
      "home_sp": "Gerrit Cole", "away_sp": "Brayan Bello",
      "home_sp_era": 3.12, "away_sp_era": 4.45,
      "park_factor": 1.05, "weather": "72°F, Wind 8mph Out",
      "home_record": "45-30", "away_record": "38-37"
    },

    "has_value": true,
    "value_bets": ["ML: NYY (LEAN)", "Spread: BOS +1.5 (BET)"]
  }]
}
```

---

## Phase 5 — Frontend Updates

### Web (`MlbLiveOdds.razor`)
- Multi-model table: side-by-side Pythagorean / XGBoost / Ensemble probabilities
- Signal badges: ✅ BET / ➡ LEAN / ⛔ PASS with color coding
- Context panel: SP matchup, park factor, weather, rest days
- Edge visualization: model probability vs implied probability
- Model metrics tab: ROC-AUC, accuracy for transparency

### Mobile (`MlbOdds.razor`)
- Consensus pick prominently displayed (BET/LEAN/PASS signal)
- Expandable detail: tap for multi-model breakdown
- SP matchup line: "Cole (3.12 ERA) vs Bello (4.45 ERA)"
- Context chips: park factor, weather, rest

### New Routes in `PredictionApiRoutes.cs`
- `MlbTeamStats()`, `MlbModelMetrics()`, `MlbRefreshStats()`, `MlbTrain()`

---

## Phase 6 — Backtesting & Validation

### Historical Backtest (`mlb_backtest.py`)
- Collect 2021-2025 data via `api_scraper.get_schedule()` + `get_data()`
- Build features for each historical game
- Chronological train/test split (80/20)
- Track: ROI, Sharpe ratio, max drawdown, win rate by confidence tier

### Daily Performance Tracker
- Log each day's picks and outcomes
- Rolling 7/30/90-day accuracy
- Store in `mlb_game_features.actual_result` after games complete

---

## Implementation Order

| # | Task | Files | Est. Hours |
|---|---|---|---|
| 1 | MLB stats collector (aggregate pitch data) | `mlb_stats_collector.py` | 3-4 |
| 2 | DB schema for team/pitcher/game stats | `02_mlb_schema.sql` | 0.5 |
| 3 | Feature engine (60 features from live data) | `mlb_features.py` | 4-5 |
| 4 | Park factor + weather data fetcher | `mlb_context.py` | 1-2 |
| 5 | Moneyline XGBoost model | `mlb_moneyline_model.py` | 2 |
| 6 | Spread XGBoost model | `mlb_spread_model.py` | 1.5 |
| 7 | Totals LGB+XGB ensemble | `mlb_totals_model.py` | 2 |
| 8 | Training pipeline + scheduler | `mlb_train_models.py` | 1.5 |
| 9 | Update predictor to ensemble | `mlb_predictor.py` | 2 |
| 10 | New API endpoints | `odds_endpoints.py` | 1.5 |
| 11 | Update web UI (multi-model, signals) | `MlbLiveOdds.razor` | 2-3 |
| 12 | Update mobile UI (consensus + detail) | `MlbOdds.razor` | 2 |
| 13 | Historical backtest (2021-2025) | `mlb_backtest.py` | 3-4 |
| 14 | Daily performance tracker + nightly job | scheduler | 1.5 |

**Total: ~28-32 hours**

---

## Dependencies to Add

```
lightgbm
joblib
```

Weather: Open-Meteo API (free, no key, 10k calls/day) via httpx.

---

## Risk & Mitigation

| Risk | Mitigation |
|---|---|
| `get_data()` slow for full season (2400+ games) | Nightly incremental collector; cache in PostgreSQL |
| Early-season small samples | Fall back to Pythagorean until 30+ games played |
| Model overfitting | Chronological split, regularization, cross-validation |
| Weather API limits | Open-Meteo is free 10k/day + cache per venue/date |
| SP lineup unknown until game day | Fetch at T-2hrs; use team averages as fallback |

---

## Success Criteria

- [ ] Moneyline model ROC-AUC ≥ 0.58 on out-of-sample test
- [ ] Backtested ROI > 0% over 2023-2025 with flat $100 bets
- [ ] Edge detection finds 2-5 value bets per day during season
- [ ] Predictions served < 3 seconds for full slate (~15 games)
- [ ] Models retrain nightly without manual intervention
