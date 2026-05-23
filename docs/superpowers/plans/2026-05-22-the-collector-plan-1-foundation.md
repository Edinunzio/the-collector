# The Collector — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the full project structure, Docker environment, Postgres schema, and shared DB pool — everything the crawler and API plans depend on.

**Architecture:** Five Docker containers (api, crawler, celery, db, redis) sharing one image built from a single Dockerfile. Postgres schema uses a generated `tsvector` column (no triggers needed) with a GIN index for FTS. Raw `asyncpg` throughout — no ORM.

**Tech Stack:** Python 3.12, asyncpg, FastAPI, Celery, Redis, Postgres 16, Docker Compose, pytest + pytest-asyncio

---

## File Map

| File | Role |
|---|---|
| `pyproject.toml` | Dependencies + pytest config |
| `Dockerfile` | Single image for api/crawler/celery |
| `docker-compose.yml` | All five services |
| `.env.example` | Template for local config |
| `collector/__init__.py` | Package root |
| `collector/config.py` | Pydantic-settings config (env-driven) |
| `collector/db.py` | Shared asyncpg connection pool |
| `migrations/001_initial_schema.sql` | Full schema: pages, quarantine, crawl_queue, seeds, threat_log, blocked_domains |
| `migrations/run_migrations.py` | CLI runner for .sql files |
| `seeds.txt` | Hand-curated seed URLs, committed to repo |
| `tests/conftest.py` | Session-scoped test DB setup, transaction-isolated fixtures |
| `tests/test_foundation.py` | Schema smoke tests |

---

### Task 1: pyproject.toml + Dockerfile + docker-compose.yml

**Files:**
- Create: `pyproject.toml`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.dockerignore`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "the-collector"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.2.0",
    "chardet>=5.2.0",
    "asyncpg>=0.29.0",
    "celery[redis]>=5.4.0",
    "pydantic-settings>=2.3.0",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-httpserver>=1.0.0",
    "respx>=0.21.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["collector"]
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# lxml needs libxml2 and libxslt at build time
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: collector
      POSTGRES_PASSWORD: collector
      POSTGRES_DB: collector
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U collector"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build: .
    command: uvicorn collector.api.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - .:/app

  crawler:
    build: .
    command: python -m collector.crawler.worker
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - .:/app

  celery:
    build: .
    command: celery -A collector.tasks.celery_app worker -B --loglevel=info
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - .:/app

volumes:
  postgres_data:
```

- [ ] **Step 4: Create .env.example**

```ini
DATABASE_URL=postgresql://collector:collector@db:5432/collector
REDIS_URL=redis://redis:6379/0

CRAWL_WORKERS=5
CRAWL_DELAY_SECONDS=2.0
CRAWL_DEPTH_MAX=3
CRAWL_DOMAIN_PAGE_CAP=500

SIGNAL_THRESHOLD=3

RESPONSE_SIZE_LIMIT_BYTES=5242880
CHARDET_CONFIDENCE_THRESHOLD=0.7
HTTPX_CONNECT_TIMEOUT=10.0
HTTPX_READ_TIMEOUT=30.0
PAGE_PROCESS_TIMEOUT=30.0
```

- [ ] **Step 5: Create .dockerignore**

```
.git
.env
__pycache__
*.pyc
*.egg-info
.pytest_cache
tests/
*.db
```

- [ ] **Step 6: Copy .env.example to .env for local dev**

```bash
cp .env.example .env
# Edit DATABASE_URL to use localhost instead of 'db' for running tests outside Docker:
# DATABASE_URL=postgresql://collector:collector@localhost:5432/collector
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml Dockerfile docker-compose.yml .env.example .dockerignore
git commit -m "feat: project scaffold — Docker, deps, compose"
```

---

### Task 2: Config + package structure

**Files:**
- Create: `collector/__init__.py`
- Create: `collector/config.py`
- Create: `collector/crawler/__init__.py`
- Create: `collector/signals/__init__.py`
- Create: `collector/indexer/__init__.py`
- Create: `collector/tasks/__init__.py`
- Create: `collector/api/__init__.py`
- Create: `collector/api/routes/__init__.py`
- Create: `seeds.txt`

- [ ] **Step 1: Create all __init__.py files (empty)**

```bash
mkdir -p collector/crawler collector/signals collector/indexer collector/tasks collector/api/routes
touch collector/__init__.py
touch collector/crawler/__init__.py
touch collector/signals/__init__.py
touch collector/indexer/__init__.py
touch collector/tasks/__init__.py
touch collector/api/__init__.py
touch collector/api/routes/__init__.py
mkdir -p tests/fixtures migrations
touch tests/__init__.py
```

- [ ] **Step 2: Create collector/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://collector:collector@localhost:5432/collector"
    redis_url: str = "redis://localhost:6379/0"

    crawl_workers: int = 5
    crawl_delay_seconds: float = 2.0
    crawl_depth_max: int = 3
    crawl_domain_page_cap: int = 500

    signal_threshold: int = 3

    response_size_limit_bytes: int = 5 * 1024 * 1024  # 5MB
    chardet_confidence_threshold: float = 0.7
    httpx_connect_timeout: float = 10.0
    httpx_read_timeout: float = 30.0
    page_process_timeout: float = 30.0


