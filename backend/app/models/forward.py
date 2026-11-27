"""Forward test of the swing models: scores frozen on the day they were made.

A backtest, however careful, is written knowing how history turned out. The
forward test is not: every session, each model's scores for that date are
recorded once, with the model version that produced them, and never
recomputed. Portfolio performance is then replayed from these frozen scores
against prices that arrived later. It is system-wide (the same for every
user), like a published track record.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ForwardScore(Base):
    __tablename__ = "forward_scores"
    __table_args__ = (UniqueConstraint("model_id", "signal_date", name="uq_forward_scores_model_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False)
