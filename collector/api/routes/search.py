"""
GET /search — full-text search using Postgres ts_rank_cd.
Results are ranked by BM25-equivalent relevance (ts_rank_cd).
Dead pages are excluded. Results include signal breakdown and a snippet.
"""
from __future__ import annotations
import json
import re
from fastapi import APIRouter, Query
from pydantic import BaseModel
from collector.db import get_pool

router = APIRouter()


class SearchResult(BaseModel):
    url: str
    title: str | None
    snippet: str
    old_web_score: int
    signals: dict
    crawled_at: str


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    limit: int
    results: list[SearchResult]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
) -> SearchResponse:
    pool = await get_pool()
    ts_q = _to_tsquery(q)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                url,
                title,
                ts_headline(
                    'english',
                    raw_text,
                    to_tsquery('english', $1),
                    'MaxWords=25, MinWords=10, StartSel="", StopSel=""'
                ) AS snippet,
                old_web_score,
                detected_signals,
                crawled_at,
                ts_rank_cd(search_vector, to_tsquery('english', $1)) AS rank
            FROM pages
            WHERE search_vector @@ to_tsquery('english', $1)
              AND status = 'active'
            ORDER BY rank DESC
            LIMIT $2 OFFSET $3
            """,
            ts_q, limit, page * limit,
        )

        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM pages
            WHERE search_vector @@ to_tsquery('english', $1)
              AND status = 'active'
            """,
            ts_q,
        )

    results = [
        SearchResult(
            url=row["url"],
            title=row["title"],
            snippet=row["snippet"] or "",
            old_web_score=row["old_web_score"],
            signals=json.loads(row["detected_signals"]) if row["detected_signals"] else {},
            crawled_at=row["crawled_at"].isoformat(),
        )
        for row in rows
    ]

    return SearchResponse(
        query=q,
        total=total or 0,
        page=page,
        limit=limit,
        results=results,
    )


def _to_tsquery(q: str) -> str:
    """
    Convert a plain search query to a tsquery string.
    Joins words with & (AND). Strips non-alphanumeric characters.
    Example: "tropical fish tanks" → "tropical & fish & tanks"
    """
    words = re.findall(r'\w+', q)
    if not words:
        return "unknown"
    return " & ".join(words)
