"""Portfolio composition, valuation and CSV ingestion."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Asset, AssetStatus, Holding, Transaction, TransactionType, User
from app.schemas.portfolio import (
    AllocationSlice, HoldingOut, ImportResult, ImportRowError, PortfolioSummary,
)
from app.services.market_service import market_cache

# The import template the UI documents and the Import page accepts.
REQUIRED_CSV_COLUMNS = {"symbol", "quantity", "average_price"}
OPTIONAL_CSV_COLUMNS = {"asset_type", "purchase_date"}
MAX_IMPORT_ROWS = 5_000


# Ratios outside this band between an entered cost basis and the adjusted
# market price on the stated purchase date are worth flagging.
COST_BASIS_PLAUSIBLE_BAND = (0.67, 1.5)

# Common Indian corporate-action factors. A cost-basis ratio sitting on one of
# these is almost certainly a bonus or split rather than a typing error.
CORPORATE_ACTION_FACTORS = (2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 0.2, 0.1)


def _cost_basis_warning(
    symbol: str, entered_price: float, purchase_date: date | None,
    price_on_date: float | None, row_number: int,
) -> str | None:
    """Flag a cost basis that cannot be reconciled with the historical price.

    Prices in this platform are adjusted for splits and bonuses, but an
    investor naturally enters the rupee price they actually paid. After a 1:1
    bonus the two differ by a factor of two, and the portfolio would report a
    50% loss that never happened. HDFCBANK is a live example: its genuine
    November 2021 price of around 1480 is 2.03x its adjusted price, because
    of the 1:1 bonus in 2025.

    This warns rather than silently rescaling, because the same symptom can
    equally mean a mistyped price or a wrong purchase date, and guessing
    which would corrupt the user's records.
    """
    if purchase_date is None or not price_on_date or price_on_date <= 0:
        return None

    ratio = entered_price / price_on_date
    low, high = COST_BASIS_PLAUSIBLE_BAND
    if low <= ratio <= high:
        return None

    nearest = min(CORPORATE_ACTION_FACTORS, key=lambda f: abs(ratio - f))
    if abs(ratio - nearest) / nearest < 0.08:
        return (
            f"Row {row_number}: the cost basis for '{symbol}' is {ratio:.2f}x the "
            f"split-adjusted price on {purchase_date} (Rs {price_on_date:,.2f}). "
            f"That is close to a {nearest:g}:1 corporate action. Prices here are "
            f"adjusted for splits and bonuses, so enter the adjusted cost "
            f"(about Rs {entered_price / nearest:,.2f}) and the adjusted quantity, "
            f"or this holding's gain will be misreported."
        )
    return (
        f"Row {row_number}: the cost basis for '{symbol}' (Rs {entered_price:,.2f}) is "
        f"{ratio:.2f}x the adjusted price on {purchase_date} (Rs {price_on_date:,.2f}). "
        f"Check the price and the purchase date."
    )


# --------------------------------------------------------------------------
# Composition and valuation
# --------------------------------------------------------------------------

def get_holdings(db: Session, user: User) -> list[Holding]:
    """Every holding for one user, with its asset eagerly loaded."""
    return list(
        db.scalars(
            select(Holding)
            .options(joinedload(Holding.asset))
            .where(Holding.user_id == user.id)
            .order_by(Holding.id)
        ).all()
    )


def value_holdings(db: Session, holdings: list[Holding]) -> list[HoldingOut]:
    """Price each holding and compute its gain and portfolio weight."""
    if not holdings:
        return []

    symbols = [h.asset.symbol for h in holdings]
    prices = market_cache.latest_prices(db, symbols)

    rows: list[HoldingOut] = []
    for holding in holdings:
        symbol = holding.asset.symbol
        price = prices.get(symbol)
        price = float(price) if price is not None and pd.notna(price) else None

        market_value = price * float(holding.quantity) if price is not None else None
        cost_basis = float(holding.quantity) * float(holding.average_price)
        gain = market_value - cost_basis if market_value is not None else None

        rows.append(
            HoldingOut(
                id=holding.id,
                symbol=symbol,
                name=holding.asset.name,
                asset_class=holding.asset.asset_class,
                sector=holding.asset.sector,
                quantity=float(holding.quantity),
                average_price=float(holding.average_price),
                purchase_date=holding.purchase_date,
                current_price=price,
                market_value=market_value,
                cost_basis=cost_basis,
                unrealized_gain=gain,
                unrealized_gain_pct=(gain / cost_basis) if gain is not None and cost_basis else None,
            )
        )

    total = sum(r.market_value for r in rows if r.market_value is not None)
    for row in rows:
        row.weight = (row.market_value / total) if (total and row.market_value is not None) else None
    return rows


def build_summary(db: Session, user: User) -> PortfolioSummary:
    """The Overview payload: value, gain and allocation breakdowns."""
    priced = value_holdings(db, get_holdings(db, user))

    if not priced:
        return PortfolioSummary(
            total_value=0.0, total_cost=0.0, unrealized_gain=0.0, unrealized_gain_pct=0.0,
            n_holdings=0, n_sectors=0, as_of=market_cache.latest_date(db),
            allocation_by_class=[], allocation_by_sector=[], top_holdings=[],
        )

    total_value = sum(r.market_value or 0.0 for r in priced)
    total_cost = sum(r.cost_basis or 0.0 for r in priced)
    gain = total_value - total_cost

    def group(attribute: str) -> list[AllocationSlice]:
        totals: dict[str, float] = {}
        for row in priced:
            if row.market_value is None:
                continue
            key = str(getattr(row, attribute) or "Unknown")
            totals[key] = totals.get(key, 0.0) + row.market_value
        return [
            AllocationSlice(label=k, value=v, weight=(v / total_value) if total_value else 0.0)
            for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        ]

    by_sector = group("sector")

    return PortfolioSummary(
        total_value=total_value,
        total_cost=total_cost,
        unrealized_gain=gain,
        unrealized_gain_pct=(gain / total_cost) if total_cost else 0.0,
        n_holdings=len(priced),
        n_sectors=len(by_sector),
        as_of=market_cache.latest_date(db),
        allocation_by_class=group("asset_class"),
        allocation_by_sector=by_sector,
        top_holdings=sorted(
            priced, key=lambda r: r.market_value or 0.0, reverse=True
        )[:10],
    )


def portfolio_weights(db: Session, user: User) -> pd.Series:
    """Current weight per symbol, used by the risk and health engines."""
    priced = value_holdings(db, get_holdings(db, user))
    values = {r.symbol: r.market_value for r in priced if r.market_value}
    series = pd.Series(values, dtype="float64")
    total = series.sum()
    return series / total if total > 0 else series


# --------------------------------------------------------------------------
# Holdings maintenance
# --------------------------------------------------------------------------

def upsert_holding(
    db: Session, user: User, asset: Asset, quantity: float,
    average_price: float, purchase_date: date | None,
) -> tuple[Holding, bool]:
    """Add a position, or merge into an existing one.

    Merging combines the two lots at their weighted average cost. Appending a
    second row for the same asset instead would double-count the position in
    every weight and concentration figure.
    """
    existing = db.scalar(
        select(Holding).where(Holding.user_id == user.id, Holding.asset_id == asset.id)
    )
    if existing is None:
        holding = Holding(
            user_id=user.id, asset_id=asset.id, quantity=quantity,
            average_price=average_price, purchase_date=purchase_date,
        )
        db.add(holding)
        return holding, True

    combined_quantity = float(existing.quantity) + quantity
    combined_cost = (
        float(existing.quantity) * float(existing.average_price) + quantity * average_price
    )
    existing.quantity = combined_quantity
    existing.average_price = combined_cost / combined_quantity
    if purchase_date and (existing.purchase_date is None or purchase_date < existing.purchase_date):
        existing.purchase_date = purchase_date
    return existing, False


# --------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------

def _parse_date(value: str) -> date | None:
    """Accept the date formats an Indian retail investor is likely to paste."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format: {text!r}")


