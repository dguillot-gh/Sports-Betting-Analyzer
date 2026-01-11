-- ============================================
-- Migration: Fix Player Uniqueness
-- Date: 2026-01-10
-- ============================================

-- The previous unique constraint entities_sport_id_name_type_series_key
-- was too strict for players since multiple players can have the same name.
-- We should rely on content_hash (gsis_id based) for player uniqueness.

-- 1. Drop the overly strict unique constraint
ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_sport_id_name_type_series_key;

-- 2. Add a non-unique index for fast name lookups
CREATE INDEX IF NOT EXISTS idx_entities_name_lookup ON entities(name, sport_id, type);

-- 3. (Optional) Re-add a unique index for teams/series if we want to stay strict on non-players
-- For now, we rely on the importer's ON CONFLICT (content_hash) logic which is more robust.
-- The content_hash includes the player_id/gsis_id so it's globally unique for NFL players.

-- DONE
