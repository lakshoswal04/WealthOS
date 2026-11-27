"""Autopilot: a model-run paper sleeve per user, and the record of every run.

The sleeve is Autopilot's own sub-account inside the user's paper account:
``sleeve`` holds the shares it bought and ``sleeve_cash`` the cash it has not
invested. Paper positions merge by symbol, so a stock the user also trades
by hand stays theirs; Autopilot only ever sells shares its ledger says it
owns.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AutopilotSettings(Base, TimestampMixin):
    __tablename__ = "autopilot_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    budget: Mapped[float] = mapped_column(Float, default=100_000.0, nullable=False)
    cadence_sessions: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    avoid_symbols: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    avoid_sectors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    sleeve: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sleeve_cash: Mapped[float | None] = mapped_column(Float)
    last_run_on: Mapped[date | None] = mapped_column(Date)


class AutopilotRun(Base):
    __tablename__ = "autopilot_runs"
    __table_args__ = (UniqueConstraint("user_id", "run_on", name="uq_autopilot_runs_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    run_on: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)          # auto | manual
    status: Mapped[str] = mapped_column(String(16), nullable=False)        # done | partial | failed
    regime: Mapped[dict | None] = mapped_column(JSONB)
    target: Mapped[list | None] = mapped_column(JSONB)
    orders: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[list | None] = mapped_column(JSONB)
    sleeve_value: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
