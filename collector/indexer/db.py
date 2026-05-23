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
