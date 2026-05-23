"""
Integration tests for the crawler worker.
Uses pytest-httpserver to serve real HTML over HTTP so we test the full
fetch → robots → signal → index pipeline without hitting the internet.

Note: pytest-httpserver runs on 127.0.0.1, which our SSRF check would normally
block. We monkeypatch check_url to a no-op for these tests since the goal is
testing the worker pipeline, not the security layer (that has its own tests).
"""
import pytest
import asyncpg
from pytest_httpserver import HTTPServer
from collector.crawler import worker as worker_module
from collector.crawler.worker import crawl_url

GEOCITIES_HTML = """<HTML><HEAD><TITLE>My Fish Page</TITLE>
<meta name="date" content="1999-03-14"></HEAD>
<BODY><FONT SIZE="+2">Welcome!</FONT>
<MARQUEE>Oscar Fish Forever</MARQUEE>
<TABLE><TR><TD>I have kept cichlids since 1997. They are the best tropical fish.</TD></TR></TABLE>
</BODY></HTML>"""

REACT_HTML = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/main.a3f9b12c.min.css">
</head><body><div id="root"></div>
<script>const react=require('react');const webpack_require=null;</script>
<script src="/bundle.c4d8e3f1.min.js"></script></body></html>"""


@pytest.fixture(autouse=True)
def _bypass_ssrf_for_localhost(monkeypatch):
    """pytest-httpserver runs on 127.0.0.1 — bypass our private-IP SSRF check."""
    monkeypatch.setattr(
        "collector.crawler.worker.check_url",
        lambda url: None,
    )
    # Also clear the robots cache so each test starts fresh
    from collector.crawler import robots
    robots.clear_cache()


@pytest.fixture
async def conn(migrated_db: str):
    """Per-test connection. Truncate-based isolation since crawl_url commits."""
    c = await asyncpg.connect(dsn=migrated_db)
    yield c
    await c.execute("TRUNCATE pages, quarantine, crawl_queue, threat_log RESTART IDENTITY CASCADE")
    await c.close()


async def test_old_web_page_gets_indexed(httpserver: HTTPServer, conn: asyncpg.Connection):
    httpserver.expect_request("/fish.html").respond_with_data(
        GEOCITIES_HTML, content_type="text/html"
    )
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nAllow: /", content_type="text/plain"
    )
    url = httpserver.url_for("/fish.html")

    await crawl_url(url=url, depth=0, conn=conn)
    row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is not None, "Expected old-web page to be indexed"
    assert row["old_web_score"] >= 3
    assert "oscar" in row["raw_text"].lower() or "cichlid" in row["raw_text"].lower()


async def test_react_app_not_indexed(httpserver: HTTPServer, conn: asyncpg.Connection):
    httpserver.expect_request("/app.html").respond_with_data(
        REACT_HTML, content_type="text/html"
    )
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nAllow: /", content_type="text/plain"
    )
    url = httpserver.url_for("/app.html")

    await crawl_url(url=url, depth=0, conn=conn)
    row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is None, "SPA root div should auto-reject"


async def test_robots_disallowed_url_not_fetched(httpserver: HTTPServer, conn: asyncpg.Connection):
    httpserver.expect_request("/robots.txt").respond_with_data(
        "User-agent: *\nDisallow: /private/", content_type="text/plain"
    )
    url = httpserver.url_for("/private/secret.html")

    await crawl_url(url=url, depth=0, conn=conn)
    row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)

    assert row is None, "Blocked by robots.txt"