settings = Settings()
```

- [ ] **Step 3: Create seeds.txt with starter seeds**

```
# Hand-curated old-web seeds — one URL per line, # for comments
https://neocities.org/browse
https://tilde.town
https://wiby.me/surprise/
https://curlie.org
https://indieweb.org/directory
https://ooh.directory
```

- [ ] **Step 4: Commit**

```bash
git add collector/ seeds.txt migrations/ tests/
git commit -m "feat: package structure, config, seed list"
```

---

### Task 3: Database schema

**Files:**
- Create: `migrations/001_initial_schema.sql`
- Create: `migrations/run_migrations.py`

- [ ] **Step 1: Create migrations/001_initial_schema.sql**

```sql
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
```

- [ ] **Step 2: Create migrations/run_migrations.py**

```python
"""Run all SQL migration files in order. Safe to re-run (IF NOT EXISTS throughout)."""
import asyncio
import asyncpg
import sys
from pathlib import Path

# Allow running from project root: python -m migrations.run_migrations
sys.path.insert(0, str(Path(__file__).parent.parent))
from collector.config import settings


async def run_migrations(db_url: str | None = None) -> None:
    url = db_url or settings.database_url
    conn = await asyncpg.connect(dsn=url)
    try:
        migrations_dir = Path(__file__).parent
        sql_files = sorted(migrations_dir.glob("*.sql"))
        if not sql_files:
            print("No migration files found.")
            return
        for migration_file in sql_files:
            print(f"Running {migration_file.name}...")
            sql = migration_file.read_text()
            await conn.execute(sql)
            print(f"  ✓ Done")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
```

- [ ] **Step 3: Commit**

```bash
git add migrations/
git commit -m "feat: database schema with FTS, quarantine, threat log"
```

---

### Task 4: Shared DB pool

**Files:**
- Create: `collector/db.py`

- [ ] **Step 1: Create collector/db.py**

```python
"""Shared asyncpg connection pool. Import get_pool() wherever DB access is needed."""
from __future__ import annotations
import asyncpg
from collector.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the shared pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    """Cleanly close the pool. Call on application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

- [ ] **Step 2: Commit**

```bash
git add collector/db.py
git commit -m "feat: shared asyncpg connection pool"
```

---

### Task 5: Test infrastructure + schema smoke tests

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_foundation.py`

- [ ] **Step 1: Start Postgres via Docker Compose (run in a separate terminal)**

```bash
docker compose up db -d
# Wait for it to be healthy:
docker compose ps
```

Expected output: `db` shows `healthy`.

- [ ] **Step 2: Create the test database**

```bash
docker compose exec db psql -U collector -c "CREATE DATABASE collector_test;"
```

Expected: `CREATE DATABASE`

- [ ] **Step 3: Create tests/conftest.py**

```python
"""
Shared test fixtures.

Test isolation strategy: each test runs inside a transaction that is rolled back
after the test. This means tests don't pollute each other and the DB stays clean
without truncating tables between runs.

