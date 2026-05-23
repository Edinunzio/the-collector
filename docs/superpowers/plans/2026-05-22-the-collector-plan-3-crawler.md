# The Collector — Plan 3: Crawler

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the async crawler — security pre-checks, robots.txt handling, crawl queue, CDX API client, and the main worker loop that fetches pages and feeds them through the signal filter into the index.

**Architecture:** All security checks run before any HTTP request. The crawler is queue-driven from Postgres (`crawl_queue` table). Workers are async coroutines running in a pool. The CDX client is a separate async function that bulk-inserts historical URLs into the queue. Content extraction strips nav/header/footer before indexing.

**Tech Stack:** httpx, asyncio, BeautifulSoup4 + lxml, asyncpg, chardet

**Depends on:** Plan 1 (DB pool, schema, config), Plan 2 (signal filter)

---

## File Map

| File | Role |
|---|---|
| `collector/crawler/security.py` | Pre-request URL validation, IP checks, SSRF prevention |
| `collector/crawler/robots.py` | Cached robots.txt parser per domain |
| `collector/crawler/queue.py` | Postgres-backed crawl queue operations |
| `collector/crawler/cdx.py` | Internet Archive CDX API client |
| `collector/crawler/worker.py` | Main async crawl loop — fetch, filter, index |
| `collector/indexer/db.py` | Write page to `pages` table, write to quarantine/threat_log |
| `tests/test_security.py` | Unit tests for security checks |
| `tests/test_crawler.py` | Integration tests using pytest-httpserver |
| `tests/test_cdx.py` | CDX client tests with mocked HTTP |

---

### Task 1: Security checks (TDD)

**Files:**
- Create: `tests/test_security.py`
- Create: `collector/crawler/security.py`

- [ ] **Step 1: Write failing tests in tests/test_security.py**

```python
"""
Unit tests for pre-request security validation.
No network calls — all checks are on URL strings and resolved IPs.
"""
import pytest
from collector.crawler.security import (
    SecurityViolation,
    check_url,
    check_content_length,
    normalize_url,
    is_high_entropy_url,
)


# --- check_url: scheme validation ---

def test_http_url_passes():
    check_url("http://example.com/page.html")  # Should not raise


def test_https_url_passes():
    check_url("https://example.com/page.html")  # Should not raise


def test_file_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("file:///etc/passwd")
    assert exc.value.threat_type == "redirect_violation"


def test_gopher_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("gopher://example.com/")
    assert exc.value.threat_type == "redirect_violation"


def test_ftp_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("ftp://example.com/file.txt")
    assert exc.value.threat_type == "redirect_violation"


# --- check_url: Docker hostname SSRF ---

def test_docker_db_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://db:5432/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_docker_redis_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://redis:6379/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_docker_api_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://api:8000/admin")
    assert exc.value.threat_type == "ssrf_attempt"


# --- check_url: private IP SSRF ---

def test_loopback_ip_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://127.0.0.1/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_private_class_a_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://10.0.0.1/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_private_class_c_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://192.168.1.100/")
    assert exc.value.threat_type == "ssrf_attempt"


# --- check_content_length ---

def test_content_length_within_limit_passes():
    check_content_length(1024, 5 * 1024 * 1024)  # Should not raise


def test_content_length_exceeds_limit_raises():
    with pytest.raises(SecurityViolation) as exc:
        check_content_length(10 * 1024 * 1024, 5 * 1024 * 1024)
    assert exc.value.threat_type == "oversized_response"


def test_none_content_length_passes():
    check_content_length(None, 5 * 1024 * 1024)  # Should not raise


# --- normalize_url ---

def test_normalize_strips_session_param():
    url = "http://example.com/page.html?sid=abc123&color=blue"
    result = normalize_url(url)
    assert "sid" not in result
    assert "color=blue" in result


def test_normalize_strips_utm_params():
    url = "http://example.com/page.html?utm_source=google&page=2"
    result = normalize_url(url)
    assert "utm_source" not in result
    assert "page=2" in result


def test_normalize_strips_phpsessid():
    url = "http://example.com/page.php?PHPSESSID=abc123def456"
    result = normalize_url(url)
    assert "PHPSESSID" not in result


def test_normalize_preserves_clean_url():
    url = "http://example.com/fish/tanks.html"
    assert normalize_url(url) == url


# --- is_high_entropy_url ---

def test_high_entropy_uuid_detected():
    url = "http://example.com/page?token=a3f9b12c4e5d6f7a8b9c0d1e2f3a4b5c"
    assert is_high_entropy_url(url) is True


def test_clean_url_not_high_entropy():
    assert is_high_entropy_url("http://example.com/fish.html?page=2") is False


def test_no_query_string_not_high_entropy():
    assert is_high_entropy_url("http://example.com/fish.html") is False
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_security.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'SecurityViolation'`

