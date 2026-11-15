"""Historical portfolio activity."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import TransactionType

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.user import User


class Transaction(Base, TimestampMixin):
    """One portfolio event: a trade, a dividend, or an external cash flow.

    Contributions and withdrawals carry no asset. They are what makes the
    time-weighted return calculation possible: without recording external
    cash flows, a deposit is indistinguishable from investment gain.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), index=True
    )

    transaction_type: Mapped[TransactionType] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="transactions")
    asset: Mapped["Asset"] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "date"),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
        CheckConstraint("price IS NULL OR price > 0", name="price_positive"),
        CheckConstraint("fees >= 0", name="fees_non_negative"),
        # A trade must name an asset; a cash flow must not.
        CheckConstraint(
            "(transaction_type IN ('buy','sell','dividend') AND asset_id IS NOT NULL) "
            "OR (transaction_type IN ('contribution','withdrawal') AND asset_id IS NULL)",
            name="asset_required_for_trades",
        ),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.transaction_type} user={self.user_id} {self.date}>"
