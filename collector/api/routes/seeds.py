from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from collector.db import get_pool
from collector.crawler.queue import enqueue_seed, enqueue_bulk_from_file

router = APIRouter()


class SeedIn(BaseModel):
    url: str
    label: str | None = None


class BulkSeedIn(BaseModel):
    file_path: str


@router.post("/seeds", status_code=201)
async def add_seed(seed: SeedIn) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await enqueue_seed(conn, seed.url, seed.label)
    return {"url": seed.url, "label": seed.label, "status": "queued"}


@router.get("/seeds")
async def list_seeds() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, url, label, source, added_at FROM seeds ORDER BY added_at DESC"
        )
    return [dict(r) for r in rows]


@router.post("/seeds/bulk")
async def bulk_import(body: BulkSeedIn) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        added = await enqueue_bulk_from_file(conn, body.file_path)
    return {"added": added, "file": body.file_path}