- [ ] **Step 3: Implement collector/crawler/security.py**

```python
"""
Pre-request security validation.
All checks run BEFORE any HTTP request is made.
Any violation raises SecurityViolation, which the worker catches and logs to threat_log.
"""
from __future__ import annotations
import ipaddress
import re
import socket
from urllib.parse import urlparse, urlencode, parse_qsl

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_DOCKER_HOSTNAMES = frozenset({"db", "redis", "api", "crawler", "celery"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})

_SESSION_PARAM = re.compile(
    r'^(session|sid|phpsessid|jsessionid|token|csrf|utm_|fbclid|gclid)',
    re.IGNORECASE,
)
_HIGH_ENTROPY_VALUE = re.compile(r'^[a-f0-9\-]{20,}$', re.IGNORECASE)


class SecurityViolation(Exception):
    def __init__(self, threat_type: str, detail: str) -> None:
        self.threat_type = threat_type
        self.detail = detail
        super().__init__(f"[{threat_type}] {detail}")


def check_url(url: str) -> None:
    """
    Validate URL before making any request.
    Raises SecurityViolation on any check failure.
    Order: scheme → Docker hostname → IP range.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SecurityViolation(
            "redirect_violation",
            f"Disallowed scheme '{parsed.scheme}' in URL: {url}",
        )

    hostname = parsed.hostname
    if not hostname:
        raise SecurityViolation("redirect_violation", f"No hostname in URL: {url}")

    if hostname in _DOCKER_HOSTNAMES:
        raise SecurityViolation(
            "ssrf_attempt",
            f"Docker service hostname '{hostname}' in URL: {url}",
        )

    # Resolve hostname → IP and check against private ranges
    try:
        resolved = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved)
        for network in _PRIVATE_NETWORKS:
            if ip in network:
                raise SecurityViolation(
                    "ssrf_attempt",
                    f"Resolved IP {ip} for '{hostname}' is in private range {network}",
                )
    except (socket.gaierror, ValueError):
        pass  # Unresolvable hostname — let httpx handle the error naturally


def check_content_length(content_length: int | None, limit: int) -> None:
    """Raise SecurityViolation if Content-Length header exceeds limit."""
    if content_length is not None and content_length > limit:
        raise SecurityViolation(
            "oversized_response",
            f"Content-Length {content_length:,} exceeds limit {limit:,}",
        )


def normalize_url(url: str) -> str:
    """
    Remove session/tracking query parameters to prevent spider traps
    and avoid indexing the same page under many different URLs.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return url

    kept = [
        (k, v) for k, v in parse_qsl(parsed.query)
        if not _SESSION_PARAM.match(k)
    ]
    clean = parsed._replace(query=urlencode(kept))
    return clean.geturl()


def is_high_entropy_url(url: str) -> bool:
    """
    Detect potential spider trap: query parameter with a long, random-looking value
    (UUID, session token, etc.). Returns True if the URL looks like a trap.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return False
    for _, value in parse_qsl(parsed.query):
        if len(value) > 20 and _HIGH_ENTROPY_VALUE.match(value):
            return True
    return False
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_security.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add collector/crawler/security.py tests/test_security.py
git commit -m "feat: security pre-request checks — SSRF, scheme, content-length, URL normalization"
```

---

### Task 2: robots.txt handler

**Files:**
- Create: `collector/crawler/robots.py`

- [ ] **Step 1: Implement collector/crawler/robots.py**