Requires a running Postgres at TEST_DATABASE_URL (see .env or set the env var).
The test DB must already exist — run: docker compose exec db psql -U collector -c "CREATE DATABASE collector_test;"
"""
import asyncio
import asyncpg
import pytest
from pathlib import Path

TEST_DATABASE_URL = "postgresql://collector:collector@localhost:5432/collector_test"


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def migrated_db() -> str:
    """Run migrations against the test DB once per session. Returns the test DB URL."""
    conn = await asyncpg.connect(dsn=TEST_DATABASE_URL)
    migrations_dir = Path(__file__).parent.parent / "migrations"
    for f in sorted(migrations_dir.glob("*.sql")):
        await conn.execute(f.read_text())
    await conn.close()
    return TEST_DATABASE_URL


@pytest.fixture
async def db(migrated_db: str) -> asyncpg.Connection:
    """
    Per-test DB connection wrapped in a rolled-back transaction.
    Any inserts/updates made during the test are invisible to other tests.
    """
    conn = await asyncpg.connect(dsn=migrated_db)
    tr = conn.transaction()
    await tr.start()
    yield conn
    await tr.rollback()
    await conn.close()
```

- [ ] **Step 4: Write failing tests in tests/test_foundation.py**

```python
"""Smoke tests: verify the schema created all expected tables and indexes."""
import pytest
import asyncpg


EXPECTED_TABLES = {
    "pages",
    "quarantine",
    "crawl_queue",
    "seeds",
    "threat_log",
    "blocked_domains",
}

EXPECTED_INDEXES = {
    "pages_search_idx",
    "pages_domain_idx",
    "pages_recrawl_idx",
    "quarantine_unreviewed_idx",
    "crawl_queue_work_idx",
    "blocked_domains_lookup_idx",
}


async def test_all_tables_exist(db: asyncpg.Connection) -> None:
    rows = await db.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    tables = {r["tablename"] for r in rows}
    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"


async def test_all_indexes_exist(db: asyncpg.Connection) -> None:
    rows = await db.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    )
    indexes = {r["indexname"] for r in rows}
    assert EXPECTED_INDEXES.issubset(indexes), f"Missing indexes: {EXPECTED_INDEXES - indexes}"


async def test_pages_search_vector_is_generated(db: asyncpg.Connection) -> None:
    """Insert a page without setting search_vector — Postgres should populate it."""
    await db.execute(
        """
        INSERT INTO pages (url, domain, title, raw_text)
        VALUES ($1, $2, $3, $4)
        """,
        "http://example.com/test",
        "example.com",
        "My Tropical Fish",
        "I love keeping oscar fish in my tank",
    )
    row = await db.fetchrow(
        "SELECT search_vector FROM pages WHERE url = $1",
        "http://example.com/test",
    )
    assert row is not None
    assert row["search_vector"] is not None
    sv = str(row["search_vector"])
    assert "fish" in sv or "tropical" in sv


async def test_pages_fts_query_works(db: asyncpg.Connection) -> None:
    """Verify ts_rank_cd query returns results."""
    await db.execute(
        """
        INSERT INTO pages (url, domain, title, raw_text)
        VALUES ($1, $2, $3, $4)
        """,
        "http://fishluv99.example.com/tank.html",
        "fishluv99.example.com",
        "My Tropical Tank Setup!!",
        "I got my first oscar in 1998 and never looked back. Cichlids rule.",
    )
    rows = await db.fetch(
        """
        SELECT url, ts_rank_cd(search_vector, query) AS rank
        FROM pages, to_tsquery('english', 'oscar') query
        WHERE search_vector @@ query
        ORDER BY rank DESC
        """,
    )
    assert len(rows) == 1
    assert "fishluv99" in rows[0]["url"]


async def test_transaction_isolation(db: asyncpg.Connection) -> None:
    """Each test's inserts should not persist after rollback."""
    count_before = await db.fetchval("SELECT COUNT(*) FROM pages")
    await db.execute(
        "INSERT INTO pages (url, domain) VALUES ($1, $2)",
        "http://isolation-test.example.com/",
        "isolation-test.example.com",
    )
    count_during = await db.fetchval("SELECT COUNT(*) FROM pages")
    assert count_during == count_before + 1
    # After the test, the fixture rolls back — next test sees count_before again
```

- [ ] **Step 5: Run the failing tests**

```bash
pip install -e ".[dev]"
pytest tests/test_foundation.py -v
```

Expected: All 4 tests **FAIL** because migrations haven't run against the test DB yet (or the DB doesn't exist).

- [ ] **Step 6: Run migrations against test DB**

```bash
python -c "
import asyncio, asyncpg
from pathlib import Path

async def main():
    conn = await asyncpg.connect('postgresql://collector:collector@localhost:5432/collector_test')
    for f in sorted(Path('migrations').glob('*.sql')):
        print(f'Running {f.name}...')
        await conn.execute(f.read_text())
    await conn.close()
    print('Done.')

asyncio.run(main())
"
```

Expected: Each migration file prints and completes.

- [ ] **Step 7: Run tests — expect PASS**

```bash
pytest tests/test_foundation.py -v
```

Expected output:
```
tests/test_foundation.py::test_all_tables_exist PASSED
tests/test_foundation.py::test_all_indexes_exist PASSED
tests/test_foundation.py::test_pages_search_vector_is_generated PASSED
tests/test_foundation.py::test_pages_fts_query_works PASSED
tests/test_foundation.py::test_transaction_isolation PASSED
```

- [ ] **Step 8: Commit**

```bash
git add tests/
git commit -m "test: schema smoke tests — FTS, generated column, transaction isolation"
```

---

### Task 6: Docker build verification

- [ ] **Step 1: Build the image**

```bash
docker compose build
```

Expected: Build completes with no errors. lxml and asyncpg compile successfully.

- [ ] **Step 2: Run migrations inside Docker**

```bash
docker compose up db -d
docker compose run --rm api python -m migrations.run_migrations
```

Expected:
```
Running 001_initial_schema.sql...
  ✓ Done
```

- [ ] **Step 3: Verify the API container starts (stub — no routes yet)**

Create a minimal `collector/api/main.py` so the container doesn't crash:

```python
from fastapi import FastAPI

app = FastAPI(title="The Collector", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 4: Start all services and hit the health endpoint**

```bash
docker compose up -d
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add collector/api/main.py
git commit -m "feat: stub FastAPI app with health endpoint, Docker verified"
```

---

## What's Next

**Plan 2 — Signal Engine** (`2026-05-22-the-collector-plan-2-signals.md`)
Implements `collector/signals/detectors.py` and `collector/signals/filter.py` with full TDD using HTML fixtures. This is the soul of the engine — every scoring decision lives here.

**Plan 3 — Crawler** (`2026-05-22-the-collector-plan-3-crawler.md`)
Implements `security.py`, `robots.py`, `queue.py`, `cdx.py`, and `worker.py`. Depends on Plan 2 (filter) and Plan 1 (DB pool).

**Plan 4 — API + Tasks** (`2026-05-22-the-collector-plan-4-api.md`)
All FastAPI routes + Celery tasks. Depends on Plans 1-3.
