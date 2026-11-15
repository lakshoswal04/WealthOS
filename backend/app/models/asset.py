"""Tradeable assets and their historical prices.

Market data is deliberately kept in its own tables with no foreign key to
users. It is reference data shared by everyone, and conflating it with user
financial records is what makes portfolio systems leak data between accounts.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, Float, ForeignKey, Index, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import AssetClass, AssetStatus

if TYPE_CHECKING:
    from app.models.holding import Holding
    from app.models.transaction import Transaction


class Asset(Base, TimestampMixin):
    """A security the platform can price and analyse."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(String(20), nullable=False, index=True)
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[AssetStatus] = mapped_column(String(20), default=AssetStatus.ACTIVE, nullable=False)

    # Where this asset's prices come from, carried through to the UI so a
    # modelled series is never mistaken for an observed one.
    price_source: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(512))

    holdings: Mapped[list["Holding"]] = relationship(back_populates="asset")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="asset")
    prices: Mapped[list["MarketPrice"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Asset {self.symbol} ({self.asset_class})>"


class MarketPrice(Base):
    """One daily price observation for one asset.

    ``close`` is corporate-action adjusted. The Kaggle source is not adjusted,
    which would misreport a 1:1 bonus as a 50% crash, so prices are loaded
    from the adjusted panel built by ml/pipelines/p03_build_prices.
    """

    __tablename__ = "market_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)

    asset: Mapped["Asset"] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="asset_date"),
        # The dominant query is "all prices for these assets over this range".
        Index("ix_market_prices_asset_date", "asset_id", "date"),
        Index("ix_market_prices_date", "date"),
        CheckConstraint("close > 0", name="close_positive"),
    )

    def __repr__(self) -> str:
        return f"<MarketPrice asset={self.asset_id} {self.date} {self.close}>"
