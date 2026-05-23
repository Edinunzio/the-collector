"""Shared asyncpg connection pool.

Import `get_pool()` wherever DB access is needed. Call `close_pool()` from
a lifespan/shutdown hook (FastAPI lifespan, Celery worker_shutdown, etc.).
"""
from __future__ import annotations
import asyncio
import asyncpg
from collector.config import settings

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Return the shared pool, creating it on first call.

    Double-checked locking guards against concurrent first-callers each
    creating their own pool (the unlocked check is the fast path once the
    pool exists; the locked re-check guarantees only one pool is created).
    """
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    dsn=settings.database_url,
                    min_size=settings.db_pool_min_size,
                    max_size=settings.db_pool_max_size,
                )
    return _pool


async def close_pool() -> None:
    """Cleanly close the pool. Call on application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
