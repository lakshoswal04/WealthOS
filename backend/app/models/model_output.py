"""Stored model predictions.

Writing predictions back to the database keeps the Copilot and the dashboard
reading the same values, and preserves what a model said at the time even
after it is retrained.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ModelOutput(Base):
    """One model's output for one user at one point in time."""

    __tablename__ = "model_outputs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Headline result in whichever form fits: a cluster id, a score, or both.
    prediction: Mapped[str | None] = mapped_column(String(128))
    score: Mapped[float | None] = mapped_column(Float)
    # Full structured output. The Copilot reads only from here, never from a
    # calculation of its own.
    payload: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="model_outputs")

    __table_args__ = (
        Index("ix_model_outputs_user_model_date", "user_id", "model_name", "as_of_date"),
    )

    def __repr__(self) -> str:
        return f"<ModelOutput {self.model_name} user={self.user_id} {self.as_of_date}>"