```python
"""
Per-domain robots.txt cache.
Fetches and parses robots.txt once per domain per crawler run,
caches in-memory. Respects Disallow rules for our User-Agent.
"""
from __future__ import annotations
import asyncio
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx

USER_AGENT = "TheCollector/0.1 (+https://github.com/you/the-collector)"

_cache: dict[str, RobotFileParser | None] = {}
_cache_lock = asyncio.Lock()


async def is_allowed(url: str, client: httpx.AsyncClient) -> bool:
    """
    Return True if the given URL is allowed to be crawled.
    Fetches and caches robots.txt for the domain on first call.
    Returns True if robots.txt is missing or unreadable (opt-in not opt-out).
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    async with _cache_lock:
        if domain not in _cache:
            _cache[domain] = await _fetch_robots(domain, client)

    rp = _cache[domain]
    if rp is None:
        return True  # No robots.txt → allowed

    return rp.can_fetch(USER_AGENT, url)


async def _fetch_robots(base_url: str, client: httpx.AsyncClient) -> RobotFileParser | None:
    """Fetch and parse robots.txt. Returns None if not found or fetch fails."""
    robots_url = f"{base_url}/robots.txt"
    try:
        resp = await client.get(robots_url, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


def clear_cache() -> None:
    """Clear the robots cache. Call between crawl runs if needed."""
    _cache.clear()
```

- [ ] **Step 2: Commit**

```bash
git add collector/crawler/robots.py
git commit -m "feat: robots.txt cache with async fetch"
```

---

### Task 3: Crawl queue

**Files:**
- Create: `collector/crawler/queue.py`

- [ ] **Step 1: Implement collector/crawler/queue.py**

```python
"""
Postgres-backed crawl queue.
Provides atomic claim, enqueue, and complete operations.
All operations use the shared asyncpg pool.
"""
from __future__ import annotations
import asyncpg
from datetime import datetime, timedelta, timezone
from collector.crawler.security import normalize_url, is_high_entropy_url


async def enqueue(
    conn: asyncpg.Connection,
    url: str,
    source_url: str | None = None,
    depth: int = 0,
) -> bool:
    """
    Add a URL to the crawl queue. Returns True if newly enqueued, False if already present.
    Normalizes the URL and silently drops high-entropy (spider trap) URLs.
    """
    url = normalize_url(url)
    if is_high_entropy_url(url):
        return False

    result = await conn.execute(
        """
        INSERT INTO crawl_queue (url, source_url, depth)
        VALUES ($1, $2, $3)
        ON CONFLICT (url) DO NOTHING
        """,
        url, source_url, depth,
    )
    return result == "INSERT 0 1"


async def claim_next(
    conn: asyncpg.Connection,
    limit: int = 1,
) -> list[asyncpg.Record]:
    """
    Atomically claim up to `limit` pending URLs for processing.
    Marks them as `in_progress`. Returns claimed records.
    Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent workers.
    """
    return await conn.fetch(
        """
        UPDATE crawl_queue
        SET status = 'in_progress'
        WHERE id IN (
            SELECT id FROM crawl_queue
            WHERE status = 'pending'
              AND next_attempt_at <= NOW()
            ORDER BY queued_at
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, url, source_url, depth, attempts
        """,
        limit,
    )


async def mark_done(conn: asyncpg.Connection, queue_id: int) -> None:
    """Mark a queue item as successfully processed."""
    await conn.execute(
        "UPDATE crawl_queue SET status = 'done' WHERE id = $1",
        queue_id,
    )


async def mark_failed(conn: asyncpg.Connection, queue_id: int, attempts: int) -> None:
    """
    Mark a queue item as failed. After 3 attempts, status becomes 'failed'.
    Before that, schedule a retry with exponential backoff.
    """
    if attempts >= 3:
        await conn.execute(
            "UPDATE crawl_queue SET status = 'failed' WHERE id = $1",
            queue_id,
        )
    else:
        backoff_seconds = 60 * (2 ** attempts)  # 60s, 120s, 240s
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        await conn.execute(
            """
            UPDATE crawl_queue
            SET status = 'pending', attempts = attempts + 1, next_attempt_at = $2
            WHERE id = $1
            """,
            queue_id, next_attempt,
        )


async def queue_depth(conn: asyncpg.Connection) -> dict[str, int]:
    """Return counts by status for monitoring."""
    rows = await conn.fetch(
        "SELECT status, COUNT(*) AS n FROM crawl_queue GROUP BY status"
    )
    return {row["status"]: row["n"] for row in rows}


async def enqueue_seed(conn: asyncpg.Connection, url: str, label: str | None = None) -> None:
    """Add a URL to both the seeds table and the crawl queue."""
    await conn.execute(
        """
        INSERT INTO seeds (url, label, source)
        VALUES ($1, $2, 'manual')
        ON CONFLICT (url) DO NOTHING
        """,
        url, label,
    )
    await enqueue(conn, url, source_url=None, depth=0)


async def enqueue_bulk_from_file(conn: asyncpg.Connection, path: str) -> int:
    """
    Read seeds.txt (one URL per line, # for comments) and enqueue all.
    Returns count of newly added URLs.
    """
    from pathlib import Path
    added = 0
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        was_new = await enqueue(conn, line, source_url=None, depth=0)
        if was_new:
            await conn.execute(
                """
                INSERT INTO seeds (url, source)
                VALUES ($1, 'file')
                ON CONFLICT (url) DO NOTHING
                """,
                line,
            )
            added += 1
    return added
```

