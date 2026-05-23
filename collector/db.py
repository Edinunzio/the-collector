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
