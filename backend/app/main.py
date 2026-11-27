"""WealthOS API entry point."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import (
    account, alerts, analytics, auth, autopilot, chat, copilot, goals, ideas, insights, linking, markets,
    options, paper, portfolio, research, screeners, signals, tools,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.live_market_service import MarketDataUnavailable
from app.services.signals_service import SignalsUnavailable
from app.services.market_data import OptionsUnavailable
from app.services.market_service import market_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("wealthos")


class _SkipProbe(Exception):
    """Skips the start-up model probe in low-memory mode."""

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

        if settings.low_memory:
            log.info("low-memory mode: models load on first use; PyTorch models are off")
            raise _SkipProbe
        status = registry.status()
        loaded = [k for k, v in status["available"].items() if v]
        missing = [k for k, v in status["available"].items() if not v]
        log.info("models loaded: %s", ", ".join(loaded) or "none")
        if missing:
            log.warning(
                "models unavailable (those endpoints will report it): %s",
                ", ".join(missing),
            )
    except _SkipProbe:
        pass
    except Exception as exc:
        log.error("model registry failed to initialise: %s", exc)

    if settings.live_market_enabled:
        import threading

        from app.services import live_market_service, screener_service

        def warm() -> None:
            from app.integrations.upstox.instruments import master
            from app.services import research_service

            def daily_jobs() -> None:
                # Price refresh, forward test and due Autopilot runs, then every 15 minutes.
                from app.services import scheduler

                scheduler.start()

            steps = [live_market_service.index_strip, screener_service.warm, master.ensure,
                     research_service.calendar, research_service.news, daily_jobs]
            if settings.low_memory:
                # The Upstox instrument file is large; load it when options are first used.
                steps.remove(master.ensure)
            for step in steps:
                try:
                    step()
                except Exception as exc:  # a cold cache must not stop the API
                    log.warning("warm-up step %s failed: %s", getattr(step, "__name__", step), exc)

        threading.Thread(target=warm, daemon=True).start()
        log.info("live market: Yahoo Finance (delayed), warming in the background")
    else:
        log.info("live market: disabled, every price is simulated")

    log.info(
        "wealth copilot: %s",
        f"{settings.llm_provider_active} ({settings.llm_model})" if settings.copilot_enabled else "deterministic fallback (no API key)",
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


@app.exception_handler(OptionsUnavailable)
async def options_unavailable_handler(request: Request, exc: OptionsUnavailable):
    """Option/futures data without an Upstox session: say why, and how to fix it."""
    if exc.state not in ("no_credentials", "not_connected", "expired"):
        # The session is fine; the data itself is missing (no listed contracts,
        # an empty chain). Nothing for the user to reconnect.
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": "market_data_unavailable"})
    return JSONResponse(status_code=409, content={
        "detail": str(exc), "code": "upstox_required", "state": exc.state,
        "action": {"label": "Connect Upstox" if exc.state in ("no_credentials", "not_connected")
                   else "Log in to Upstox again", "href": "/settings/brokers"},
    })


@app.exception_handler(MarketDataUnavailable)
async def market_data_unavailable_handler(request: Request, exc: MarketDataUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": "market_data_unavailable"})


@app.exception_handler(SignalsUnavailable)
async def signals_unavailable_handler(request: Request, exc: SignalsUnavailable):
    """Models not trained, or no price history yet: say which, so the UI can explain."""
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": exc.code})


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
app.include_router(markets.router, prefix=settings.api_v1_prefix)
app.include_router(options.router, prefix=settings.api_v1_prefix)
app.include_router(screeners.router, prefix=settings.api_v1_prefix)
app.include_router(ideas.router, prefix=settings.api_v1_prefix)
app.include_router(paper.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)
app.include_router(account.router, prefix=settings.api_v1_prefix)
app.include_router(tools.router, prefix=settings.api_v1_prefix)
app.include_router(signals.router, prefix=settings.api_v1_prefix)
app.include_router(autopilot.router, prefix=settings.api_v1_prefix)
app.include_router(signals.advisor_router, prefix=settings.api_v1_prefix)
app.include_router(account.callback_router, prefix=settings.api_v1_prefix)