def import_holdings_csv(
    db: Session, user: User, content: bytes, replace_existing: bool = False
) -> ImportResult:
    """Validate and load a holdings CSV.

    Validation runs over the whole file before anything is written. A file
    with any invalid row is rejected in full, because a partially imported
    portfolio produces analytics that look complete and are wrong.
    """
    errors: list[ImportRowError] = []
    warnings: list[str] = []

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin1")
            warnings.append("File was not UTF-8; it was decoded as latin-1.")
        except UnicodeDecodeError:
            return ImportResult(
                accepted=False, rows_read=0, rows_imported=0, holdings_created=0,
                holdings_updated=0,
                errors=[ImportRowError(row_number=0, field=None, value=None,
                                       message="File could not be decoded as text.")],
            )

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return ImportResult(
            accepted=False, rows_read=0, rows_imported=0, holdings_created=0,
            holdings_updated=0,
            errors=[ImportRowError(row_number=0, field=None, value=None,
                                   message="File is empty or has no header row.")],
        )

    headers = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = REQUIRED_CSV_COLUMNS - headers
    if missing:
        return ImportResult(
            accepted=False, rows_read=0, rows_imported=0, holdings_created=0,
            holdings_updated=0,
            errors=[ImportRowError(
                row_number=0, field=",".join(sorted(missing)), value=None,
                message=(f"Missing required column(s): {', '.join(sorted(missing))}. "
                         f"Expected header: {', '.join(sorted(REQUIRED_CSV_COLUMNS))}"
                         f"[, {', '.join(sorted(OPTIONAL_CSV_COLUMNS))}]"),
            )],
        )

    known_assets = {
        a.symbol.upper(): a
        for a in db.scalars(select(Asset).where(Asset.status == AssetStatus.ACTIVE)).all()
    }

    # Loaded once; used to sanity-check each row's cost basis against the
    # adjusted price on its stated purchase date.
    price_panel = market_cache.panel(db)

    parsed: list[dict] = []
    seen_symbols: dict[str, int] = {}
    rows_read = 0

    for line_number, raw in enumerate(reader, start=2):  # row 1 is the header
        normalised = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(normalised.values()):
            continue  # skip blank lines
        rows_read += 1

        if rows_read > MAX_IMPORT_ROWS:
            errors.append(ImportRowError(
                row_number=line_number, field=None, value=None,
                message=f"File exceeds the {MAX_IMPORT_ROWS}-row limit.",
            ))
            break

        symbol = normalised.get("symbol", "").upper()
        if not symbol:
            errors.append(ImportRowError(row_number=line_number, field="symbol",
                                         value=None, message="Symbol is required."))
            continue

        asset = known_assets.get(symbol)
        if asset is None:
            errors.append(ImportRowError(
                row_number=line_number, field="symbol", value=symbol,
                message=f"'{symbol}' is not a supported symbol in this platform's universe.",
            ))
            continue

        try:
            quantity = float(normalised.get("quantity", ""))
        except ValueError:
            errors.append(ImportRowError(
                row_number=line_number, field="quantity",
                value=normalised.get("quantity"), message="Quantity must be a number.",
            ))
            continue
        if quantity <= 0:
            errors.append(ImportRowError(
                row_number=line_number, field="quantity", value=str(quantity),
                message="Quantity must be greater than zero.",
            ))
            continue

        try:
            average_price = float(normalised.get("average_price", ""))
        except ValueError:
            errors.append(ImportRowError(
                row_number=line_number, field="average_price",
                value=normalised.get("average_price"),
                message="Average price must be a number.",
            ))
            continue
        if average_price <= 0:
            errors.append(ImportRowError(
                row_number=line_number, field="average_price", value=str(average_price),
                message="Average price must be greater than zero.",
            ))
            continue

        try:
            purchase_date = _parse_date(normalised.get("purchase_date", ""))
        except ValueError as exc:
            errors.append(ImportRowError(
                row_number=line_number, field="purchase_date",
                value=normalised.get("purchase_date"), message=str(exc),
            ))
            continue

        if purchase_date and purchase_date > date.today():
            errors.append(ImportRowError(
                row_number=line_number, field="purchase_date", value=str(purchase_date),
                message="Purchase date is in the future.",
            ))
            continue

        declared = normalised.get("asset_type", "")
        if declared and declared.lower() != str(asset.asset_class).lower():
            warnings.append(
                f"Row {line_number}: '{symbol}' is classified as "
                f"'{asset.asset_class}', not '{declared}'. The platform's "
                "classification was used."
            )

        price_on_date = None
        if purchase_date is not None and symbol in price_panel.columns:
            historical = price_panel[symbol].asof(pd.Timestamp(purchase_date))
            if pd.notna(historical):
                price_on_date = float(historical)

        basis_warning = _cost_basis_warning(
            symbol, average_price, purchase_date, price_on_date, line_number
        )
        if basis_warning:
            warnings.append(basis_warning)

        if symbol in seen_symbols:
            warnings.append(
                f"Row {line_number}: '{symbol}' also appears on row "
                f"{seen_symbols[symbol]}; the two lots were combined at their "
                "weighted average cost."
            )
        else:
            seen_symbols[symbol] = line_number

        parsed.append({
            "asset": asset, "quantity": quantity,
            "average_price": average_price, "purchase_date": purchase_date,
        })

    if errors:
        return ImportResult(
            accepted=False, rows_read=rows_read, rows_imported=0,
            holdings_created=0, holdings_updated=0, errors=errors, warnings=warnings,
        )
    if not parsed:
        return ImportResult(
            accepted=False, rows_read=rows_read, rows_imported=0, holdings_created=0,
            holdings_updated=0,
            errors=[ImportRowError(row_number=0, field=None, value=None,
                                   message="No valid holdings found in the file.")],
            warnings=warnings,
        )

    if replace_existing:
        for holding in get_holdings(db, user):
            db.delete(holding)
        db.flush()

    # Collapse repeated symbols before touching the database. The session
    # runs with autoflush off, so a second upsert for the same asset would
    # not see the first one still pending and would violate the unique
    # (user_id, asset_id) constraint. Merging here also makes the weighted
    # average cost explicit, which is what the warning above promises.
    merged: dict[int, dict] = {}
    for record in parsed:
        asset = record["asset"]
        if asset.id not in merged:
            merged[asset.id] = dict(record)
            continue

        running = merged[asset.id]
        total_quantity = running["quantity"] + record["quantity"]
        total_cost = (
            running["quantity"] * running["average_price"]
            + record["quantity"] * record["average_price"]
        )
        running["quantity"] = total_quantity
        running["average_price"] = total_cost / total_quantity
        # Keep the earliest purchase date across the merged lots.
        dates = [d for d in (running["purchase_date"], record["purchase_date"]) if d]
        running["purchase_date"] = min(dates) if dates else None

    created = updated = 0
    transactions_recorded = 0
    for record in merged.values():
        _, is_new = upsert_holding(
            db, user, record["asset"], record["quantity"],
            record["average_price"], record["purchase_date"],
        )
        db.flush()  # make the new row visible to the next lookup
        created += int(is_new)
        updated += int(not is_new)

        # A CSV row carrying a purchase date is a record of a purchase, so
        # record it as one.
        #
        # Until Phase 4 nothing wrote to `transactions` except the explicit
        # POST /transactions endpoint, so for anyone who onboarded by CSV --
        # the documented path, and the one the demonstration uses -- the
        # table was empty. That had consequences beyond a missing feature:
        # behavioural profiling fell back to the reconstruction, which holds
        # quantities fixed and so reports zero turnover, pushing every live
        # user towards the passive clusters whatever they actually do.
        #
        # Only rows with a date are recorded. Inventing one would put a
        # fabricated event in the user's own history, and a holding without a
        # purchase date is a position of unknown vintage, not a purchase made
        # today.
        if record["purchase_date"] is not None:
            db.add(Transaction(
                user_id=user.id,
                asset_id=record["asset"].id,
                transaction_type=TransactionType.BUY,
                date=record["purchase_date"],
                quantity=record["quantity"],
                price=record["average_price"],
                value=record["quantity"] * record["average_price"],
                fees=0.0,
            ))
            transactions_recorded += 1
    db.commit()

    if transactions_recorded:
        warnings.append(
            f"Recorded {transactions_recorded} purchase "
            f"{'transaction' if transactions_recorded == 1 else 'transactions'} "
            "from the dated rows, so behavioural analysis can use your own "
            "history rather than inferring it."
        )
    elif created or updated:
        warnings.append(
            "No purchase dates were given, so no transaction history was "
            "recorded. Behavioural features will be inferred from price "
            "history, which cannot see trading activity."
        )

    return ImportResult(
        accepted=True, rows_read=rows_read, rows_imported=len(parsed),
        holdings_created=created, holdings_updated=updated,
        errors=[], warnings=warnings,
    )
