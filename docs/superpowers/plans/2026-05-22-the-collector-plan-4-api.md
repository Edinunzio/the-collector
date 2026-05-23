# The Collector — Plan 4: API + Tasks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all FastAPI routes (search, seeds, crawl control, quarantine, threats) and Celery background tasks (re-crawl, dead link check, CDX import). After this plan the full stack is runnable end-to-end via `docker compose up`.

**Architecture:** One FastAPI app with route modules registered at startup. Lifespan hook opens/closes the DB pool. All routes use `asyncpg` directly via the shared pool. Celery runs in its own container, shares the same DB. Search uses `ts_rank_cd` with `ts_headline` for snippets.

**Tech Stack:** FastAPI, asyncpg, Celery + Redis, httpx, pytest + pytest-asyncio

**Depends on:** Plans 1-3 (schema, signal filter, crawler, indexer)

---

## File Map

| File | Role |
|---|---|
| `collector/api/main.py` | FastAPI app + lifespan (DB pool open/close) |
| `collector/api/routes/search.py` | `GET /search` — BM25-style full-text search |
| `collector/api/routes/seeds.py` | `POST/GET /seeds`, `POST /seeds/bulk` |
| `collector/api/routes/crawl.py` | `POST /crawl/start`, `GET /crawl/status` |
| `collector/api/routes/pages.py` | `GET /pages/{id}`, `DELETE /pages/{id}`, `GET /stats` |
| `collector/api/routes/quarantine.py` | Quarantine CRUD + approve/reject/rescore |
| `collector/api/routes/threats.py` | Threat log + blocked domains management |
| `collector/api/routes/tasks.py` | `POST /tasks/import-cdx` |
| `collector/tasks/celery_app.py` | Celery app, beat schedule, task definitions |
| `tests/test_api.py` | Full route tests via FastAPI test client |
| `tests/test_tasks.py` | Celery task tests with mocked dependencies |

---

### Task 1: FastAPI app + lifespan

**Files:**
- Modify: `collector/api/main.py`

- [ ] **Step 1: Replace stub main.py with full app**

```python
"""
FastAPI application entry point.
The lifespan context manager ensures the DB pool is created once on startup
and cleanly closed on shutdown — no connection leaks across requests.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from collector.db import get_pool, close_pool
from collector.api.routes import (
    search,
    seeds,
    crawl,
    pages,
    quarantine,
    threats,
    tasks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()   # warm up pool
    yield
    await close_pool()


app = FastAPI(
    title="The Collector",
    description="A poor man's search engine for the weird old-school internet.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(search.router, tags=["search"])
app.include_router(seeds.router, tags=["seeds"])
app.include_router(crawl.router, tags=["crawl"])
app.include_router(pages.router, tags=["pages"])
app.include_router(quarantine.router, tags=["quarantine"])
app.include_router(threats.router, tags=["threats"])
app.include_router(tasks.router, tags=["tasks"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 2: Create empty route stubs so the app imports**

Create the following files now (they'll be filled in subsequent tasks):

```python
# collector/api/routes/pages.py
from fastapi import APIRouter
router = APIRouter()
```

```python
# collector/api/routes/tasks.py
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 3: Commit**

```bash
git add collector/api/main.py collector/api/routes/pages.py collector/api/routes/tasks.py
git commit -m "feat: FastAPI app with lifespan DB pool management"
```

---

### Task 2: Search route (TDD)

**Files:**
- Create: `collector/api/routes/search.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

```python
"""API route tests — all routes tested via FastAPI's AsyncClient."""
import json
import pytest
import asyncpg
from httpx import AsyncClient, ASGITransport
from collector.api.main import app
from collector.db import _pool as _db_pool
import collector.db as db_module


@pytest.fixture
async def test_app(migrated_db: str, monkeypatch):
    """
    Override the shared DB pool to use the test database.
    The monkeypatch resets the global pool between tests.
    """
    import asyncpg as apg
    pool = await apg.create_pool(dsn=migrated_db, min_size=1, max_size=3)
    monkeypatch.setattr(db_module, "_pool", pool)
    yield app
    await pool.close()
    monkeypatch.setattr(db_module, "_pool", None)