- [ ] **Step 2: Commit**

```bash
git add collector/crawler/queue.py
git commit -m "feat: Postgres crawl queue with atomic claim and exponential backoff"
```

---

### Task 4: CDX API client

**Files:**
- Create: `collector/crawler/cdx.py`
- Create: `tests/test_cdx.py`

- [ ] **Step 1: Write failing test in tests/test_cdx.py**

```python
"""Tests for the Internet Archive CDX API client."""
import pytest
import respx
import httpx
from collector.crawler.cdx import fetch_cdx_urls, CDX_API_URL


@respx.mock
async def test_fetch_cdx_urls_returns_live_urls():
    """CDX client should parse the API response and return (url, timestamp) tuples."""
    mock_response = (
        '["urlkey","timestamp","original","statuscode"]\n'
        '["com,example)/fish.html","19990315120000","http://example.com/fish.html","200"]\n'
        '["com,example)/tanks.html","20010822093012","http://example.com/tanks.html","200"]\n'
        '["com,example)/old.html","20030110080000","http://example.com/old.html","404"]\n'
    )
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(200, text=mock_response))

    results = await fetch_cdx_urls(from_year=1996, to_year=2005, limit=10)
    # Should only include status 200 URLs
    assert len(results) == 2
    urls = [r[0] for r in results]
    assert "http://example.com/fish.html" in urls
    assert "http://example.com/tanks.html" in urls
    # 404 should be excluded
    assert "http://example.com/old.html" not in urls


@respx.mock
async def test_fetch_cdx_urls_handles_empty_response():
    mock_response = '["urlkey","timestamp","original","statuscode"]\n'
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(200, text=mock_response))

    results = await fetch_cdx_urls(from_year=1996, to_year=2000, limit=10)
    assert results == []


@respx.mock
async def test_fetch_cdx_urls_handles_api_error():
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(500))

    results = await fetch_cdx_urls(from_year=1996, to_year=2000, limit=10)
    assert results == []
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
pytest tests/test_cdx.py -v
```

Expected: `ImportError: cannot import name 'fetch_cdx_urls'`

- [ ] **Step 3: Implement collector/crawler/cdx.py**

