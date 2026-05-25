"""
GET /search — full-text search using Postgres ts_rank_cd, extended with:
  - Query-side synonym expansion (chickpea ↔ garbanzo, etc.)
  - pg_trgm trigram fallback for typo tolerance on title field

Ranking priority:
  FTS match  → ts_rank_cd(...) + 1.0   (always > 1.0)
  Trgm-only  → similarity(title, q)    (0.0 – 1.0)

FTS results always outrank trigram-only results.
"""
from __future__ import annotations
import json
import re
from fastapi import APIRouter, Query
from pydantic import BaseModel
from collector.db import get_pool
from collector.search.synonyms import expand

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
    ts_q = _to_tsquery(q)      # tsquery string, synonym-expanded
    raw_q = q.strip()          # raw query string for trigram similarity

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
                CASE
                    WHEN search_vector @@ to_tsquery('english', $1)
                        THEN ts_rank_cd(search_vector, to_tsquery('english', $1)) + 1.0
                    ELSE similarity(title, $2)
                END AS rank
            FROM pages
            WHERE status = 'active'
              AND (
                  search_vector @@ to_tsquery('english', $1)
                  OR similarity(title, $2) > 0.3
              )
            ORDER BY rank DESC
            LIMIT $3 OFFSET $4
            """,
            ts_q, raw_q, limit, page * limit,
        )

        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM pages
            WHERE status = 'active'
              AND (
                  search_vector @@ to_tsquery('english', $1)
                  OR similarity(title, $2) > 0.3
              )
            """,
            ts_q, raw_q,
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
    Convert a plain search query to a tsquery string with synonym expansion.

    Each word is expanded to include known synonyms, OR-joined inside parens.
    Words with no synonyms are passed through unchanged.

    Examples:
        "tropical fish tanks"  → "tropical & fish & tanks"
        "garbanzo beans"       → "(garbanzo | chickpea) & beans"
        "geociteis page"       → "(geociteis | geocities) & page"
    """
    words = re.findall(r'\w+', q)
    if not words:
        return "unknown"
    parts = []
    for word in words:
        variants = expand(word)
        if len(variants) == 1:
            parts.append(variants[0])
        else:
            parts.append("(" + " | ".join(variants) + ")")
    return " & ".join(parts)