@pytest.fixture
async def client(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def db(migrated_db: str):
    conn = await asyncpg.connect(dsn=migrated_db)
    tr = conn.transaction()
    await tr.start()
    yield conn
    await tr.rollback()
    await conn.close()


# --- /search ---

async def test_search_returns_empty_for_no_results(client: AsyncClient):
    resp = await client.get("/search?q=xyzzyabcdef123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["results"] == []


async def test_search_finds_indexed_page(client: AsyncClient, db: asyncpg.Connection):
    await db.execute(
        """
        INSERT INTO pages (url, domain, title, raw_text, old_web_score, detected_signals)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        "http://fishluv99.example.com/tank.html",
        "fishluv99.example.com",
        "My Tropical Tank",
        "Oscar fish are the best cichlids I have ever kept.",
        8,
        json.dumps({"no_framework": 2, "has_font_tag": 1}),
    )
    resp = await client.get("/search?q=oscar+cichlid")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    result = data["results"][0]
    assert "fishluv99" in result["url"]
    assert result["old_web_score"] == 8
    assert "signals" in result
    assert "snippet" in result


async def test_search_pagination(client: AsyncClient, db: asyncpg.Connection):
    for i in range(5):
        await db.execute(
            """
            INSERT INTO pages (url, domain, title, raw_text, old_web_score, detected_signals)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            f"http://example.com/page{i}.html",
            "example.com",
            f"Aquarium Page {i}",
            f"I love keeping tropical fish in my aquarium number {i}.",
            5,
            json.dumps({}),
        )
    resp = await client.get("/search?q=aquarium&limit=2&page=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) <= 2


async def test_search_requires_query(client: AsyncClient):
    resp = await client.get("/search")
    assert resp.status_code == 422  # missing required param
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_api.py::test_search_returns_empty_for_no_results -v
```

Expected: Route 404 or ImportError.

- [ ] **Step 3: Implement collector/api/routes/search.py**

```python
"""
GET /search — full-text search using Postgres ts_rank_cd.
Results are ranked by BM25-equivalent relevance (ts_rank_cd).
Dead pages are excluded. Results include signal breakdown and a snippet.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from collector.db import get_pool
import asyncpg

router = APIRouter()


class SearchResult(BaseModel):
    url: str
    title: str | None
    snippet: str
    old_web_score: int
    signals: dict
    crawled_at: str


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    limit: int
    results: list[SearchResult]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
) -> SearchResponse:
    pool = await get_pool()
    import json

    async with pool.acquire() as conn:
        # ts_headline generates a snippet with search terms highlighted (plain text)
        rows = await conn.fetch(
            """
            SELECT
                url,
                title,
                ts_headline(
                    'english',
                    raw_text,
                    to_tsquery('english', $1),
                    'MaxWords=25, MinWords=10, StartSel=, StopSel='
                ) AS snippet,
                old_web_score,
                detected_signals,
                crawled_at,
                ts_rank_cd(search_vector, to_tsquery('english', $1)) AS rank
            FROM pages
            WHERE search_vector @@ to_tsquery('english', $1)
              AND status = 'active'
            ORDER BY rank DESC
            LIMIT $2 OFFSET $3
            """,
            _to_tsquery(q), limit, page * limit,
        )

        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM pages
            WHERE search_vector @@ to_tsquery('english', $1)
              AND status = 'active'
            """,
            _to_tsquery(q),
        )

    results = [
        SearchResult(
            url=row["url"],
            title=row["title"],
            snippet=row["snippet"] or "",
            old_web_score=row["old_web_score"],
            signals=json.loads(row["detected_signals"]) if row["detected_signals"] else {},
            crawled_at=row["crawled_at"].isoformat(),
        )
        for row in rows
    ]

    return SearchResponse(
        query=q,
        total=total or 0,
        page=page,
        limit=limit,
        results=results,
    )


def _to_tsquery(q: str) -> str:
    """
    Convert a plain search query to a tsquery string.
    Joins words with & (AND). Strips non-alphanumeric characters.
    Example: "tropical fish tanks" → "tropical & fish & tanks"
    """
    import re
    words = re.findall(r'\w+', q)
    if not words:
        return "unknown"
    return " & ".join(words)
```

- [ ] **Step 4: Run search tests — expect PASS**

```bash
pytest tests/test_api.py -k "search" -v
```

Expected: All search tests pass.

- [ ] **Step 5: Commit**

```bash
git add collector/api/routes/search.py tests/test_api.py
git commit -m "feat: search route with ts_rank_cd ranking and ts_headline snippets"
```

---

### Task 3: Seeds + crawl control routes

**Files:**
- Create: `collector/api/routes/seeds.py`
- Create: `collector/api/routes/crawl.py`

- [ ] **Step 1: Add failing tests to tests/test_api.py**

Append to `tests/test_api.py`:

```python
# --- /seeds ---

async def test_add_seed(client: AsyncClient, db: asyncpg.Connection):
    resp = await client.post("/seeds", json={"url": "http://tilde.town", "label": "Tilde Town"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "http://tilde.town"


async def test_list_seeds(client: AsyncClient, db: asyncpg.Connection):
    await db.execute(
        "INSERT INTO seeds (url, label) VALUES ($1, $2)",
        "http://neocities.org", "Neocities"
    )
    resp = await client.get("/seeds")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_bulk_seed_import(client: AsyncClient, tmp_path):
    seeds_file = tmp_path / "seeds.txt"
    seeds_file.write_text(
        "# Comment line\nhttp://example1.com\nhttp://example2.com\n"
    )
    resp = await client.post(
        "/seeds/bulk",
        json={"file_path": str(seeds_file)},
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 2


# --- /crawl ---

async def test_crawl_status(client: AsyncClient):
    resp = await client.get("/crawl/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "pending" in data
    assert "done" in data
```

- [ ] **Step 2: Implement collector/api/routes/seeds.py**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from collector.db import get_pool
from collector.crawler.queue import enqueue_seed, enqueue_bulk_from_file

router = APIRouter()


class SeedIn(BaseModel):
    url: str
    label: str | None = None


class BulkSeedIn(BaseModel):
    file_path: str


@router.post("/seeds", status_code=201)
async def add_seed(seed: SeedIn) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await enqueue_seed(conn, seed.url, seed.label)
    return {"url": seed.url, "label": seed.label, "status": "queued"}


@router.get("/seeds")
async def list_seeds() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, url, label, source, added_at FROM seeds ORDER BY added_at DESC"
        )
    return [dict(r) for r in rows]


@router.post("/seeds/bulk")
async def bulk_import(body: BulkSeedIn) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        added = await enqueue_bulk_from_file(conn, body.file_path)
    return {"added": added, "file": body.file_path}
```

- [ ] **Step 3: Implement collector/api/routes/crawl.py**

```python
from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks
from collector.db import get_pool
from collector.crawler.queue import queue_depth

router = APIRouter()

_crawl_running = False


@router.post("/crawl/start", status_code=202)
async def start_crawl(background_tasks: BackgroundTasks) -> dict:
    global _crawl_running
    if _crawl_running:
        return {"status": "already_running"}
    background_tasks.add_task(_run_crawl)
    return {"status": "started"}


async def _run_crawl() -> None:
    global _crawl_running
    _crawl_running = True
    try:
        from collector.crawler.worker import run_crawler
        pool = await get_pool()
        await run_crawler(pool)
    finally:
        _crawl_running = False


@router.get("/crawl/status")
async def crawl_status() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        depth = await queue_depth(conn)
    return {
        "running": _crawl_running,
        **depth,
    }
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_api.py -k "seed or crawl" -v
```

- [ ] **Step 5: Commit**

```bash
git add collector/api/routes/seeds.py collector/api/routes/crawl.py
git commit -m "feat: seeds and crawl control routes"
```

---

### Task 4: Pages + stats + quarantine + threats routes

**Files:**
- Modify: `collector/api/routes/pages.py`
- Create: `collector/api/routes/quarantine.py`
- Create: `collector/api/routes/threats.py`

- [ ] **Step 1: Implement collector/api/routes/pages.py**

```python
from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from collector.db import get_pool

router = APIRouter()


@router.get("/pages/{page_id}")
async def get_page(page_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE id = $1", page_id)
    if not row:
        raise HTTPException(status_code=404, detail="Page not found")
    data = dict(row)
    data["detected_signals"] = json.loads(data["detected_signals"]) if data["detected_signals"] else {}
    data["search_vector"] = str(data["search_vector"])  # not serialisable as-is
    return data


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(page_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM pages WHERE id = $1", page_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Page not found")


@router.get("/stats")
async def stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_pages = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE status = 'active'")
        total_domains = await conn.fetchval("SELECT COUNT(DISTINCT domain) FROM pages WHERE status = 'active'")
        avg_score = await conn.fetchval("SELECT AVG(old_web_score) FROM pages WHERE status = 'active'")
        dead_pages = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE status = 'dead'")
        quarantine_count = await conn.fetchval("SELECT COUNT(*) FROM quarantine WHERE reviewed = FALSE")
        threat_count = await conn.fetchval("SELECT COUNT(*) FROM threat_log")
    return {
        "total_pages": total_pages,
        "total_domains": total_domains,
        "avg_old_web_score": round(float(avg_score or 0), 2),
        "dead_pages": dead_pages,
        "quarantine_unreviewed": quarantine_count,
        "threat_log_total": threat_count,
    }
```

- [ ] **Step 2: Implement collector/api/routes/quarantine.py**

```python
from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from collector.db import get_pool
from collector.signals.filter import score_page

router = APIRouter()


@router.get("/quarantine")
async def list_quarantine(
    reason: str | None = None,
    reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = "SELECT id, url, error_reason, partial_score, http_status, fetched_at, reviewed FROM quarantine"
        params: list = []
        conditions = [f"reviewed = ${len(params)+1}"]
        params.append(reviewed)
        if reason:
            conditions.append(f"error_reason = ${len(params)+1}")
            params.append(reason)
        query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY fetched_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
        params += [limit, offset]
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/quarantine/{item_id}")
async def get_quarantine_item(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    data = dict(row)
    data["partial_signals"] = json.loads(data["partial_signals"]) if data["partial_signals"] else {}
    return data


@router.post("/quarantine/{item_id}/approve")
async def approve_quarantine(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if not row["raw_html"]:
            raise HTTPException(status_code=422, detail="No raw HTML stored — cannot approve")

        from collector.indexer import db as indexer_db
        from collector.signals.filter import FilterResult
        import json as _json

        result = FilterResult(
            passed=True,
            score=row["partial_score"],
            signals=_json.loads(row["partial_signals"]) if row["partial_signals"] else {},
        )
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(row["raw_html"], "lxml")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        raw_text = soup.get_text(separator=" ", strip=True)
        from urllib.parse import urlparse
        domain = urlparse(row["url"]).netloc

        await indexer_db.upsert_page(
            conn=conn,
            url=row["url"],
            domain=domain,
            title=title,
            raw_text=raw_text,
            result=result,
            page_size_bytes=len(row["raw_html"].encode()),
        )
        await conn.execute("UPDATE quarantine SET reviewed = TRUE WHERE id = $1", item_id)

    return {"status": "approved", "url": row["url"]}


@router.post("/quarantine/{item_id}/reject")
async def reject_quarantine(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM quarantine WHERE id = $1", item_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "rejected"}


@router.post("/quarantine/{item_id}/rescore")
async def rescore_quarantine(item_id: int) -> dict:
    """Re-run the signal filter with current weights. Useful after tuning thresholds."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if not row["raw_html"]:
            raise HTTPException(status_code=422, detail="No raw HTML stored")

        from urllib.parse import urlparse
        domain = urlparse(row["url"]).netloc
        result = score_page(row["raw_html"], domain)

        await conn.execute(
            """
            UPDATE quarantine
            SET partial_signals = $1, partial_score = $2, error_reason = $3, reviewed = FALSE
            WHERE id = $4
            """,
            json.dumps(result.signals), result.score,
            result.quarantine_reason or ("passed" if result.passed else "below_threshold"),
            item_id,
        )

    return {
        "score": result.score,
        "passed": result.passed,
        "quarantine_reason": result.quarantine_reason,
        "signals": result.signals,
    }
```

- [ ] **Step 3: Implement collector/api/routes/threats.py**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from collector.db import get_pool

router = APIRouter()


@router.get("/threats")
async def list_threats(
    threat_type: str | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        conditions, params = [], []
        if threat_type:
            conditions.append(f"threat_type = ${len(params)+1}")
            params.append(threat_type)
        if domain:
            conditions.append(f"domain = ${len(params)+1}")
            params.append(domain)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        rows = await conn.fetch(
            f"SELECT * FROM threat_log {where} ORDER BY detected_at DESC "
            f"LIMIT ${len(params)-1} OFFSET ${len(params)}",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/threats/{threat_id}/block-domain")
async def block_domain(threat_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM threat_log WHERE id = $1", threat_id)
        if not row:
            raise HTTPException(status_code=404, detail="Threat not found")
        await conn.execute(
            """
            INSERT INTO blocked_domains (domain, reason, source)
            VALUES ($1, $2, 'manual')
            ON CONFLICT (domain) DO NOTHING
            """,
            row["domain"],
            f"Promoted from threat_log #{threat_id}: {row['threat_type']}",
        )
        await conn.execute(
            "UPDATE threat_log SET domain_blocked = TRUE WHERE domain = $1",
            row["domain"],
        )
    return {"status": "blocked", "domain": row["domain"]}


@router.get("/blocked-domains")
async def list_blocked_domains() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM blocked_domains ORDER BY blocked_at DESC"
        )
    return [dict(r) for r in rows]


@router.delete("/blocked-domains/{domain}", status_code=204)
async def unblock_domain(domain: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM blocked_domains WHERE domain = $1", domain
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Domain not found in blocklist")
```

- [ ] **Step 4: Implement collector/api/routes/tasks.py**

```python
from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()


class CDXImportRequest(BaseModel):
    from_year: int = 1996
    to_year: int = 2008
    limit: int = 10_000


@router.post("/tasks/import-cdx", status_code=202)
async def trigger_cdx_import(
    body: CDXImportRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    background_tasks.add_task(_run_cdx_import, body.from_year, body.to_year, body.limit)
    return {"status": "started", "from_year": body.from_year, "to_year": body.to_year}


async def _run_cdx_import(from_year: int, to_year: int, limit: int) -> None:
    from collector.crawler.cdx import fetch_cdx_urls
    from collector.crawler.queue import enqueue
    from collector.db import get_pool

    urls = await fetch_cdx_urls(from_year=from_year, to_year=to_year, limit=limit)
    pool = await get_pool()
    async with pool.acquire() as conn:
        for url, _ in urls:
            await enqueue(conn, url, source_url="cdx", depth=0)
    print(f"[cdx] Enqueued {len(urls)} URLs from {from_year}-{to_year}")
```

- [ ] **Step 5: Run all API tests**

```bash
pytest tests/test_api.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add collector/api/routes/
git commit -m "feat: pages, quarantine, threats, tasks routes"
```

---

### Task 5: Celery tasks

**Files:**
- Create: `collector/tasks/celery_app.py`
- Create: `tests/test_tasks.py`

- [ ] **Step 1: Write failing tests in tests/test_tasks.py**

```python
"""
Celery task tests — run tasks synchronously (CELERY_TASK_ALWAYS_EAGER)
to avoid needing a running broker.
"""
import pytest
from unittest.mock import AsyncMock, patch


def test_recrawl_stale_pages_task_exists():
    from collector.tasks.celery_app import recrawl_stale_pages
    assert callable(recrawl_stale_pages)


def test_check_dead_links_task_exists():
    from collector.tasks.celery_app import check_dead_links
    assert callable(check_dead_links)


def test_import_cdx_batch_task_exists():
    from collector.tasks.celery_app import import_cdx_batch
    assert callable(import_cdx_batch)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_tasks.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement collector/tasks/celery_app.py**

```python
"""
Celery application and scheduled tasks.

Tasks:
  recrawl_stale_pages  — re-queue pages due for recrawling (runs every 6 hours)
  check_dead_links     — HEAD-check pages, mark dead if 404/timeout (runs weekly)
  import_cdx_batch     — pull URLs from Internet Archive CDX API (run manually or on schedule)

The beat schedule runs inside the celery container (celery -A collector.tasks.celery_app worker -B).
"""
from __future__ import annotations
import asyncio
import asyncpg
import httpx
from celery import Celery
from celery.schedules import crontab
from collector.config import settings
from collector.crawler.robots import USER_AGENT

app = Celery("collector", broker=settings.redis_url, backend=settings.redis_url)

app.conf.beat_schedule = {
    "recrawl-stale-every-6h": {
        "task": "collector.tasks.celery_app.recrawl_stale_pages",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "check-dead-links-weekly": {
        "task": "collector.tasks.celery_app.check_dead_links",
        "schedule": crontab(minute=0, hour=3, day_of_week=0),  # Sunday 3am
    },
}
app.conf.timezone = "UTC"


def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


@app.task(name="collector.tasks.celery_app.recrawl_stale_pages")
def recrawl_stale_pages() -> dict:
    """Find pages where next_crawl_at < NOW() and re-queue them."""
    async def _inner():
        conn = await asyncpg.connect(dsn=settings.database_url)
        try:
            rows = await conn.fetch(
                """
                SELECT url FROM pages
                WHERE status = 'active' AND next_crawl_at < NOW()
                LIMIT 1000
                """
            )
            from collector.crawler.queue import enqueue
            count = 0
            for row in rows:
                added = await enqueue(conn, row["url"], source_url="recrawl", depth=0)
                if added:
                    count += 1
            return {"requeued": count}
        finally:
            await conn.close()

    return _run(_inner())


@app.task(name="collector.tasks.celery_app.check_dead_links")
def check_dead_links() -> dict:
    """HEAD-check all active pages; mark as dead if they 404 or timeout."""
    async def _inner():
        conn = await asyncpg.connect(dsn=settings.database_url)
        dead = 0
        try:
            rows = await conn.fetch(
                "SELECT id, url FROM pages WHERE status = 'active' LIMIT 5000"
            )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=10.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                for row in rows:
                    try:
                        resp = await client.head(row["url"])
                        if resp.status_code == 404:
                            await conn.execute(
                                "UPDATE pages SET status = 'dead', last_seen_at = NOW() WHERE id = $1",
                                row["id"],
                            )
                            dead += 1
                    except (httpx.RequestError, httpx.TimeoutException):
                        # Timeout doesn't mean dead — skip, will retry next run
                        pass
            return {"checked": len(rows), "marked_dead": dead}
        finally:
            await conn.close()

    return _run(_inner())


@app.task(name="collector.tasks.celery_app.import_cdx_batch")
def import_cdx_batch(from_year: int = 1996, to_year: int = 2008, limit: int = 10_000) -> dict:
    """Pull URLs from Internet Archive CDX API and enqueue them."""
    async def _inner():
        from collector.crawler.cdx import fetch_cdx_urls
        from collector.crawler.queue import enqueue

        urls = await fetch_cdx_urls(from_year=from_year, to_year=to_year, limit=limit)
        conn = await asyncpg.connect(dsn=settings.database_url)
        added = 0
        try:
            for url, _ in urls:
                was_new = await enqueue(conn, url, source_url="cdx", depth=0)
                if was_new:
                    added += 1
            return {"fetched": len(urls), "newly_enqueued": added}
        finally:
            await conn.close()

    return _run(_inner())
```

- [ ] **Step 4: Run task tests — expect PASS**

```bash
pytest tests/test_tasks.py -v
```

- [ ] **Step 5: Commit**

```bash
git add collector/tasks/celery_app.py tests/test_tasks.py
git commit -m "feat: Celery tasks — recrawl, dead link check, CDX import"
```

---

### Task 6: Full integration smoke test

- [ ] **Step 1: Build and start all services**

```bash
docker compose up --build -d
docker compose ps
```

Expected: All 5 services show `healthy` or `running`.

- [ ] **Step 2: Run migrations**

```bash
docker compose exec api python -m migrations.run_migrations
```

Expected: `Running 001_initial_schema.sql... ✓ Done`

- [ ] **Step 3: Seed from seeds.txt**

```bash
curl -s -X POST http://localhost:8000/seeds/bulk \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/app/seeds.txt"}' | python -m json.tool
```

Expected: `{"added": N, "file": "/app/seeds.txt"}` where N > 0.

- [ ] **Step 4: Check queue**

```bash
curl -s http://localhost:8000/crawl/status | python -m json.tool
```

Expected: `{"running": false, "pending": N, ...}`

- [ ] **Step 5: Trigger a crawl**

```bash
curl -s -X POST http://localhost:8000/crawl/start | python -m json.tool
```

Expected: `{"status": "started"}`

- [ ] **Step 6: Wait 30 seconds, check stats**

```bash
sleep 30 && curl -s http://localhost:8000/stats | python -m json.tool
```

Expected: `total_pages` > 0.

- [ ] **Step 7: Search for something**

```bash
curl -s "http://localhost:8000/search?q=personal+site" | python -m json.tool
```

Expected: Results with `old_web_score`, `signals` breakdown, and `snippet` visible.

- [ ] **Step 8: Check quarantine**

```bash
curl -s "http://localhost:8000/quarantine?reviewed=false" | python -m json.tool
```

Expected: Any borderline pages that almost made it in — review and approve/reject as desired.

- [ ] **Step 9: Run full test suite**

```bash
docker compose exec api pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 10: Commit**

```bash
git add .
git commit -m "feat: full stack verified — search, crawl, quarantine, threats all working"
```

---

## Done

The Collector is now:
- ✅ Fully containerised (5 Docker services)
- ✅ Crawling from seeds.txt + CDX API + link-following
- ✅ Signal filtering with explainable scores
- ✅ Full-text search with `ts_rank_cd` ranking
- ✅ Quarantine queue for human review of ambiguous pages
- ✅ Threat logging + domain blocklist
- ✅ Celery re-crawl scheduler
- ✅ API-only (Phase 1 complete)

**Phase 2 next steps:** minimal HTML search UI, multi-user seed submission, `POST /quarantine/{id}/approve` UI, signal weight tuning interface.
