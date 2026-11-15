"""Point-in-time portfolio state.

Snapshots are the time series every model is trained on. One row records what
a portfolio looked like on one date: its value, how it was allocated, how it
had performed, and how concentrated it was.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, Float, ForeignKey, Index, Integer, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PortfolioSnapshot(Base):
    """A user's portfolio state on one date."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # --- value and flows ---
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    invested_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Net external cash in during the period. Required to separate investment
    # performance from money added; see wealthos_core.portfolio.
    net_contribution: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # --- allocation (fractions of total value) ---
    equity_allocation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    etf_allocation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    debt_allocation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gold_allocation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cash_allocation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # --- performance, time-weighted ---
    period_return: Mapped[float | None] = mapped_column(Float)
    cumulative_return: Mapped[float | None] = mapped_column(Float)
    volatility: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    current_drawdown: Mapped[float | None] = mapped_column(Float)

    # --- concentration ---
    hhi: Mapped[float | None] = mapped_column(Float)
    sector_hhi: Mapped[float | None] = mapped_column(Float)
    top_holding_weight: Mapped[float | None] = mapped_column(Float)
    n_holdings: Mapped[int | None] = mapped_column(Integer)
    n_sectors: Mapped[int | None] = mapped_column(Integer)

    # --- behaviour ---
    turnover: Mapped[float | None] = mapped_column(Float)
    n_transactions: Mapped[int | None] = mapped_column(Integer)

    # Per-symbol weights, kept as JSONB so the shape can vary per user without
    # a sparse column per asset.
    allocations: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped["User"] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="user_date"),
        Index("ix_snapshots_user_date", "user_id", "date"),
        CheckConstraint("total_value >= 0", name="value_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Snapshot user={self.user_id} {self.date} value={self.total_value:.0f}>"
