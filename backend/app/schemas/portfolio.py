"""Portfolio, holding and transaction payloads."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssetClass, TransactionType


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    asset_class: AssetClass
    sector: str | None
    price_source: str | None = None


class HoldingCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: float = Field(gt=0)
    average_price: float = Field(gt=0)
    purchase_date: date | None = None


class HoldingUpdate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    average_price: float | None = Field(default=None, gt=0)
    purchase_date: date | None = None


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    asset_class: AssetClass
    sector: str | None
    quantity: float
    average_price: float
    purchase_date: date | None

    # Valuation, filled in by the service from the latest market price.
    current_price: float | None = None
    market_value: float | None = None
    cost_basis: float | None = None
    unrealized_gain: float | None = None
    unrealized_gain_pct: float | None = None
    weight: float | None = None


class TransactionCreate(BaseModel):
    transaction_type: TransactionType
    date: date
    symbol: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)
    value: float | None = Field(default=None, gt=0)
    fees: float = Field(default=0.0, ge=0)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_type: TransactionType
    date: date
    symbol: str | None
    quantity: float | None
    price: float | None
    value: float
    fees: float


class AllocationSlice(BaseModel):
    label: str
    value: float
    weight: float


class PortfolioSummary(BaseModel):
    """The Overview page payload."""

    total_value: float
    total_cost: float
    unrealized_gain: float
    unrealized_gain_pct: float
    n_holdings: int
    n_sectors: int
    as_of: date | None
    allocation_by_class: list[AllocationSlice]
    allocation_by_sector: list[AllocationSlice]
    top_holdings: list[HoldingOut]


# --------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------

class ImportRowError(BaseModel):
    """One rejected CSV row, reported back with the reason."""

    row_number: int
    field: str | None
    value: str | None
    message: str


class ImportResult(BaseModel):
    """Outcome of a CSV import.

    Imports are all-or-nothing by default: a file with any invalid row is
    rejected entirely rather than leaving the portfolio half-loaded and
    silently wrong.
    """

    accepted: bool
    rows_read: int
    rows_imported: int
    holdings_created: int
    holdings_updated: int
    errors: list[ImportRowError]
    warnings: list[str] = []
