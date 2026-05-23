from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from collector.db import get_pool

router = APIRouter()


@router.get("/pages/{page_id}")
async def get_page(page_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE id = $1", page_id)
    if not row:
        raise HTTPException(status_code=404, detail="Page not found")
    data = dict(row)
    data["detected_signals"] = json.loads(data["detected_signals"]) if data["detected_signals"] else {}
    data["search_vector"] = str(data["search_vector"])  # not serialisable as-is
    return data


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(page_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM pages WHERE id = $1", page_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Page not found")


@router.get("/stats")
async def stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_pages = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE status = 'active'")
        total_domains = await conn.fetchval("SELECT COUNT(DISTINCT domain) FROM pages WHERE status = 'active'")
        avg_score = await conn.fetchval("SELECT AVG(old_web_score) FROM pages WHERE status = 'active'")
        dead_pages = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE status = 'dead'")
        quarantine_count = await conn.fetchval("SELECT COUNT(*) FROM quarantine WHERE reviewed = FALSE")
        threat_count = await conn.fetchval("SELECT COUNT(*) FROM threat_log")
    return {
        "total_pages": total_pages,
        "total_domains": total_domains,
        "avg_old_web_score": round(float(avg_score or 0), 2),
        "dead_pages": dead_pages,
        "quarantine_unreviewed": quarantine_count,
        "threat_log_total": threat_count,
    }
