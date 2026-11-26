"""Decision-support alerts: generate, list, read, dismiss."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.services import alert_service

router = APIRouter(tags=["alerts"])


@router.post("/alerts/generate")
def generate(user: CurrentUser, db: DbSession) -> dict:
    """Run every rule against the current portfolio and store what it finds.

    Six rules, one per category the `alerts` schema already enumerates:
    concentration, drawdown, goals off track, allocation drift, health score
    drop and model-detected anomalies. Each alert carries the measurement,
    the threshold it passed and the evidence behind it.

    Two gates stand between a rule and a stored alert. Every message is run
    through the Copilot's groundedness check against the measurements that
    produced it, so a rule cannot state a figure the services did not
    compute. And every message is scanned for wording that reads as
    investment advice. Rejections are returned rather than hidden, because a
    rule that keeps failing is a bug worth seeing.

    An alert of the same type raised within the last 24 hours is not
    recreated, so repeated calls do not stack duplicates.
    """
    return alert_service.generate_alerts(db, user)


@router.get("/alerts")
def list_alerts(
    user: CurrentUser,
    db: DbSession,
    include_read: bool = Query(default=True, description="Include alerts already read"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Alerts for the signed-in user, newest first."""
    return alert_service.list_alerts(db, user, include_read=include_read, limit=limit)


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Mark one alert as read."""
    updated = alert_service.mark_read(db, user, alert_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
        )
    return updated


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(alert_id: int, user: CurrentUser, db: DbSession) -> None:
    """Dismiss one alert permanently."""
    if not alert_service.dismiss(db, user, alert_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
        )
