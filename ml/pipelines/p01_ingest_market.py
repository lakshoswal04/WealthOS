"""Stage 01 — ingest the Kaggle NSE dataset into validated parquet.

Reads the per-stock SCRIP files and the INDEX files, standardises their
schemas, runs data-quality checks and writes:

    data/raw/nse_equity.parquet     one row per symbol-date
    data/raw/nse_index.parquet      one row per index-date
    ml/reports/ingest_quality.json  the quality findings

Outliers are flagged, never dropped. An extreme move in Indian equity history
is usually a real event -- a crash, a split, a corporate action -- and
deleting it would quietly bias every volatility and drawdown figure computed
downstream.

Run:  python -m ml.pipelines.p01_ingest_market [--limit N]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .common import (
    KAGGLE_NSE_DIR,
    RAW_DIR,
    PipelineError,
    Stage,
    clean_column_names,
    clean_numeric,
    describe_frame,
    find_column,
    get_logger,
    load_universe,
    read_tabular,
    write_report,
)

log = get_logger("ingest")

# Columns we standardise onto, and the aliases seen across dataset revisions.
COLUMN_ALIASES = {
    "date": ["date", "datetime", "timestamp", "tradedate"],
    "symbol": ["symbol", "ticker", "security", "stock"],
    "open": ["open", "openprice", "open_price"],
    "high": ["high", "highprice", "high_price"],
    "low": ["low", "lowprice", "low_price"],
    "close": ["close", "closeprice", "close_price", "ltp"],
    "volume": ["volume", "sharestraded", "qty", "quantity"],
}


def _standardise(df: pd.DataFrame, fallback_symbol: str | None = None) -> pd.DataFrame | None:
    """Map a raw file onto the canonical schema, or return None if not price data."""
    frame = clean_column_names(df)

    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        found = find_column(frame, aliases)
        if found is not None:
            resolved[canonical] = found

    # A price file must at minimum carry a date and a closing price.
    if "date" not in resolved or "close" not in resolved:
        return None

    out = pd.DataFrame(index=frame.index)
    out["date"] = pd.to_datetime(frame[resolved["date"]], errors="coerce")

    if "symbol" in resolved:
        out["symbol"] = frame[resolved["symbol"]].astype(str).str.strip().str.upper()
    elif fallback_symbol is not None:
        out["symbol"] = fallback_symbol
    else:
        return None

    for field in ("open", "high", "low", "close", "volume"):
        out[field] = clean_numeric(frame[resolved[field]]) if field in resolved else np.nan

    # Early index history records only the closing level and writes 0.0 into
    # open/high/low. Those zeros are absent data, not a price of zero rupees,
    # and leaving them in place would corrupt any intraday range calculation
    # and make the OHLC consistency check meaningless.
    for field in ("open", "high", "low", "close"):
        out.loc[out[field] <= 0, field] = np.nan

    # Negative traded volume is impossible; treat it as unrecorded.
    out.loc[out["volume"] < 0, "volume"] = np.nan

    return out.dropna(subset=["date", "close"])


def _quality_checks(df: pd.DataFrame, label: str) -> dict:
    """Validate OHLC relationships and flag impossible values.

    Findings are reported, not acted on: the decision to exclude a row belongs
    to a human reading the report, not to the loader.
    """
    findings: dict[str, int | float] = {}

    has_ohlc = all(c in df.columns for c in ("open", "high", "low", "close"))
    if has_ohlc:
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        # The high must be the day's maximum and the low its minimum.
        broken_high = (h < o) | (h < c) | (h < l)
        broken_low = (l > o) | (l > c) | (l > h)
        invalid = (broken_high | broken_low).fillna(False)
        findings["invalid_ohlc_rows"] = int(invalid.sum())
        findings["invalid_ohlc_pct"] = round(100.0 * invalid.mean(), 4)
        # These are genuine defects in the source for thinly traded early
        # listings, where the recorded open falls outside the day's range.
        # They are reported rather than repaired, and they do not affect the
        # metrics this platform computes, all of which derive from close.
        if invalid.any():
            findings["invalid_ohlc_symbols"] = int(df.loc[invalid, "symbol"].nunique())

    for field in ("open", "high", "low", "close"):
        if field in df.columns:
            findings[f"non_positive_{field}"] = int((df[field] <= 0).fillna(False).sum())

    if "volume" in df.columns:
        findings["negative_volume"] = int((df["volume"] < 0).fillna(False).sum())
        findings["zero_volume_rows"] = int((df["volume"] == 0).fillna(False).sum())

    findings["duplicate_symbol_date"] = int(df.duplicated(subset=["symbol", "date"]).sum())
    findings["missing_close"] = int(df["close"].isna().sum())
    findings["rows"] = int(len(df))
    findings["symbols"] = int(df["symbol"].nunique())

    log.info("%s quality: %s", label, {k: v for k, v in findings.items() if v})
    return findings


def ingest_equities(limit: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Load every per-stock SCRIP file into one frame."""
    scrip_dir = KAGGLE_NSE_DIR / "SCRIP"
    if not scrip_dir.exists():
        raise PipelineError(
            f"SCRIP directory not found at {scrip_dir}. "
            "Set KAGGLE_NSE_DIR to the folder holding SCRIP/ and INDEX/."
        )

    files = sorted(scrip_dir.glob("*.csv"))
    if limit:
        files = files[:limit]
    log.info("reading %d SCRIP files from %s", len(files), scrip_dir)

    frames, skipped = [], []
    for n, path in enumerate(files, 1):
        if n % 400 == 0:
            log.info("  … %d/%d files", n, len(files))
        try:
            standard = _standardise(read_tabular(path), fallback_symbol=path.stem.upper())
        except Exception as exc:  # a single unreadable file must not stop the run
            skipped.append(f"{path.name}: {type(exc).__name__}")
            continue
        if standard is None or standard.empty:
            skipped.append(f"{path.name}: not price data")
            continue
        frames.append(standard)

    if not frames:
        raise PipelineError("no readable SCRIP price files found")

    equities = pd.concat(frames, ignore_index=True)
    equities = equities.drop_duplicates(subset=["symbol", "date"], keep="last")
    equities = equities.sort_values(["symbol", "date"]).reset_index(drop=True)

    if skipped:
        log.warning("skipped %d files (first few: %s)", len(skipped), skipped[:5])

    quality = _quality_checks(equities, "equity")
    quality["files_read"] = len(frames)
    quality["files_skipped"] = len(skipped)
    return equities, quality


