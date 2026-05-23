"""
Shared test fixtures.

Test isolation strategy: each test runs inside a transaction that is rolled back
after the test. This means tests don't pollute each other and the DB stays clean
without truncating tables between runs.

Requires a running Postgres at TEST_DATABASE_URL (see .env or set the env var).
The test DB must already exist — run: docker compose exec db psql -U collector -c "CREATE DATABASE collector_test;"
"""
import asyncio
import os
import asyncpg
import pytest
from pathlib import Path

def _derive_test_url() -> str:
    """
    Default TEST_DATABASE_URL.

    Priority:
    1. Explicit TEST_DATABASE_URL env var
    2. Swap database name in DATABASE_URL (so it works inside Docker where host is `db`)
    3. Fallback to localhost
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    prod = os.environ.get("DATABASE_URL")
    if prod:
        # postgresql://user:pass@host:port/dbname  →  .../collector_test
        return prod.rsplit("/", 1)[0] + "/collector_test"
    return "postgresql://collector:collector@localhost:5432/collector_test"


TEST_DATABASE_URL = _derive_test_url()


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
