-- ============================================
-- Sports Betting Analyzer - Database Schema
-- This script runs automatically on first container start
-- ============================================

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- CORE TABLES
-- ============================================

-- Sports reference
CREATE TABLE IF NOT EXISTS sports (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    config JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert default sports
INSERT INTO sports (name, display_name) VALUES
    ('nascar', 'NASCAR'),
    ('nfl', 'NFL'),
    ('nba', 'NBA')
ON CONFLICT (name) DO NOTHING;

-- Entities (Teams, Drivers, Players)
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,  -- 'team', 'driver', 'player'
    abbreviation VARCHAR(20),
    metadata JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(sport_id, name, type)
);

-- Game/Race Results
CREATE TABLE IF NOT EXISTS results (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    week INTEGER,
    game_date DATE,
    
    -- For team sports (NFL/NBA)
    home_entity_id INTEGER REFERENCES entities(id),
    away_entity_id INTEGER REFERENCES entities(id),
    home_score DECIMAL(10,2),
    away_score DECIMAL(10,2),
    
    -- For racing (NASCAR)
    track VARCHAR(255),
    race_name VARCHAR(255),
    
    -- Flexible data storage
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Race/Game Participants (for NASCAR driver results per race)
CREATE TABLE IF NOT EXISTS race_results (
    id SERIAL PRIMARY KEY,
    result_id INTEGER REFERENCES results(id) ON DELETE CASCADE,
    entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    start_position INTEGER,
    finish_position INTEGER,
    laps_completed INTEGER,
    laps_led INTEGER,
    points DECIMAL(10,2),
    status VARCHAR(50),  -- 'running', 'dnf', 'dq'
    metadata JSONB DEFAULT '{}',
    UNIQUE(result_id, entity_id)
);

-- Player/Driver Statistics
CREATE TABLE IF NOT EXISTS stats (
    id SERIAL PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    season INTEGER,
    stat_date DATE,
    stat_type VARCHAR(50),  -- 'game', 'season', 'career'
    stats JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ML Models Registry
CREATE TABLE IF NOT EXISTS models (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id),
    name VARCHAR(255),
    task VARCHAR(50),  -- 'classification', 'regression'
    model_type VARCHAR(50),  -- 'random_forest', 'xgboost'
    model_path VARCHAR(500),
    metrics JSONB DEFAULT '{}',
    hyperparameters JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    trained_at TIMESTAMP DEFAULT NOW()
);

-- Predictions History
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    model_id INTEGER REFERENCES models(id) ON DELETE CASCADE,
    result_id INTEGER REFERENCES results(id),
    input_data JSONB,
    prediction JSONB,
    confidence DECIMAL(5,4),
    was_correct BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

-- User Bets (for future bet tracking feature)
CREATE TABLE IF NOT EXISTS bets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,  -- Future: link to auth
    result_id INTEGER REFERENCES results(id),
    bet_type VARCHAR(50),  -- 'spread', 'moneyline', 'total', 'prop'
    pick VARCHAR(255),
    odds DECIMAL(10,2),
    stake DECIMAL(10,2),
    payout DECIMAL(10,2),
    outcome VARCHAR(20),  -- 'win', 'loss', 'push', 'pending'
    placed_at TIMESTAMP DEFAULT NOW(),
    settled_at TIMESTAMP
);

-- Data Import History
CREATE TABLE IF NOT EXISTS import_history (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id),
    source VARCHAR(100),
    file_name VARCHAR(255),
    rows_imported INTEGER,
    status VARCHAR(50),  -- 'success', 'failed', 'partial'
    error_message TEXT,
    imported_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_entities_sport ON entities(sport_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_results_sport_season ON results(sport_id, season);
CREATE INDEX IF NOT EXISTS idx_results_date ON results(game_date);
CREATE INDEX IF NOT EXISTS idx_race_results_entity ON race_results(entity_id);
CREATE INDEX IF NOT EXISTS idx_stats_entity ON stats(entity_id);
CREATE INDEX IF NOT EXISTS idx_stats_date ON stats(stat_date);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON predictions(model_id);
CREATE INDEX IF NOT EXISTS idx_bets_outcome ON bets(outcome);

-- ============================================
-- VIEWS
-- ============================================

-- Latest model for each sport/task combination
CREATE OR REPLACE VIEW latest_models AS
SELECT DISTINCT ON (sport_id, task)
    m.*,
    s.name as sport_name
FROM models m
JOIN sports s ON s.id = m.sport_id
WHERE m.is_active = TRUE
ORDER BY sport_id, task, trained_at DESC;

-- ============================================
-- FUNCTIONS
-- ============================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to entities table
DROP TRIGGER IF EXISTS entities_updated_at ON entities;
CREATE TRIGGER entities_updated_at
    BEFORE UPDATE ON entities
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================
-- DONE
-- ============================================
-- Database initialized successfully!
