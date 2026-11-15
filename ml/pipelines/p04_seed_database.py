"""Stage 04 — load the asset universe and price panel into PostgreSQL.

Market data is reference data: it belongs to no user and is shared by every
account. This stage is idempotent, so re-running it after a pipeline change
refreshes prices without duplicating rows.

Run:  python -m ml.pipelines.p04_seed_database [--reset]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, func, insert, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Asset, MarketPrice  # noqa: E402

from .common import PROCESSED_DIR, Stage, get_logger, load_universe, write_report  # noqa: E402

log = get_logger("seed")

CHUNK_SIZE = 20_000


def seed_assets(session) -> dict[str, int]:
    """Insert or update one row per asset; return a symbol -> id map."""
    universe = load_universe()
    panel = pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")
    sources = (
        pd.read_parquet(PROCESSED_DIR / "prices.parquet")[["symbol", "source"]]
        .drop_duplicates()
        .set_index("symbol")["source"]
        .to_dict()
    )

    existing = {a.symbol: a for a in session.scalars(select(Asset)).all()}
    created = updated = 0

    for _, row in universe.iterrows():
        symbol = row["symbol"]
        # Only seed assets the panel can actually price.
        if symbol not in panel.columns:
            continue

        fields = {
            "name": row["name"],
            "asset_class": row["asset_class"],
            "sector": row["sector"] or None,
            "status": row["status"],
            "price_source": sources.get(symbol),
            "note": (row["note"] or None) if "note" in row else None,
        }

        if symbol in existing:
            for key, value in fields.items():
                setattr(existing[symbol], key, value)
            updated += 1
        else:
            session.add(Asset(symbol=symbol, **fields))
            created += 1

    session.commit()
    log.info("  assets: %d created, %d updated", created, updated)
    return {a.symbol: a.id for a in session.scalars(select(Asset)).all()}


def seed_prices(session, asset_ids: dict[str, int], reset: bool) -> int:
    """Load the adjusted price panel into market_prices."""
    panel = pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")

    long = (
        panel.stack()
        .rename("close")
        .reset_index()
        .rename(columns={"level_0": "date", "level_1": "symbol"})
    )
    long.columns = ["date", "symbol", "close"]
    long = long[long["symbol"].isin(asset_ids) & (long["close"] > 0)]
    long["asset_id"] = long["symbol"].map(asset_ids)
    long["date"] = pd.to_datetime(long["date"]).dt.date

    if reset:
        session.execute(delete(MarketPrice))
        session.commit()
        log.info("  cleared existing prices")

    already = session.scalar(select(MarketPrice).exists().select())
    if already and not reset:
        log.info("  prices already loaded; pass --reset to reload")
        return 0

    records = long[["asset_id", "date", "close"]].to_dict("records")
    for start in range(0, len(records), CHUNK_SIZE):
        chunk = records[start : start + CHUNK_SIZE]
        session.execute(insert(MarketPrice), chunk)
        session.commit()
        log.info("    %d / %d rows", start + len(chunk), len(records))

    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed assets and market prices")
    parser.add_argument("--reset", action="store_true", help="delete and reload all prices")
    args = parser.parse_args()

    report: dict = {}
    with SessionLocal() as session:
        with Stage(log, "seed assets"):
            asset_ids = seed_assets(session)
            report["assets"] = len(asset_ids)

        with Stage(log, "seed market prices"):
            inserted = seed_prices(session, asset_ids, args.reset)
            report["prices_inserted"] = inserted

        with Stage(log, "verify"):
            report["db_assets"] = session.scalar(select(func.count()).select_from(Asset))
            report["db_prices"] = session.scalar(select(func.count()).select_from(MarketPrice))
            span = session.execute(
                select(func.min(MarketPrice.date), func.max(MarketPrice.date))
            ).one()
            report["price_span"] = [str(span[0]), str(span[1])]
            log.info(
                "  %d assets, %d price rows, %s → %s",
                report["db_assets"], report["db_prices"], span[0], span[1],
            )

    write_report("database_seed", report)


if __name__ == "__main__":
    main()
