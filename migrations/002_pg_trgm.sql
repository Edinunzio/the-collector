-- Enable pg_trgm for fuzzy (trigram-based) title matching.
-- Complements the existing tsvector FTS — trigrams catch typos and near-misses
-- that FTS lexeme stemming misses entirely (e.g. "geociteis" → "geocities").
--
-- We index title only (not raw_text) because:
--   1. similarity() on long text is both slow and meaningless
--   2. title is the highest-signal field for identity matching

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS pages_title_trgm_idx
    ON pages USING GIN(title gin_trgm_ops);
