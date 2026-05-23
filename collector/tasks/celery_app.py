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
                timeout=httpx.Timeout(10.0, connect=5.0, read=10.0),
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
