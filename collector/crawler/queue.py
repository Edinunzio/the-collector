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
