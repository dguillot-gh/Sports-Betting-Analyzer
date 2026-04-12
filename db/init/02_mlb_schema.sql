-- ============================================
-- MLB Advanced Predictor - Schema Extension
-- ============================================

-- Register MLB sport if not already present
INSERT INTO sports (name, display_name) VALUES
    ('mlb', 'MLB')
ON CONFLICT (name) DO NOTHING;

-- ============================================
-- MLB TEAM SEASON STATS
-- Aggregated from pitch-level data + standings
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_team_stats (
    id SERIAL PRIMARY KEY,
    season INT NOT NULL,
    team_name TEXT NOT NULL,
    team_abbr VARCHAR(10),
    mlb_team_id INT,
    games_played INT DEFAULT 0,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    -- Runs
    runs_scored INT DEFAULT 0,
    runs_allowed INT DEFAULT 0,
    rs_per_game FLOAT,
    ra_per_game FLOAT,
    run_diff_per_game FLOAT,
    -- Win pct
    win_pct FLOAT,
    pyth_win_pct FLOAT,
    -- Pitching (team-level)
    era FLOAT,
    whip FLOAT,
    k9 FLOAT,
    bb9 FLOAT,
    -- Batting
    batting_avg FLOAT,
    slg FLOAT,
    obp FLOAT,
    -- Plate Discipline
    k_rate FLOAT,
    bb_rate FLOAT,
    k_bb_ratio FLOAT,
    -- Fielding
    errors_per_game FLOAT,
    dp_rate FLOAT,
    def_efficiency FLOAT,
    -- Baserunning
    sb_success_rate FLOAT,
    sb_rate FLOAT,
    -- Scoring efficiency
    lob_per_game FLOAT,
    -- Day/Night splits
    day_win_pct FLOAT,
    night_win_pct FLOAT,
    -- Metadata
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(season, team_name)
);

-- ============================================
-- MLB PITCHER SEASON STATS
-- Per-pitcher season aggregates
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_pitcher_stats (
    id SERIAL PRIMARY KEY,
    season INT NOT NULL,
    pitcher_id INT NOT NULL,
    pitcher_name TEXT,
    team_name TEXT,
    team_abbr VARCHAR(10),
    throws VARCHAR(1),  -- L/R
    games INT DEFAULT 0,
    games_started INT DEFAULT 0,
    innings_pitched FLOAT DEFAULT 0,
    earned_runs INT DEFAULT 0,
    hits_allowed INT DEFAULT 0,
    walks INT DEFAULT 0,
    strikeouts INT DEFAULT 0,
    era FLOAT,
    whip FLOAT,
    k9 FLOAT,
    bb9 FLOAT,
    -- Advanced
    avg_velocity FLOAT,
    avg_spin_rate FLOAT,
    -- Metadata
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(season, pitcher_id)
);

-- ============================================
-- MLB SP vs OPPONENT HISTORY
-- Starting pitcher performance against specific teams
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_sp_vs_opponent (
    id SERIAL PRIMARY KEY,
    season INT NOT NULL,
    pitcher_id INT NOT NULL,
    opponent_team TEXT NOT NULL,
    games INT DEFAULT 0,
    innings_pitched FLOAT DEFAULT 0,
    earned_runs INT DEFAULT 0,
    strikeouts INT DEFAULT 0,
    era FLOAT,
    k9 FLOAT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(season, pitcher_id, opponent_team)
);

-- ============================================
-- MLB GAME FEATURES + PREDICTIONS
-- Per-game feature vectors, predictions, and actuals
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_game_features (
    id SERIAL PRIMARY KEY,
    game_id INT,
    game_date DATE NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_sp_id INT,
    away_sp_id INT,
    home_sp_name TEXT,
    away_sp_name TEXT,
    -- Feature vector (60+ features stored as JSON for flexibility)
    features JSONB,
    -- Model predictions
    prediction JSONB,
    -- Actual results (filled after game completes)
    actual_home_runs INT,
    actual_away_runs INT,
    actual_winner TEXT,
    actual_total INT,
    -- Odds at prediction time
    home_moneyline INT,
    away_moneyline INT,
    spread FLOAT,
    over_under FLOAT,
    -- Tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(game_date, home_team, away_team)
);

-- ============================================
-- MLB BULLPEN FATIGUE (rolling window)
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_bullpen_log (
    id SERIAL PRIMARY KEY,
    game_date DATE NOT NULL,
    team_name TEXT NOT NULL,
    pitcher_id INT NOT NULL,
    innings_pitched FLOAT DEFAULT 0,
    pitches_thrown INT DEFAULT 0,
    is_starter BOOLEAN DEFAULT FALSE,
    UNIQUE(game_date, team_name, pitcher_id)
);

-- ============================================
-- MLB MODEL TRAINING RUNS
-- Track model performance over time
-- ============================================
CREATE TABLE IF NOT EXISTS mlb_model_runs (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(50) NOT NULL,  -- 'moneyline', 'spread', 'totals'
    trained_at TIMESTAMPTZ DEFAULT NOW(),
    train_size INT,
    test_size INT,
    roc_auc FLOAT,
    accuracy FLOAT,
    brier_score FLOAT,
    log_loss FLOAT,
    feature_importances JSONB,
    hyperparameters JSONB,
    model_path TEXT
);

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX IF NOT EXISTS idx_mlb_team_stats_season ON mlb_team_stats(season);
CREATE INDEX IF NOT EXISTS idx_mlb_team_stats_team ON mlb_team_stats(team_name);
CREATE INDEX IF NOT EXISTS idx_mlb_pitcher_stats_season ON mlb_pitcher_stats(season);
CREATE INDEX IF NOT EXISTS idx_mlb_pitcher_stats_team ON mlb_pitcher_stats(team_name);
CREATE INDEX IF NOT EXISTS idx_mlb_pitcher_stats_pitcher ON mlb_pitcher_stats(pitcher_id);
CREATE INDEX IF NOT EXISTS idx_mlb_sp_vs_opp ON mlb_sp_vs_opponent(season, pitcher_id);
CREATE INDEX IF NOT EXISTS idx_mlb_game_features_date ON mlb_game_features(game_date);
CREATE INDEX IF NOT EXISTS idx_mlb_game_features_teams ON mlb_game_features(home_team, away_team);
CREATE INDEX IF NOT EXISTS idx_mlb_bullpen_log_date ON mlb_bullpen_log(game_date, team_name);
CREATE INDEX IF NOT EXISTS idx_mlb_model_runs_name ON mlb_model_runs(model_name, trained_at DESC);