```python
"""
Internet Archive CDX API client.
Fetches historical URLs captured between two years that returned HTTP 200.
These are live old-web pages that no modern link graph connects to.

API docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""
from __future__ import annotations
import httpx

CDX_API_URL = "https://web.archive.org/cdx/search/cdx"


async def fetch_cdx_urls(
    from_year: int,
    to_year: int,
    limit: int = 10_000,
    match_type: str = "domain",
    filter_mime: str = "text/html",
) -> list[tuple[str, str]]:
    """
    Query the CDX API for URLs captured between from_year and to_year
    that returned HTTP 200 and are HTML pages.

    Returns a list of (url, timestamp) tuples. Empty list on any error.

    Rate limit: be polite — call this in batches with delays, not in a tight loop.
    """
    params = {
        "output": "json",
        "fl": "urlkey,timestamp,original,statuscode",
        "filter": "statuscode:200",
        "from": f"{from_year}0101",
        "to": f"{to_year}1231",
        "limit": str(limit),
        "matchType": match_type,
        "mimetype": filter_mime,
        "collapse": "urlkey",  # deduplicate same URL
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(CDX_API_URL, params=params)
            resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        print(f"[cdx] API error: {exc}")
        return []

    results: list[tuple[str, str]] = []
    lines = resp.text.strip().splitlines()

    # First line is the header row — skip it
    for line in lines[1:]:
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        try:
            import json
            parts = json.loads(line)
            # parts: [urlkey, timestamp, original_url, statuscode]
            if len(parts) >= 4 and parts[3] == "200":
                results.append((parts[2], parts[1]))
        except (ValueError, IndexError):
            continue

    return results
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_cdx.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add collector/crawler/cdx.py tests/test_cdx.py
git commit -m "feat: Internet Archive CDX API client"
```

---

### Task 5: Indexer DB layer

**Files:**
- Create: `collector/indexer/db.py`

- [ ] **Step 1: Implement collector/indexer/db.py**

```python
"""
Database write operations for the indexer.
Handles: inserting indexed pages, quarantine entries, threat log entries.
All functions accept an asyncpg Connection (not the pool) for transaction safety.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
import asyncpg
from collector.signals.filter import FilterResult


async def upsert_page(
    conn: asyncpg.Connection,
    url: str,
    domain: str,
    title: str | None,
    raw_text: str,
    result: FilterResult,
    page_size_bytes: int,
) -> None:
    """
    Insert or update a page in the index.
    The search_vector is generated automatically by Postgres.
    """
    await conn.execute(
        """
        INSERT INTO pages (
            url, domain, title, raw_text,
            old_web_score, page_size_bytes, detected_signals,
            crawled_at, last_seen_at,
            next_crawl_at, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW(), $8, 'active')
        ON CONFLICT (url) DO UPDATE SET
            title           = EXCLUDED.title,
            raw_text        = EXCLUDED.raw_text,
            old_web_score   = EXCLUDED.old_web_score,
            page_size_bytes = EXCLUDED.page_size_bytes,
            detected_signals = EXCLUDED.detected_signals,
            last_seen_at    = NOW(),
            next_crawl_at   = EXCLUDED.next_crawl_at,
            status          = 'active'
        """,
        url,
        domain,
        title,
        raw_text,
        result.score,
        page_size_bytes,
        json.dumps(result.signals),
        datetime.now(timezone.utc) + timedelta(days=30),
    )


async def upsert_quarantine(
    conn: asyncpg.Connection,
    url: str,
    raw_html: str | None,
    result: FilterResult,
    http_status: int | None = None,
    fetch_error: str | None = None,
) -> None:
    """Insert or update a quarantine entry."""
    await conn.execute(
        """
        INSERT INTO quarantine (
            url, raw_html, error_reason,
            partial_signals, partial_score,
            http_status, fetch_error
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (url) DO UPDATE SET
            raw_html       = EXCLUDED.raw_html,
            error_reason   = EXCLUDED.error_reason,
            partial_signals = EXCLUDED.partial_signals,
            partial_score  = EXCLUDED.partial_score,
            http_status    = EXCLUDED.http_status,
            fetch_error    = EXCLUDED.fetch_error,
            fetched_at     = NOW(),
            reviewed       = FALSE
        """,
        url,
        raw_html,
        result.quarantine_reason,
        json.dumps(result.signals),
        result.score,
        http_status,
        fetch_error,
    )


async def log_threat(
    conn: asyncpg.Connection,
    url: str,
    domain: str,
    threat_type: str,
    detail: str,
    http_status: int | None = None,
) -> None:
    """Log a security threat. Check if domain is in blocked_domains after logging."""
    await conn.execute(
        """
        INSERT INTO threat_log (url, domain, threat_type, detail, http_status)
        VALUES ($1, $2, $3, $4, $5)
        """,
        url, domain, threat_type, detail, http_status,
    )


async def is_domain_blocked(conn: asyncpg.Connection, domain: str) -> bool:
    """Return True if the domain is in the blocked_domains table."""
    row = await conn.fetchrow(
        "SELECT 1 FROM blocked_domains WHERE domain = $1",
        domain,
    )
    return row is not None


async def mark_page_dead(conn: asyncpg.Connection, url: str) -> None:
    """Mark a page as dead (404 / unreachable on re-crawl check)."""
    await conn.execute(
        "UPDATE pages SET status = 'dead', last_seen_at = NOW() WHERE url = $1",
        url,
    )
```

