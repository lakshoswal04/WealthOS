"""Portfolio composition, holdings, transactions and CSV import."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Asset, AssetStatus, Holding, Transaction
from app.schemas.portfolio import (
    AssetOut, HoldingCreate, HoldingOut, HoldingUpdate, ImportResult,
    PortfolioSummary, TransactionCreate, TransactionOut,
)
from app.services import portfolio_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

MAX_UPLOAD_BYTES = 2 * 1024 * 1024


@router.get("", response_model=PortfolioSummary)
def get_portfolio(user: CurrentUser, db: DbSession) -> PortfolioSummary:
    """Total value, gain and allocation breakdowns for the Overview page."""
    return portfolio_service.build_summary(db, user)


@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(user: CurrentUser, db: DbSession) -> list[HoldingOut]:
    """Every holding, priced, with its unrealised gain and portfolio weight."""
    return portfolio_service.value_holdings(db, portfolio_service.get_holdings(db, user))


@router.post("/holdings", response_model=HoldingOut, status_code=status.HTTP_201_CREATED)
def create_holding(payload: HoldingCreate, user: CurrentUser, db: DbSession) -> HoldingOut:
    """Add a position, merging into an existing one for the same asset."""
    asset = db.scalar(select(Asset).where(Asset.symbol == payload.symbol.upper()))
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{payload.symbol}' is not a supported symbol",
        )
    if asset.status != AssetStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{asset.symbol}' is {asset.status} and cannot be held",
        )

    holding, _ = portfolio_service.upsert_holding(
        db, user, asset, payload.quantity, payload.average_price, payload.purchase_date
    )
    db.commit()
    db.refresh(holding)
    priced = portfolio_service.value_holdings(db, [holding])
    return priced[0]


@router.patch("/holdings/{holding_id}", response_model=HoldingOut)
def update_holding(
    holding_id: int, payload: HoldingUpdate, user: CurrentUser, db: DbSession
) -> HoldingOut:
    # Scoped by user_id as well as id, so guessing another user's holding id
    # returns 404 rather than their data.
    holding = db.scalar(
        select(Holding).where(Holding.id == holding_id, Holding.user_id == user.id)
    )
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(holding, field, value)
    db.commit()
    db.refresh(holding)
    return portfolio_service.value_holdings(db, [holding])[0]


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, user: CurrentUser, db: DbSession) -> None:
    holding = db.scalar(
        select(Holding).where(Holding.id == holding_id, Holding.user_id == user.id)
    )
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    db.delete(holding)
    db.commit()


@router.post("/import", response_model=ImportResult)
async def import_portfolio(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    replace_existing: bool = Query(
        default=False, description="Delete current holdings before importing"
    ),
) -> ImportResult:
    """Import holdings from a CSV.

    Expected header: ``symbol,quantity,average_price`` with optional
    ``asset_type`` and ``purchase_date``. The whole file is validated before
    anything is written; any invalid row rejects the entire import.
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a .csv file"
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    return portfolio_service.import_holdings_csv(db, user, content, replace_existing)


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    user: CurrentUser, db: DbSession, limit: int = Query(default=200, le=1000)
) -> list[TransactionOut]:
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
    ).all()
    return [
        TransactionOut(
            id=t.id, transaction_type=t.transaction_type, date=t.date,
            symbol=t.asset.symbol if t.asset else None,
            quantity=t.quantity, price=t.price, value=t.value, fees=t.fees,
        )
        for t in rows
    ]


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate, user: CurrentUser, db: DbSession
) -> TransactionOut:
    """Record a trade or an external cash flow."""
    asset = None
    if payload.symbol:
        asset = db.scalar(select(Asset).where(Asset.symbol == payload.symbol.upper()))
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{payload.symbol}' is not a supported symbol",
            )

    is_trade = payload.transaction_type in ("buy", "sell", "dividend")
    if is_trade and asset is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A {payload.transaction_type} transaction requires a symbol",
        )
    if not is_trade and asset is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A {payload.transaction_type} is an external cash flow and takes no symbol",
        )

    value = payload.value
    if value is None:
        if payload.quantity is None or payload.price is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide either a value, or both a quantity and a price",
            )
        value = payload.quantity * payload.price

    transaction = Transaction(
        user_id=user.id, asset_id=asset.id if asset else None,
        transaction_type=payload.transaction_type, date=payload.date,
        quantity=payload.quantity, price=payload.price, value=value, fees=payload.fees,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return TransactionOut(
        id=transaction.id, transaction_type=transaction.transaction_type,
        date=transaction.date, symbol=asset.symbol if asset else None,
        quantity=transaction.quantity, price=transaction.price,
        value=transaction.value, fees=transaction.fees,
    )


@router.get("/assets", response_model=list[AssetOut], tags=["reference"])
def list_assets(db: DbSession, asset_class: str | None = None) -> list[Asset]:
    """The investable universe, for symbol pickers and import validation."""
    query = select(Asset).where(Asset.status == AssetStatus.ACTIVE).order_by(Asset.symbol)
    if asset_class:
        query = query.where(Asset.asset_class == asset_class)
    return list(db.scalars(query).all())
