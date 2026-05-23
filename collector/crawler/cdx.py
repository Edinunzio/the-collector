"""
Internet Archive CDX API client.
Fetches historical URLs captured between two years that returned HTTP 200.
These are live old-web pages that no modern link graph connects to.

API docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""
from __future__ import annotations
import httpx

CDX_API_URL = "https://web.archive.org/cdx/search/cdx"


async def fetch_cdx_urls(
    from_year: int,
    to_year: int,
    limit: int = 10_000,
    match_type: str = "domain",
    filter_mime: str = "text/html",
) -> list[tuple[str, str]]:
    """
    Query the CDX API for URLs captured between from_year and to_year
    that returned HTTP 200 and are HTML pages.

    Returns a list of (url, timestamp) tuples. Empty list on any error.

    Rate limit: be polite — call this in batches with delays, not in a tight loop.
    """
    params = {
        "output": "json",
        "fl": "urlkey,timestamp,original,statuscode",
        "filter": "statuscode:200",
        "from": f"{from_year}0101",
        "to": f"{to_year}1231",
        "limit": str(limit),
        "matchType": match_type,
        "mimetype": filter_mime,
        "collapse": "urlkey",  # deduplicate same URL
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(CDX_API_URL, params=params)
            resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        print(f"[cdx] API error: {exc}")
        return []

    results: list[tuple[str, str]] = []
    lines = resp.text.strip().splitlines()

    # First line is the header row — skip it
    for line in lines[1:]:
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        try:
            import json
            parts = json.loads(line)
            # parts: [urlkey, timestamp, original_url, statuscode]
            if len(parts) >= 4 and parts[3] == "200":
                results.append((parts[2], parts[1]))
        except (ValueError, IndexError):
            continue

    return results
