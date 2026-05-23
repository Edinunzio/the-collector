"""
Minimal HTML UI for The Collector.

Deliberately framework-free — server-rendered Jinja templates, no JS.
The UI calls the existing JSON routes via internal function calls
(not over HTTP) to avoid double-handling.
"""
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from collector.api.routes.search import search as search_route
from collector.api.routes.pages import stats as stats_route
from collector.api.routes.crawl import crawl_status as crawl_status_route, _run_crawl
from collector.api.routes.quarantine import (
    list_quarantine as list_quarantine_route,
    approve_quarantine as approve_route,
    reject_quarantine as reject_route,
    rescore_quarantine as rescore_route,
)
import collector.api.routes.crawl as crawl_module

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Custom Jinja filters
templates.env.filters["pluralize"] = lambda n: "" if n == 1 else "s"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = None,
    page: int = Query(0, ge=0),
):
    """Search page — also the home page."""
    stats_data = await stats_route()

    if not q:
        return templates.TemplateResponse(
            request,
            "search.html",
            {"query": None, "stats": stats_data},
        )

    result = await search_route(q=q, page=page, limit=10)
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "query": q,
            "page": page,
            "limit": 10,
            "total": result.total,
            "results": [r.model_dump() for r in result.results],
            "stats": stats_data,
        },
    )


@router.get("/ui/stats", response_class=HTMLResponse)
async def ui_stats(request: Request):
    stats_data = await stats_route()
    crawl_data = await crawl_status_route()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {"stats": stats_data, "crawl": crawl_data},
    )


@router.post("/ui/crawl-start")
async def ui_crawl_start(background_tasks: BackgroundTasks):
    """Trigger a crawl from the stats page, then redirect back."""
    if not crawl_module._crawl_running:
        background_tasks.add_task(_run_crawl)
    return RedirectResponse(url="/ui/stats", status_code=303)


@router.get("/ui/quarantine", response_class=HTMLResponse)
async def ui_quarantine(request: Request):
    items = await list_quarantine_route(reviewed=False, limit=50, offset=0)
    return templates.TemplateResponse(
        request,
        "quarantine.html",
        {"items": items},
    )


@router.post("/ui/quarantine/{item_id}/approve")
async def ui_quarantine_approve(item_id: int):
    await approve_route(item_id)
    return RedirectResponse(url="/ui/quarantine", status_code=303)


@router.post("/ui/quarantine/{item_id}/reject")
async def ui_quarantine_reject(item_id: int):
    await reject_route(item_id)
    return RedirectResponse(url="/ui/quarantine", status_code=303)


@router.post("/ui/quarantine/{item_id}/rescore")
async def ui_quarantine_rescore(item_id: int):
    await rescore_route(item_id)
    return RedirectResponse(url="/ui/quarantine", status_code=303)
