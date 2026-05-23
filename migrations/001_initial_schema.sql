-- The Collector: initial schema
-- Requires Postgres 12+ for GENERATED ALWAYS AS STORED columns

CREATE TABLE IF NOT EXISTS pages (
    id              SERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    domain          TEXT NOT NULL,
    title           TEXT,
    raw_text        TEXT,
    -- tsvector generated from title (weight A) + raw_text (weight B)
    -- STORED means Postgres maintains it automatically; no trigger needed
    search_vector   TSVECTOR GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
                        setweight(to_tsvector('english', COALESCE(raw_text, '')), 'B')
                    ) STORED,
    old_web_score   INTEGER NOT NULL DEFAULT 0,
    page_size_bytes INTEGER,
    detected_signals JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active', -- active | dead
    crawled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_crawl_at   TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS pages_search_idx    ON pages USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS pages_domain_idx    ON pages(domain);
CREATE INDEX IF NOT EXISTS pages_recrawl_idx   ON pages(next_crawl_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS pages_status_idx    ON pages(status);


CREATE TABLE IF NOT EXISTS quarantine (
    id              SERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    raw_html        TEXT,
    error_reason    TEXT NOT NULL,  -- parse_error | encoding_uncertain | borderline_score | frameset | mixed_signals | empty_body
    partial_signals JSONB NOT NULL DEFAULT '{}',
    partial_score   INTEGER NOT NULL DEFAULT 0,
    http_status     INTEGER,
    fetch_error     TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS quarantine_unreviewed_idx ON quarantine(reviewed, fetched_at);
CREATE INDEX IF NOT EXISTS quarantine_reason_idx     ON quarantine(error_reason);


CREATE TABLE IF NOT EXISTS crawl_queue (
    id              SERIAL PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    source_url      TEXT,
    depth           INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS crawl_queue_work_idx ON crawl_queue(status, next_attempt_at)
    WHERE status IN ('pending', 'in_progress');


CREATE TABLE IF NOT EXISTS seeds (
    id        SERIAL PRIMARY KEY,
    url       TEXT UNIQUE NOT NULL,
    label     TEXT,
    source    TEXT NOT NULL DEFAULT 'manual',  -- manual | cdx | file
    added_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS threat_log (
    id            SERIAL PRIMARY KEY,
    url           TEXT NOT NULL,
    domain        TEXT NOT NULL,
    threat_type   TEXT NOT NULL,  -- ssrf_attempt | gzip_bomb | spider_trap | redirect_violation | slow_response | recursion_bomb | oversized_response
    detail        TEXT,
    http_status   INTEGER,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain_blocked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS threat_log_domain_idx  ON threat_log(domain);
CREATE INDEX IF NOT EXISTS threat_log_type_idx    ON threat_log(threat_type);
CREATE INDEX IF NOT EXISTS threat_log_flagged_idx ON threat_log(domain_blocked) WHERE domain_blocked = FALSE;


CREATE TABLE IF NOT EXISTS blocked_domains (
    id         SERIAL PRIMARY KEY,
    domain     TEXT UNIQUE NOT NULL,
    reason     TEXT,
    source     TEXT NOT NULL DEFAULT 'manual',  -- manual | auto
    blocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS blocked_domains_lookup_idx ON blocked_domains(domain);
