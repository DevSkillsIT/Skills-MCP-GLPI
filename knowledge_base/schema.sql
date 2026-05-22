-- =====================================================================
-- knowledge_base schema — GLPI tickets as a vector knowledge base
--
-- Mirrors the reference schema conventions (portuguese_unaccent FTS,
-- halfvec embeddings, HNSW + GIN indexes) so every KB in a deployment shares
-- the same shape and the MCP can query them through one hybrid-search path.
--
-- Requires extensions: vector (>= 0.7 for halfvec), unaccent, pg_trgm.
-- Run them as superuser before this script:
--   CREATE EXTENSION IF NOT EXISTS vector;
--   CREATE EXTENSION IF NOT EXISTS unaccent;
--   CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- =====================================================================

-- ---------------------------------------------------------------------
-- Portuguese text search configuration with unaccent
-- "e-mail" / "email", "solucao" / "solução" hit the same documents.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config WHERE cfgname = 'portuguese_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION portuguese_unaccent (COPY = portuguese);
        ALTER TEXT SEARCH CONFIGURATION portuguese_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, portuguese_stem;
    END IF;
END
$$;

-- ---------------------------------------------------------------------
-- tickets — one resolved GLPI ticket per row
--
-- Structured columns exist for the filters the MCP needs (status, category,
-- dates, entity). Everything else that varies per source lives in `metadata`
-- (JSONB): the "fields can change, the essence cannot" contract. The essence
-- the search path relies on is fixed: body_text + fts + embedding + source_date.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id                  BIGINT      NOT NULL,
    source              TEXT        NOT NULL DEFAULT 'glpi',
    titulo              TEXT        NOT NULL DEFAULT '',
    tipo                TEXT        NOT NULL DEFAULT '',
    status              TEXT        NOT NULL DEFAULT '',
    categoria           TEXT        NOT NULL DEFAULT '',
    prioridade          TEXT        NOT NULL DEFAULT '',
    origem              TEXT        NOT NULL DEFAULT '',
    entidade            TEXT        NOT NULL DEFAULT '',

    -- Source-specific / variable fields (solicitantes, tecnicos, grupos,
    -- urgencia, impacto, localizacao, anexos_docids, acompanhamentos count...).
    metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- The problem statement (form "Descrição"), cleaned to plain text. This is
    -- what gets embedded — titles are boilerplate on form-opened tickets.
    body_text           TEXT        NOT NULL DEFAULT '',
    -- The resolution, kept separate: surfaced on hit, FTS weight B, NOT embedded.
    solution_text       TEXT        NOT NULL DEFAULT '',
    body_hash           TEXT        NOT NULL,

    -- NULL embedding is valid: body too long to embed still gets stored so FTS
    -- can find it (mirrors reference behavior).
    embedding           halfvec(2560),
    embedding_model     TEXT,

    -- Recency lives on source_date (ticket open date). date_mod drives the
    -- incremental change gate alongside body_hash.
    source_date         TIMESTAMPTZ,
    date_mod            TIMESTAMPTZ,

    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A single row identifies a ticket within a source; the same KB table may
    -- hold more than one GLPI instance later.
    PRIMARY KEY (source, id),

    -- Weighted FTS: the problem (Descrição) dominates (A), the solution helps
    -- (B), title + category are weak context (D). ts_rank then favors matches
    -- in the real problem text over the repetitive form boilerplate.
    fts tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('portuguese_unaccent', body_text), 'A') ||
        setweight(to_tsvector('portuguese_unaccent', solution_text), 'B') ||
        setweight(to_tsvector('portuguese_unaccent',
            coalesce(titulo, '') || ' ' || coalesce(categoria, '')), 'D')
    ) STORED
);

-- Vector similarity (cosine) — HNSW for low-latency ANN at this corpus size.
CREATE INDEX IF NOT EXISTS idx_tickets_embedding
    ON tickets USING hnsw (embedding halfvec_cosine_ops);

-- Full-text search (hybrid half).
CREATE INDEX IF NOT EXISTS idx_tickets_fts
    ON tickets USING gin (fts);

-- Recency filtering / purge.
CREATE INDEX IF NOT EXISTS idx_tickets_source_date
    ON tickets (source_date);

-- Common metadata filters (e.g. entity-scoped queries).
CREATE INDEX IF NOT EXISTS idx_tickets_metadata
    ON tickets USING gin (metadata);

-- ---------------------------------------------------------------------
-- sync_state — single-row checkpoint for the incremental ETL
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_state (
    id                  INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_sync_at        TIMESTAMPTZ,
    last_status         TEXT        NOT NULL DEFAULT 'never',
    last_ticket_count   INTEGER     NOT NULL DEFAULT 0,
    last_changed_count  INTEGER     NOT NULL DEFAULT 0,
    last_duration_sec   INTEGER     NOT NULL DEFAULT 0,
    last_error          TEXT,
    error_count         INTEGER     NOT NULL DEFAULT 0
);

INSERT INTO sync_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
