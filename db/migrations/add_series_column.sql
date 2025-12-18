-- ============================================
-- Add Series Column Migration
-- Run this on your PostgreSQL database
-- ============================================

-- Add series column to entities table
ALTER TABLE entities ADD COLUMN IF NOT EXISTS series VARCHAR(50);

-- Add series column to results table  
ALTER TABLE results ADD COLUMN IF NOT EXISTS series VARCHAR(50);

-- Add series column to stats table
ALTER TABLE stats ADD COLUMN IF NOT EXISTS series VARCHAR(50);

-- Create indexes for series column
CREATE INDEX IF NOT EXISTS idx_entities_series ON entities(series);
CREATE INDEX IF NOT EXISTS idx_results_series ON results(series);
CREATE INDEX IF NOT EXISTS idx_stats_series ON stats(series);

-- Update unique constraint on entities to include series
-- First drop the old constraint
ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_sport_id_name_type_key;

-- Create new unique constraint including series
ALTER TABLE entities ADD CONSTRAINT entities_sport_id_name_type_series_key 
    UNIQUE(sport_id, name, type, series);

-- ============================================
-- DONE
-- ============================================
-- Run this migration before re-importing data
