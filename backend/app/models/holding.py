"""Current positions held by a user."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.user import User


class Holding(Base, TimestampMixin):
    """A user's current position in one asset.

    One row per user-asset pair: buying more of something already held
    updates the quantity and the weighted average cost rather than creating a
    second row, so portfolio weights cannot double-count.
    """

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    average_price: Mapped[float] = mapped_column(Float, nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date)

    user: Mapped["User"] = relationship(back_populates="holdings")
    asset: Mapped["Asset"] = relationship(back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("user_id", "asset_id", name="user_asset"),
        Index("ix_holdings_user_asset", "user_id", "asset_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("average_price > 0", name="average_price_positive"),
    )

    @property
    def cost_basis(self) -> float:
        return float(self.quantity) * float(self.average_price)

    def __repr__(self) -> str:
        return f"<Holding user={self.user_id} asset={self.asset_id} qty={self.quantity}>"
