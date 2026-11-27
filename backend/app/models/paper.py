"""Paper trading: a virtual cash account, its orders and open positions.

Nothing here touches a real broker. Orders fill against the same delayed or
simulated prices the screens show, and every row is scoped to its user the
same way holdings are.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class PaperAccount(Base, TimestampMixin):
    """One virtual trading account per user."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    cash: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    starting_cash: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(16, 2), default=0, nullable=False)

    user: Mapped["User"] = relationship()


class PaperOrder(Base):
    """An order, from placement to fill, cancellation or rejection."""

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # equity | option
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    # The tradable name: "RELIANCE", or "NIFTY 01 DEC 25900 CE".
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    underlying: Mapped[str] = mapped_column(String(32), nullable=False)
    option_type: Mapped[str | None] = mapped_column(String(2))
    strike: Mapped[float | None] = mapped_column(Float)
    expiry: Mapped[date | None] = mapped_column(Date)

    side: Mapped[str] = mapped_column(String(4), nullable=False)          # buy | sell
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)        # units, not lots
    order_type: Mapped[str] = mapped_column(String(8), nullable=False)    # market | limit
    limit_price: Mapped[float | None] = mapped_column(Float)
    # delivery (equity held overnight) | intraday | nrml (F&O)
    product: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)       # open|filled|cancelled|rejected
    fill_price: Mapped[float | None] = mapped_column(Float)
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    # Where the order came from: manual, ai, autopilot, strategy:<id>
    tag: Mapped[str] = mapped_column(String(48), default="manual", nullable=False)
    price_source: Mapped[str | None] = mapped_column(String(12))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_paper_orders_user_created", "user_id", "created_at"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("side IN ('buy', 'sell')", name="side_valid"),
    )


class PaperPosition(Base, TimestampMixin):
    """A net open position. Quantity is signed: negative is short (options only)."""

    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    underlying: Mapped[str] = mapped_column(String(32), nullable=False)
    option_type: Mapped[str | None] = mapped_column(String(2))
    strike: Mapped[float | None] = mapped_column(Float)
    expiry: Mapped[date | None] = mapped_column(Date)
    product: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tag: Mapped[str] = mapped_column(String(48), default="manual", nullable=False)
    # Margin held against a short option position, from Upstox's margin API
    # at the time of the fill, scaled down as the short is reduced.
    margin_blocked: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "product", name="uq_paper_positions_user_symbol_product"),
    )
