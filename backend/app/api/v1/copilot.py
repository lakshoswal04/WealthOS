"""The AI Wealth Copilot endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.services import copilot_service, copilot_tools

router = APIRouter(prefix="/copilot", tags=["copilot"])


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    include_tool_outputs: bool = Field(
        default=False,
        description="Return the raw tool JSON the answer was built from",
    )


@router.post("/chat")
def chat(payload: ChatRequest, user: CurrentUser, db: DbSession) -> dict:
    """Ask a question about this portfolio.

    The assistant calls read-only backend tools and narrates their results.
    Every number in the answer is checked against those tool outputs before
    the response is returned; the check is reported under ``grounding``.
    """
    result = copilot_service.answer(
        db, user, payload.message,
        history=[turn.model_dump() for turn in payload.history],
    )
    if not payload.include_tool_outputs:
        result.pop("tool_outputs", None)
    return result


@router.get("/capabilities")
def capabilities() -> dict:
    """What the Copilot can do and how it is currently running."""
    return {
        "mode": "llm" if settings.copilot_enabled else "deterministic_fallback",
        "provider": settings.llm_provider_active or "template",
        "model": settings.llm_model if settings.copilot_enabled else "template-explainer",
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in copilot_tools.TOOL_SCHEMAS
        ],
        "grounding": (
            "Every number in an answer is extracted and matched against the "
            "tool outputs that produced it. Unmatched figures are reported "
            "rather than presented as fact."
        ),
        "limits": [
            "Read-only: it cannot change holdings or goals, and cannot place trades. "
            "It can propose a paper order, which is placed only when the user presses Confirm.",
            "It does not give investment advice.",
            "Forecasts are projections under stated assumptions, not predictions.",
        ],
    }
