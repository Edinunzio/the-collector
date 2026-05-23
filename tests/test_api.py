"""API route tests — all routes tested via FastAPI's AsyncClient."""
import json
import pytest
import asyncpg
from httpx import AsyncClient, ASGITransport
from collector.api.main import app
import collector.db as db_module


@pytest.fixture
async def test_app(migrated_db: str, monkeypatch):
    """
    Override the shared DB pool to use the test database.
    The monkeypatch resets the global pool between tests.
    """
    pool = await asyncpg.create_pool(dsn=migrated_db, min_size=1, max_size=3)
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
async def api_db(migrated_db: str):
    """Per-test DB connection. Truncate-based isolation since the API commits."""
    conn = await asyncpg.connect(dsn=migrated_db)
    yield conn
    await conn.execute(
        "TRUNCATE pages, quarantine, crawl_queue, seeds, threat_log, blocked_domains "
        "RESTART IDENTITY CASCADE"
    )
    await conn.close()


# --- /search ---

async def test_search_returns_empty_for_no_results(client: AsyncClient):
    resp = await client.get("/search?q=xyzzyabcdef123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["results"] == []


async def test_search_finds_indexed_page(client: AsyncClient, api_db: asyncpg.Connection):
    await api_db.execute(
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


async def test_search_pagination(client: AsyncClient, api_db: asyncpg.Connection):
    for i in range(5):
        await api_db.execute(
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
