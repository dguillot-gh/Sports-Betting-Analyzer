-- ============================================
-- SQL Migration: Add model_performance tracking table
-- ============================================

CREATE TABLE IF NOT EXISTS model_performance (
    id SERIAL PRIMARY KEY,
    sport_id INTEGER REFERENCES sports(id),
    total_bets INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    win_rate NUMERIC(10, 4) DEFAULT 0,
    total_staked NUMERIC(12, 2) DEFAULT 0,
    total_profit NUMERIC(12, 2) DEFAULT 0,
    roi NUMERIC(10, 4) DEFAULT 0,
    sharpe_ratio NUMERIC(10, 4) DEFAULT 0,
    max_drawdown NUMERIC(12, 2) DEFAULT 0,
    avg_edge NUMERIC(10, 4) DEFAULT 0,
    final_bankroll NUMERIC(15, 2) DEFAULT 0,
    by_season JSONB DEFAULT '[]',
    bet_history JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for querying by sport ID and creation time
CREATE INDEX IF NOT EXISTS idx_model_performance_sport ON model_performance(sport_id);
CREATE INDEX IF NOT EXISTS idx_model_performance_created ON model_performance(created_at DESC);
