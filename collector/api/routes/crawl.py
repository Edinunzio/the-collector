from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks
from collector.db import get_pool
from collector.crawler.queue import queue_depth

router = APIRouter()

_crawl_running = False


@router.post("/crawl/start", status_code=202)
async def start_crawl(background_tasks: BackgroundTasks) -> dict:
    global _crawl_running
    if _crawl_running:
        return {"status": "already_running"}
    background_tasks.add_task(_run_crawl)
    return {"status": "started"}


async def _run_crawl() -> None:
    global _crawl_running
    _crawl_running = True
    try:
        from collector.crawler.worker import run_crawler
        pool = await get_pool()
        await run_crawler(pool)
    finally:
        _crawl_running = False


@router.get("/crawl/status")
async def crawl_status() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        depth = await queue_depth(conn)
    return {
        "running": _crawl_running,
        **depth,
    }
