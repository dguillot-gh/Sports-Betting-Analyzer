-- ============================================
-- SQL Migration: Fix Schema Drift
-- ============================================

-- Fix 1: Add missing description column to sports table
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'sports' AND column_name = 'description') THEN
        ALTER TABLE sports ADD COLUMN description TEXT;
    END IF;
END $$;

-- Fix 2: Add missing new_rows_imported column to import_logs table
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'import_logs' AND column_name = 'new_rows_imported') THEN
        ALTER TABLE import_logs ADD COLUMN new_rows_imported INTEGER DEFAULT 0;
    END IF;
END $$;

-- Fix 3: Ensure nba_odds_history table exists
CREATE TABLE IF NOT EXISTS nba_odds_history (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(50),
    sportsbook VARCHAR(50),
    home_moneyline INTEGER,
    away_moneyline INTEGER,
    home_spread NUMERIC(5, 1),
    away_spread NUMERIC(5, 1),
    over_under NUMERIC(5, 1),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Fix 4: Ensure deployments table exists
CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deployment_id VARCHAR(100) UNIQUE NOT NULL,
    version VARCHAR(50) NOT NULL,
    git_sha VARCHAR(40),
    git_branch VARCHAR(100),
    build_time TIMESTAMP,
    environment VARCHAR(50) DEFAULT 'development',
    status VARCHAR(20) DEFAULT 'pending',
    description TEXT,
    deployed_by VARCHAR(100),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Fix 5: Ensure deployment_components table exists
CREATE TABLE IF NOT EXISTS deployment_components (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deployment_id UUID REFERENCES deployments(id) ON DELETE CASCADE,
    component_name VARCHAR(50) NOT NULL,
    component_version VARCHAR(50) NOT NULL,
    component_sha VARCHAR(40),
    image_tag VARCHAR(200),
    status VARCHAR(20) DEFAULT 'pending',
    health_check_url VARCHAR(500),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    rollback_info JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(deployment_id, component_name)
);

-- Fix 6: Ensure model_performance table exists
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

-- Ensure indexes for model_performance
CREATE INDEX IF NOT EXISTS idx_model_performance_sport ON model_performance(sport_id);
CREATE INDEX IF NOT EXISTS idx_model_performance_created ON model_performance(created_at DESC);
