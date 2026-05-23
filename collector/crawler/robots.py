"""
Per-domain robots.txt cache.
Fetches and parses robots.txt once per domain per crawler run,
caches in-memory. Respects Disallow rules for our User-Agent.
"""
from __future__ import annotations
import asyncio
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx

USER_AGENT = "TheCollector/0.1 (+https://github.com/you/the-collector)"

_cache: dict[str, RobotFileParser | None] = {}
_cache_lock = asyncio.Lock()


async def is_allowed(url: str, client: httpx.AsyncClient) -> bool:
    """
    Return True if the given URL is allowed to be crawled.
    Fetches and caches robots.txt for the domain on first call.
    Returns True if robots.txt is missing or unreadable (opt-in not opt-out).
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    async with _cache_lock:
        if domain not in _cache:
            _cache[domain] = await _fetch_robots(domain, client)

    rp = _cache[domain]
    if rp is None:
        return True  # No robots.txt → allowed

    return rp.can_fetch(USER_AGENT, url)


async def _fetch_robots(base_url: str, client: httpx.AsyncClient) -> RobotFileParser | None:
    """Fetch and parse robots.txt. Returns None if not found or fetch fails."""
    robots_url = f"{base_url}/robots.txt"
    try:
        resp = await client.get(robots_url, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass
    return None


def clear_cache() -> None:
    """Clear the robots cache. Call between crawl runs if needed."""
    _cache.clear()