- [ ] **Step 2: Commit**

```bash
git add collector/indexer/db.py
git commit -m "feat: indexer DB layer — upsert pages, quarantine, threat log"
```

---

### Task 6: Crawler worker (integration test + implementation)

**Files:**
- Create: `tests/test_crawler.py`
- Create: `collector/crawler/worker.py`

- [ ] **Step 1: Write integration tests in tests/test_crawler.py**

```python
"""
Integration tests for the crawler worker.
Uses pytest-httpserver to serve real HTML over HTTP so we test the full
fetch → security → robots → signal → index pipeline without hitting the internet.
"""
import pytest
import asyncpg
from pytest_httpserver import HTTPServer
from collector.crawler.worker import crawl_url
from collector.db import get_pool, close_pool

GEOCITIES_HTML = """<HTML><HEAD><TITLE>My Fish Page</TITLE>
<meta name="date" content="1999-03-14"></HEAD>
<BODY><FONT SIZE="+2">Welcome!</FONT>
<MARQUEE>Oscar Fish Forever</MARQUEE>
<TABLE><TR><TD>I have kept cichlids since 1997. They are the best tropical fish.</TD></TR></TABLE>
</BODY></HTML>"""

REACT_HTML = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/main.a3f9b12c.min.css">
</head><body><div id="root"></div>
<script src="/bundle.c4d8e3f1.min.js"></script></body></html>"""


@pytest.fixture(scope="module")
async def pool(migrated_db):
    p = await get_pool.__wrapped__(migrated_db)  # Use test DB, not prod
    yield p
    await p.close()


@pytest.fixture(scope="module")
async def pool(migrated_db: str):
    import asyncpg as apg
    p = await apg.create_pool(dsn=migrated_db, min_size=1, max_size=3)
    yield p
    await p.close()


async def test_old_web_page_gets_indexed(httpserver: HTTPServer, pool: asyncpg.Pool):
    httpserver.expect_request("/fish.html").respond_with_data(
        GEOCITIES_HTML, content_type="text/html"
    )
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nAllow: /", content_type="text/plain"
    )
    url = httpserver.url_for("/fish.html")
    domain = f"localhost:{httpserver.port}"

    async with pool.acquire() as conn:
        await crawl_url(url=url, depth=0, conn=conn)
        row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is not None
    assert row["old_web_score"] >= 3
    assert "oscar" in row["raw_text"].lower() or "cichlid" in row["raw_text"].lower()


async def test_react_app_not_indexed(httpserver: HTTPServer, pool: asyncpg.Pool):
    httpserver.expect_request("/app.html").respond_with_data(
        REACT_HTML, content_type="text/html"
    )
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nAllow: /", content_type="text/plain"
    )
    url = httpserver.url_for("/app.html")

    async with pool.acquire() as conn:
        await crawl_url(url=url, depth=0, conn=conn)
        row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is None  # auto-rejected, not indexed


async def test_robots_disallowed_url_not_fetched(httpserver: HTTPServer, pool: asyncpg.Pool):
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nDisallow: /private/", content_type="text/plain"
    )
    url = httpserver.url_for("/private/secret.html")

    async with pool.acquire() as conn:
        await crawl_url(url=url, depth=0, conn=conn)
        row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is None  # Blocked by robots.txt
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_crawler.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'crawl_url'`

- [ ] **Step 3: Implement collector/crawler/worker.py**

