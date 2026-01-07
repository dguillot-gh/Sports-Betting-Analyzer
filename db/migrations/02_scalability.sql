-- ============================================
-- Migration: Scalability Improvements
-- Date: 2026-01-07
-- ============================================

-- ============================================
-- 1. EVENT VERSIONING FOR ODDS (Line Movement Tracking)
-- ============================================
-- Instead of overwriting odds, we version them.
-- This allows tracking line movement over time.

CREATE TABLE IF NOT EXISTS odds_history (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(100) NOT NULL,
    sport VARCHAR(20) NOT NULL,
    sportsbook VARCHAR(50),
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Odds snapshot
    spread DECIMAL(5,2),
    spread_odds INTEGER,
    total DECIMAL(5,2),
    total_over_odds INTEGER,
    total_under_odds INTEGER,
    home_ml INTEGER,
    away_ml INTEGER,
    
    -- Metadata
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(50),  -- 'api', 'manual', 'scrape'
    
    -- Composite unique constraint for versioning
    CONSTRAINT unique_odds_version UNIQUE (game_id, sportsbook, version)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_odds_history_game ON odds_history(game_id);
CREATE INDEX IF NOT EXISTS idx_odds_history_captured ON odds_history(captured_at);
CREATE INDEX IF NOT EXISTS idx_odds_history_sport_date ON odds_history(sport, captured_at);

-- View to get latest odds per game/sportsbook
CREATE OR REPLACE VIEW latest_odds AS
SELECT DISTINCT ON (game_id, sportsbook)
    *
FROM odds_history
ORDER BY game_id, sportsbook, version DESC;


-- ============================================
-- 2. ADDITIONAL INDEXES FOR BETS TABLE
-- ============================================

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_bets_sport_outcome ON bets(sport, outcome);
CREATE INDEX IF NOT EXISTS idx_bets_created_outcome ON bets(created_at, outcome);
CREATE INDEX IF NOT EXISTS idx_bets_sportsbook ON bets(sportsbook);

-- Partial index for pending bets (faster lookups for active bets)
CREATE INDEX IF NOT EXISTS idx_bets_pending 
    ON bets(created_at DESC) WHERE outcome = 'pending';


-- ============================================
-- 3. MATERIALIZED VIEW FOR BETTING ANALYTICS
-- ============================================

CREATE MATERIALIZED VIEW IF NOT EXISTS betting_stats_daily AS
SELECT 
    DATE(created_at) as bet_date,
    sport,
    sportsbook,
    COUNT(*) as total_bets,
    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN outcome = 'cashout' THEN 1 ELSE 0 END) as cashouts,
    COALESCE(SUM(stake), 0) as total_staked,
    COALESCE(SUM(profit), 0) as daily_profit,
    COALESCE(SUM(cashout_amount), 0) as total_cashout_amount
FROM bets
WHERE outcome != 'pending'
GROUP BY DATE(created_at), sport, sportsbook;

CREATE UNIQUE INDEX IF NOT EXISTS idx_betting_stats_daily_pk 
    ON betting_stats_daily(bet_date, sport, sportsbook);


-- ============================================
-- 4. FUNCTION TO INCREMENT ODDS VERSION
-- ============================================

CREATE OR REPLACE FUNCTION insert_odds_version(
    p_game_id VARCHAR,
    p_sport VARCHAR,
    p_sportsbook VARCHAR,
    p_spread DECIMAL,
    p_total DECIMAL,
    p_home_ml INTEGER,
    p_away_ml INTEGER,
    p_source VARCHAR DEFAULT 'api'
) RETURNS INTEGER AS $$
DECLARE
    v_next_version INTEGER;
BEGIN
    -- Get next version number
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_next_version
    FROM odds_history
    WHERE game_id = p_game_id AND sportsbook = p_sportsbook;
    
    -- Insert new version
    INSERT INTO odds_history (
        game_id, sport, sportsbook, version,
        spread, total, home_ml, away_ml, source
    ) VALUES (
        p_game_id, p_sport, p_sportsbook, v_next_version,
        p_spread, p_total, p_home_ml, p_away_ml, p_source
    );
    
    RETURN v_next_version;
END;
$$ LANGUAGE plpgsql;


-- ============================================
-- 5. FUNCTION TO REFRESH MATERIALIZED VIEW
-- ============================================

CREATE OR REPLACE FUNCTION refresh_betting_stats() 
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY betting_stats_daily;
END;
$$ LANGUAGE plpgsql;


-- ============================================
-- DONE
-- ============================================
-- Run this migration with: psql -U sports_user -d sports_betting -f 02_scalability.sql
