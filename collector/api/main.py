"""
FastAPI application entry point.
The lifespan context manager ensures the DB pool is created once on startup
and cleanly closed on shutdown — no connection leaks across requests.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from collector.db import get_pool, close_pool
from collector.api.routes import (
    search,
    seeds,
    crawl,
    pages,
    quarantine,
    threats,
    tasks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()   # warm up pool
    yield
    await close_pool()


app = FastAPI(
    title="The Collector",
    description="A poor man's search engine for the weird old-school internet.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(search.router, tags=["search"])
app.include_router(seeds.router, tags=["seeds"])
app.include_router(crawl.router, tags=["crawl"])
app.include_router(pages.router, tags=["pages"])
app.include_router(quarantine.router, tags=["quarantine"])
app.include_router(threats.router, tags=["threats"])
app.include_router(tasks.router, tags=["tasks"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
