from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from collector.db import get_pool
from collector.signals.filter import score_page

router = APIRouter()


@router.get("/quarantine")
async def list_quarantine(
    reason: str | None = None,
    reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = "SELECT id, url, error_reason, partial_score, http_status, fetched_at, reviewed FROM quarantine"
        params: list = []
        conditions = [f"reviewed = ${len(params)+1}"]
        params.append(reviewed)
        if reason:
            conditions.append(f"error_reason = ${len(params)+1}")
            params.append(reason)
        query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY fetched_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
        params += [limit, offset]
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/quarantine/{item_id}")
async def get_quarantine_item(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    data = dict(row)
    data["partial_signals"] = json.loads(data["partial_signals"]) if data["partial_signals"] else {}
    return data


@router.post("/quarantine/{item_id}/approve")
async def approve_quarantine(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if not row["raw_html"]:
            raise HTTPException(status_code=422, detail="No raw HTML stored — cannot approve")

        from collector.indexer import db as indexer_db
        from collector.signals.filter import FilterResult
        import json as _json

        result = FilterResult(
            passed=True,
            score=row["partial_score"],
            signals=_json.loads(row["partial_signals"]) if row["partial_signals"] else {},
        )
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(row["raw_html"], "lxml")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        raw_text = soup.get_text(separator=" ", strip=True)
        from urllib.parse import urlparse
        domain = urlparse(row["url"]).netloc

        await indexer_db.upsert_page(
            conn=conn,
            url=row["url"],
            domain=domain,
            title=title,
            raw_text=raw_text,
            result=result,
            page_size_bytes=len(row["raw_html"].encode()),
        )
        await conn.execute("UPDATE quarantine SET reviewed = TRUE WHERE id = $1", item_id)

    return {"status": "approved", "url": row["url"]}


@router.post("/quarantine/{item_id}/reject")
async def reject_quarantine(item_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM quarantine WHERE id = $1", item_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "rejected"}


@router.post("/quarantine/{item_id}/rescore")
async def rescore_quarantine(item_id: int) -> dict:
    """Re-run the signal filter with current weights. Useful after tuning thresholds."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM quarantine WHERE id = $1", item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if not row["raw_html"]:
            raise HTTPException(status_code=422, detail="No raw HTML stored")

        from urllib.parse import urlparse
        domain = urlparse(row["url"]).netloc
        result = score_page(row["raw_html"], domain)

        await conn.execute(
            """
            UPDATE quarantine
            SET partial_signals = $1, partial_score = $2, error_reason = $3, reviewed = FALSE
            WHERE id = $4
            """,
            json.dumps(result.signals), result.score,
            result.quarantine_reason or ("passed" if result.passed else "below_threshold"),
            item_id,
        )

    return {
        "score": result.score,
        "passed": result.passed,
        "quarantine_reason": result.quarantine_reason,
        "signals": result.signals,
    }
