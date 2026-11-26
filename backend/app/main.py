"""WealthOS API entry point."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import (
    alerts, analytics, auth, copilot, goals, insights, linking, portfolio,
    research,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.market_service import market_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("wealthos")

DESCRIPTION = """
Personal wealth intelligence: portfolio analytics, risk, goal forecasting and
a grounded AI Copilot.

**This is an academic research prototype, not a regulated financial advisory
service.** It explains computed portfolio metrics. It does not provide
investment advice, and every forecast is a projection under stated
assumptions rather than a prediction of returns.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the caches that would otherwise make the first request slow."""
    log.info("starting %s (%s)", settings.app_name, settings.environment)
    try:
        with SessionLocal() as db:
            market_cache.load(db)
            panel = market_cache.panel(db)
            if panel.empty:
                log.warning(
                    "no market prices loaded — run: python -m ml.pipelines.p04_seed_database"
                )
            else:
                log.info(
                    "market cache: %d dates x %d assets (%s → %s)",
                    len(panel), panel.shape[1],
                    panel.index.min().date(), panel.index.max().date(),
                )
    except Exception as exc:
        # A cold cache must not stop the API from booting; endpoints that need
        # prices will report the problem themselves.
        log.error("market cache failed to load: %s", exc)

    try:
        from app.ml_runtime.registry import registry

        status = registry.status()
        loaded = [k for k, v in status["available"].items() if v]
        missing = [k for k, v in status["available"].items() if not v]
        log.info("models loaded: %s", ", ".join(loaded) or "none")
        if missing:
            log.warning(
                "models unavailable (those endpoints will report it): %s",
                ", ".join(missing),
            )
    except Exception as exc:
        log.error("model registry failed to initialise: %s", exc)

    log.info(
        "wealth copilot: %s",
        "Anthropic API" if settings.copilot_enabled else "deterministic fallback (no API key)",
    )
    yield
    log.info("shutting down")


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    """Expose server-side duration, so the PRD's latency target is measurable."""
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log the detail, return a generic message.

    Stack traces and database errors can disclose schema and file paths, so
    they stay in the server log rather than going to the client.
    """
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. The incident has been logged."},
    )


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness and dependency check."""
    status_payload = {"status": "ok", "environment": settings.environment}
    try:
        with SessionLocal() as db:
            panel = market_cache.panel(db)
            status_payload["database"] = "connected"
            status_payload["market_data"] = {
                "assets": int(panel.shape[1]) if not panel.empty else 0,
                "latest_date": str(panel.index.max().date()) if not panel.empty else None,
            }
    except Exception as exc:
        status_payload["status"] = "degraded"
        status_payload["database"] = f"unavailable: {type(exc).__name__}"

    status_payload["copilot"] = "llm" if settings.copilot_enabled else "fallback"
    return status_payload


app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(portfolio.router, prefix=settings.api_v1_prefix)
app.include_router(analytics.router, prefix=settings.api_v1_prefix)
app.include_router(goals.router, prefix=settings.api_v1_prefix)
app.include_router(insights.router, prefix=settings.api_v1_prefix)
app.include_router(alerts.router, prefix=settings.api_v1_prefix)
app.include_router(linking.router, prefix=settings.api_v1_prefix)
app.include_router(copilot.router, prefix=settings.api_v1_prefix)
app.include_router(research.router, prefix=settings.api_v1_prefix)