```python
"""
Async crawler worker.
crawl_url() handles one URL: fetch → security → robots → encode → signal filter → index.
run_crawler() runs the full pool of workers until the queue is empty.
"""
from __future__ import annotations
import asyncio
import asyncpg
import chardet
import httpx
from asyncio import timeout as async_timeout
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

from collector.config import settings
from collector.crawler import robots as robots_module
from collector.crawler import queue as queue_module
from collector.crawler.security import (
    SecurityViolation,
    check_url,
    check_content_length,
    normalize_url,
)
from collector.signals.filter import score_page
from collector.indexer import db as indexer_db

_CONTENT_TYPE_HTML = ("text/html",)


def _extract_domain(url: str) -> str:
    return urlparse(url).netloc


def _extract_text(soup: BeautifulSoup) -> str:
    """Extract body text, stripping script/style/nav content."""
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract and normalise all href links from the page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full_url = urljoin(base_url, href)
        normalized = normalize_url(full_url)
        parsed = urlparse(normalized)
        if parsed.scheme in ("http", "https"):
            links.append(normalized)
    return links


def _extract_frame_srcs(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract frame/iframe src URLs so frameset content isn't missed."""
    srcs = []
    for tag in soup.find_all(["frame", "iframe"], src=True):
        src = tag["src"].strip()
        if src and not src.startswith(("javascript:", "#")):
            srcs.append(normalize_url(urljoin(base_url, src)))
    return srcs


async def crawl_url(
    url: str,
    depth: int,
    conn: asyncpg.Connection,
    client: httpx.AsyncClient | None = None,
) -> None:
    """
    Fetch and process a single URL.
    Handles: security checks, robots.txt, encoding detection,
    signal filtering, indexing/quarantining, link extraction.
    """
    domain = _extract_domain(url)

    # Pre-flight: check blocked domains
    if await indexer_db.is_domain_blocked(conn, domain):
        return

    # Pre-flight: security check
    try:
        check_url(url)
    except SecurityViolation as exc:
        await indexer_db.log_threat(conn, url, domain, exc.threat_type, exc.detail)
        return

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=settings.httpx_connect_timeout,
                read=settings.httpx_read_timeout,
            ),
            headers={"User-Agent": robots_module.USER_AGENT},
            max_redirects=5,
        )

    try:
        # robots.txt check
        allowed = await robots_module.is_allowed(url, client)
        if not allowed:
            return

        # Fetch — stream to enforce size limit
        try:
            async with async_timeout(settings.httpx_read_timeout):
                resp = await client.get(url)
        except (httpx.RequestError, asyncio.TimeoutError) as exc:
            await indexer_db.log_threat(
                conn, url, domain, "slow_response", str(exc)
            )
            return

        # Re-validate URL after redirects (could have redirected to internal IP)
        final_url = str(resp.url)
        if final_url != url:
            try:
                check_url(final_url)
            except SecurityViolation as exc:
                await indexer_db.log_threat(conn, url, domain, exc.threat_type, exc.detail)
                return

        # Content-type check — only index HTML
        content_type = resp.headers.get("content-type", "")
        if not any(ct in content_type for ct in _CONTENT_TYPE_HTML):
            return

        # Content-Length check
        raw_bytes = resp.content
        try:
            check_content_length(len(raw_bytes), settings.response_size_limit_bytes)
        except SecurityViolation as exc:
            await indexer_db.log_threat(conn, url, domain, exc.threat_type, exc.detail)
            return

        # Encoding detection
        last_modified = resp.headers.get("last-modified")
        detected = chardet.detect(raw_bytes)
        confidence = detected.get("confidence") or 0.0
        encoding = detected.get("encoding") or "utf-8"

        if confidence < settings.chardet_confidence_threshold:
            # Quarantine low-confidence encodings for manual inspection
            from collector.signals.filter import FilterResult
            result = FilterResult(
                passed=False,
                score=0,
                signals={},
                quarantine_reason="encoding_uncertain",
            )
            await indexer_db.upsert_quarantine(
                conn, url, None, result, http_status=resp.status_code
            )
            return

        html = raw_bytes.decode(encoding, errors="replace")

        # Signal filter (with processing timeout to guard against ReDoS)
        try:
            async with async_timeout(settings.page_process_timeout):
                result = await asyncio.get_event_loop().run_in_executor(
                    None, score_page, html, domain, last_modified
                )
        except asyncio.TimeoutError:
            await indexer_db.log_threat(
                conn, url, domain, "recursion_bomb",
                "Signal filter timed out — possible malicious nesting"
            )
            return

        if result.auto_rejected:
            return

        if result.quarantine_reason:
            await indexer_db.upsert_quarantine(
                conn, url, html, result, http_status=resp.status_code
            )
            # For frameset pages, also enqueue the frame sources
            if result.quarantine_reason == "frameset":
                soup = BeautifulSoup(html, "lxml")
                for src in _extract_frame_srcs(soup, url):
                    await queue_module.enqueue(conn, src, source_url=url, depth=depth + 1)
            return

        if result.passed:
            soup = BeautifulSoup(html, "lxml")
            title = soup.title.string.strip() if soup.title and soup.title.string else None
            raw_text = _extract_text(soup)

            await indexer_db.upsert_page(
                conn=conn,
                url=final_url,
                domain=domain,
                title=title,
                raw_text=raw_text,
                result=result,
                page_size_bytes=len(raw_bytes),
            )

            # Enqueue discovered links if under depth cap
            if depth < settings.crawl_depth_max:
                for link in _extract_links(soup, final_url):
                    await queue_module.enqueue(conn, link, source_url=final_url, depth=depth + 1)

    finally:
        if own_client:
            await client.aclose()


async def _worker(pool: asyncpg.Pool, client: httpx.AsyncClient, semaphores: dict) -> None:
    """Single worker: claim a URL from the queue and process it."""
    async with pool.acquire() as conn:
        records = await queue_module.claim_next(conn, limit=1)
        if not records:
            return
        record = records[0]

    domain = _extract_domain(record["url"])
    # Per-domain rate limiting
    if domain not in semaphores:
        semaphores[domain] = asyncio.Semaphore(1)
    async with semaphores[domain]:
        await asyncio.sleep(settings.crawl_delay_seconds)
        async with pool.acquire() as conn:
            try:
                await crawl_url(
                    url=record["url"],
                    depth=record["depth"],
                    conn=conn,
                    client=client,
                )
                await queue_module.mark_done(conn, record["id"])
            except Exception as exc:
                await queue_module.mark_failed(conn, record["id"], record["attempts"])


async def run_crawler(pool: asyncpg.Pool) -> None:
    """
    Run the crawl worker pool until the queue is exhausted.
    Spawn settings.crawl_workers concurrent workers.
    """
    semaphores: dict[str, asyncio.Semaphore] = {}
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(
            connect=settings.httpx_connect_timeout,
            read=settings.httpx_read_timeout,
        ),
        headers={"User-Agent": robots_module.USER_AGENT},
        max_redirects=5,
    ) as client:
        while True:
            tasks = [
                asyncio.create_task(_worker(pool, client, semaphores))
                for _ in range(settings.crawl_workers)
            ]
            await asyncio.gather(*tasks)

            # Check if queue has any remaining pending work
            async with pool.acquire() as conn:
                depth = await queue_module.queue_depth(conn)
            if depth.get("pending", 0) == 0 and depth.get("in_progress", 0) == 0:
                break


if __name__ == "__main__":
    import asyncio
    from collector.db import get_pool, close_pool

    async def main() -> None:
        pool = await get_pool()
        try:
            print("Starting crawler...")
            await run_crawler(pool)
            print("Queue exhausted.")
        finally:
            await close_pool()

    asyncio.run(main())
```

- [ ] **Step 4: Run crawler integration tests**

```bash
pytest tests/test_crawler.py -v
```

Expected: All tests pass. If `test_old_web_page_gets_indexed` fails, check that the test DB has been migrated and the pool fixture connects to the right URL.

- [ ] **Step 5: Commit**

```bash
git add collector/crawler/worker.py tests/test_crawler.py
git commit -m "feat: async crawler worker — fetch, filter, index, quarantine"
```

---

## What's Next

**Plan 4 — API + Tasks** (`2026-05-22-the-collector-plan-4-api.md`)
All FastAPI routes (search, seeds, crawl control, quarantine, threats) + Celery re-crawl tasks. Run `docker compose up` and use the full stack.
