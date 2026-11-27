"""Ready-made and user-built stock screens."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import SavedScreen
from app.services import screener_service as ss

router = APIRouter(prefix="/screeners", tags=["screeners"])


class ScreenDefinition(BaseModel):
    filters: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    sort: dict[str, str] | None = None
    limit: int = Field(default=50, ge=1, le=100)


class SaveScreen(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    definition: ScreenDefinition


@router.get("")
def screens(user: CurrentUser) -> dict:
    return {"screens": ss.list_screens(), "fields": ss.field_catalog()}


@router.get("/run/{screen_id}")
def run_screen(screen_id: str, user: CurrentUser, db: DbSession,
               limit: int = Query(50, ge=1, le=100)) -> dict:
    try:
        return ss.run_screen(db, screen_id, limit)
    except ss.ScreenError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/run")
def run_custom(payload: ScreenDefinition, user: CurrentUser, db: DbSession) -> dict:
    try:
        return ss.run(db, payload.model_dump())
    except ss.ScreenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _saved(row: SavedScreen) -> dict:
    return {"id": row.id, "name": row.name, "definition": row.definition,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("/saved")
def list_saved(user: CurrentUser, db: DbSession) -> dict:
    rows = db.scalars(select(SavedScreen).where(SavedScreen.user_id == user.id)
                      .order_by(SavedScreen.id.desc()))
    return {"screens": [_saved(r) for r in rows]}


@router.post("/saved", status_code=status.HTTP_201_CREATED)
def save(payload: SaveScreen, user: CurrentUser, db: DbSession) -> dict:
    try:
        definition = ss.validate(payload.definition.model_dump())
    except ss.ScreenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    row = SavedScreen(user_id=user.id, name=payload.name.strip(), definition=definition)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _saved(row)


def _owned(db, user, screen_id: int) -> SavedScreen:
    row = db.scalar(select(SavedScreen).where(SavedScreen.id == screen_id,
                                              SavedScreen.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Screen not found")
    return row


@router.get("/saved/{screen_id}/run")
def run_saved(screen_id: int, user: CurrentUser, db: DbSession) -> dict:
    row = _owned(db, user, screen_id)
    result = ss.run(db, row.definition)
    result["saved"] = _saved(row)
    return result


@router.delete("/saved/{screen_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved(screen_id: int, user: CurrentUser, db: DbSession) -> None:
    db.delete(_owned(db, user, screen_id))
    db.commit()
