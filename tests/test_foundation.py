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
