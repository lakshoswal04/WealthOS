"""Performance, risk and concentration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.services import risk_service
from app.services.risk_service import InsufficientHistory

router = APIRouter(prefix="/portfolio", tags=["analytics"])


@router.get("/analytics")
def get_analytics(
    user: CurrentUser,
    db: DbSession,
    lookback: str | None = Query(default=None, description="1m, 3m, 6m, 1y, 3y or 5y"),
) -> dict:
    """Returns, risk-adjusted ratios and trailing performance by window."""
    try:
        return risk_service.analytics(db, user, lookback)
    except InsufficientHistory as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/risk")
def get_risk(user: CurrentUser, db: DbSession) -> dict:
    """Volatility, drawdown, tail risk, beta and the correlation matrix."""
    try:
        return risk_service.risk(db, user)
    except InsufficientHistory as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/concentration")
def get_concentration(user: CurrentUser, db: DbSession) -> dict:
    """Concentration by asset, sector and asset class, with plain-language notes."""
    try:
        return risk_service.concentration(db, user)
    except InsufficientHistory as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
