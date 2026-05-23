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
                settings.httpx_read_timeout,  # default for write/pool
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
            except Exception:
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
            settings.httpx_read_timeout,
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
