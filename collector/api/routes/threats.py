from __future__ import annotations
from fastapi import APIRouter, HTTPException
from collector.db import get_pool

router = APIRouter()


@router.get("/threats")
async def list_threats(
    threat_type: str | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        conditions, params = [], []
        if threat_type:
            conditions.append(f"threat_type = ${len(params)+1}")
            params.append(threat_type)
        if domain:
            conditions.append(f"domain = ${len(params)+1}")
            params.append(domain)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        rows = await conn.fetch(
            f"SELECT * FROM threat_log {where} ORDER BY detected_at DESC "
            f"LIMIT ${len(params)-1} OFFSET ${len(params)}",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/threats/{threat_id}/block-domain")
async def block_domain(threat_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM threat_log WHERE id = $1", threat_id)
        if not row:
            raise HTTPException(status_code=404, detail="Threat not found")
        await conn.execute(
            """
            INSERT INTO blocked_domains (domain, reason, source)
            VALUES ($1, $2, 'manual')
            ON CONFLICT (domain) DO NOTHING
            """,
            row["domain"],
            f"Promoted from threat_log #{threat_id}: {row['threat_type']}",
        )
        await conn.execute(
            "UPDATE threat_log SET domain_blocked = TRUE WHERE domain = $1",
            row["domain"],
        )
    return {"status": "blocked", "domain": row["domain"]}


@router.get("/blocked-domains")
async def list_blocked_domains() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM blocked_domains ORDER BY blocked_at DESC"
        )
    return [dict(r) for r in rows]


@router.delete("/blocked-domains/{domain}", status_code=204)
async def unblock_domain(domain: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM blocked_domains WHERE domain = $1", domain
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Domain not found in blocklist")
