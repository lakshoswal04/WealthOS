"""Model-backed insight endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.ml_runtime.registry import registry
from app.services import insight_service

router = APIRouter(tags=["insights"])


@router.get("/investor-profile")
def get_investor_profile(user: CurrentUser, db: DbSession) -> dict:
    """Which behavioural cluster this investor's portfolio resembles."""
    return insight_service.investor_profile(db, user)


@router.get("/anomalies")
def get_anomalies(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=24, ge=1, le=120),
) -> dict:
    """Months whose portfolio behaviour the autoencoder could not reconstruct."""
    return insight_service.detect_anomalies(db, user, limit)


@router.get("/forecast")
def get_forecast(
    user: CurrentUser,
    db: DbSession,
    horizon: int = Query(default=12, description="Months ahead: 1, 3, 6 or 12"),
) -> dict:
    """Projected portfolio value, from the trained forecasting models."""
    if horizon not in (1, 3, 6, 12):
        horizon = 12
    return insight_service.wealth_forecast(db, user, horizon)


@router.get("/models/status", tags=["system"])
def model_status() -> dict:
    """Which model artifacts loaded, for diagnostics and the health page."""
    return registry.status()
