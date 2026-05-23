from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()


class CDXImportRequest(BaseModel):
    from_year: int = 1996
    to_year: int = 2008
    limit: int = 10_000


@router.post("/tasks/import-cdx", status_code=202)
async def trigger_cdx_import(
    body: CDXImportRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    background_tasks.add_task(_run_cdx_import, body.from_year, body.to_year, body.limit)
    return {"status": "started", "from_year": body.from_year, "to_year": body.to_year}


async def _run_cdx_import(from_year: int, to_year: int, limit: int) -> None:
    from collector.crawler.cdx import fetch_cdx_urls
    from collector.crawler.queue import enqueue
    from collector.db import get_pool

    urls = await fetch_cdx_urls(from_year=from_year, to_year=to_year, limit=limit)
    pool = await get_pool()
    async with pool.acquire() as conn:
        for url, _ in urls:
            await enqueue(conn, url, source_url="cdx", depth=0)
    print(f"[cdx] Enqueued {len(urls)} URLs from {from_year}-{to_year}")
