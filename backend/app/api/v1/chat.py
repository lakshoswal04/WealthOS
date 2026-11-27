"""Saved AI chat threads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatContext(BaseModel):
    symbol: str | None = Field(default=None, max_length=32)


class NewThread(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    context: ChatContext | None = None


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    context: ChatContext | None = None


@router.get("/threads")
def threads(user: CurrentUser, db: DbSession) -> dict:
    return {"threads": chat_service.list_threads(db, user)}


@router.post("/threads", status_code=status.HTTP_201_CREATED)
def create(payload: NewThread, user: CurrentUser, db: DbSession) -> dict:
    ctx = payload.context.model_dump(exclude_none=True) if payload.context else None
    thread = chat_service.create_thread(db, user, payload.title, ctx or None)
    return chat_service.thread_dict(thread, with_messages=True)


def _owned(db, user, thread_id: int):
    thread = chat_service.get_thread(db, user, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return thread


@router.get("/threads/{thread_id}")
def read(thread_id: int, user: CurrentUser, db: DbSession) -> dict:
    return chat_service.thread_dict(_owned(db, user, thread_id), with_messages=True)


@router.post("/threads/{thread_id}/messages")
def send(thread_id: int, payload: NewMessage, user: CurrentUser, db: DbSession) -> dict:
    thread = _owned(db, user, thread_id)
    ctx = payload.context.model_dump(exclude_none=True) if payload.context else None
    return chat_service.send(db, user, thread, payload.content, ctx or None)


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(thread_id: int, user: CurrentUser, db: DbSession) -> None:
    if not chat_service.delete_thread(db, user, thread_id):
        raise HTTPException(status_code=404, detail="Chat not found")