def ingest_indices() -> tuple[pd.DataFrame, dict]:
    """Load the INDEX files, taking each index name from its filename."""
    index_dir = KAGGLE_NSE_DIR / "INDEX"
    if not index_dir.exists():
        raise PipelineError(f"INDEX directory not found at {index_dir}")

    files = sorted(index_dir.glob("*.csv"))
    log.info("reading %d INDEX files", len(files))

    frames = []
    for path in files:
        standard = _standardise(read_tabular(path), fallback_symbol=path.stem.upper())
        if standard is None or standard.empty:
            continue
        # Index files carry no symbol column; the filename is the index name.
        standard["symbol"] = path.stem.upper()
        frames.append(standard)

    if not frames:
        raise PipelineError("no readable INDEX files found")

    indices = pd.concat(frames, ignore_index=True)
    indices = indices.drop_duplicates(subset=["symbol", "date"], keep="last")
    indices = indices.sort_values(["symbol", "date"]).reset_index(drop=True)

    return indices, _quality_checks(indices, "index")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the Kaggle NSE dataset")
    parser.add_argument("--limit", type=int, default=None, help="read only N SCRIP files")
    args = parser.parse_args()

    report: dict = {}

    with Stage(log, "ingest equities"):
        equities, report["equity"] = ingest_equities(args.limit)
        log.info(describe_frame(equities, "equities"))
        equities.to_parquet(RAW_DIR / "nse_equity.parquet", index=False)

    with Stage(log, "ingest indices"):
        indices, report["index"] = ingest_indices()
        log.info(describe_frame(indices, "indices"))
        indices.to_parquet(RAW_DIR / "nse_index.parquet", index=False)

    with Stage(log, "check universe coverage"):
        universe = load_universe()
        # Equity symbols are stored under a filename that strips '&' (M&M -> MM).
        wanted = universe.loc[universe.asset_class == "equity", "file_symbol"].dropna()
        available = set(equities["symbol"].unique())
        missing = sorted(set(wanted) - available)
        report["universe_coverage"] = {
            "required": int(len(wanted)),
            "found": int(len(wanted) - len(missing)),
            "missing": missing,
        }
        if missing:
            log.warning("universe symbols absent from the dataset: %s", missing)
        else:
            log.info("all %d MVP equity symbols present", len(wanted))

    path = write_report("ingest_quality", report)
    log.info("quality report → %s", path)


if __name__ == "__main__":
    main()
