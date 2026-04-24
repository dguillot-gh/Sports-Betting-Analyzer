-- ============================================
-- Migration: Add updated_at to results table
-- Date: 2026-04-21
-- Purpose: Track when results rows are inserted or updated
--          so the import pipeline can capture detailed records.
-- ============================================

-- 1. Add the column (defaults to NOW() for new rows)
ALTER TABLE results ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 2. Back-fill existing rows that pre-date this migration
UPDATE results SET updated_at = created_at WHERE updated_at IS NULL;

-- 3. Trigger to auto-set updated_at on every INSERT or UPDATE
CREATE OR REPLACE FUNCTION update_results_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_results_updated_at ON results;
CREATE TRIGGER trg_results_updated_at
    BEFORE INSERT OR UPDATE ON results
    FOR EACH ROW
    EXECUTE FUNCTION update_results_updated_at();

-- 4. Index for fast range queries during import record collection
CREATE INDEX IF NOT EXISTS idx_results_updated_at ON results(updated_at);

-- ============================================
-- DONE
-- ============================================
