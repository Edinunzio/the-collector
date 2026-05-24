"""
Minimal HTML UI for The Collector.

Deliberately framework-free — server-rendered Jinja templates, no JS.
The UI calls the existing JSON routes via internal function calls
(not over HTTP) to avoid double-handling.
"""
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request, Query, BackgroundTasks, Form
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
from collector.api.routes.seeds import (
    add_seed as add_seed_route,
    list_seeds as list_seeds_route,
    SeedIn,
)
from collector.api.routes.tasks import (
    trigger_cdx_import as trigger_cdx_route,
    CDXImportRequest,
)
from collector.api.routes.threats import (
    list_threats as list_threats_route,
    block_domain as block_domain_route,
    list_blocked_domains as list_blocked_route,
    unblock_domain as unblock_route,
)
import collector.api.routes.crawl as crawl_module

# Threat types we know how to log — used to populate the filter dropdown
_THREAT_TYPES = [
    "ssrf_attempt",
    "gzip_bomb",
    "spider_trap",
    "redirect_violation",
    "slow_response",
    "recursion_bomb",
    "oversized_response",
]

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
async def ui_stats(request: Request, cdx_message: str | None = None):
    stats_data = await stats_route()
    crawl_data = await crawl_status_route()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {"stats": stats_data, "crawl": crawl_data, "cdx_message": cdx_message},
    )


@router.post("/ui/crawl-start")
async def ui_crawl_start(background_tasks: BackgroundTasks):
    """Trigger a crawl from the stats page, then redirect back."""
    if not crawl_module._crawl_running:
        background_tasks.add_task(_run_crawl)
    return RedirectResponse(url="/ui/stats", status_code=303)


@router.post("/ui/cdx-import")
async def ui_cdx_import(
    background_tasks: BackgroundTasks,
    from_year: int = Form(1996),
    to_year: int = Form(2008),
    limit: int = Form(1000),
):
    """Trigger CDX API import from the stats page."""
    await trigger_cdx_route(
        CDXImportRequest(from_year=from_year, to_year=to_year, limit=limit),
        background_tasks,
    )
    msg = f"CDX import started: {from_year}–{to_year}, limit {limit}. URLs will appear in the queue shortly."
    from urllib.parse import quote
    return RedirectResponse(url=f"/ui/stats?cdx_message={quote(msg)}", status_code=303)


# --- Seeds ---

@router.get("/ui/seeds", response_class=HTMLResponse)
async def ui_seeds(request: Request, message: str | None = None):
    seeds = await list_seeds_route()
    return templates.TemplateResponse(
        request,
        "seeds.html",
        {"seeds": seeds, "message": message},
    )


@router.post("/ui/seeds")
async def ui_seeds_add(
    url: str = Form(...),
    label: str | None = Form(None),
):
    """Add a seed via form, redirect back with a success message."""
    label = (label or "").strip() or None
    await add_seed_route(SeedIn(url=url.strip(), label=label))
    from urllib.parse import quote
    msg = f"Added {url} to seeds + crawl queue."
    return RedirectResponse(url=f"/ui/seeds?message={quote(msg)}", status_code=303)


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


# --- Threats / blocked domains ---

@router.get("/ui/threats", response_class=HTMLResponse)
async def ui_threats(
    request: Request,
    threat_type: str | None = None,
    domain: str | None = None,
    message: str | None = None,
):
    # Normalise empty-string params from the filter form to None
    threat_type = threat_type or None
    domain = domain or None
    threats = await list_threats_route(
        threat_type=threat_type, domain=domain, limit=100, offset=0
    )
    blocked = await list_blocked_route()
    return templates.TemplateResponse(
        request,
        "threats.html",
        {
            "threats": threats,
            "blocked": blocked,
            "threat_types": _THREAT_TYPES,
            "filter_type": threat_type,
            "filter_domain": domain,
            "message": message,
        },
    )


@router.post("/ui/threats/{threat_id}/block-domain")
async def ui_threat_block(threat_id: int):
    result = await block_domain_route(threat_id)
    from urllib.parse import quote
    msg = f"Blocked domain: {result.get('domain', '')}"
    return RedirectResponse(url=f"/ui/threats?message={quote(msg)}", status_code=303)


@router.post("/ui/blocked-domains/{domain}/unblock")
async def ui_unblock_domain(domain: str):
    await unblock_route(domain)
    from urllib.parse import quote
    msg = f"Unblocked {domain}."
    return RedirectResponse(url=f"/ui/threats?message={quote(msg)}", status_code=303)
