"""Stage 12 — daily OHLCV for the trading universe (NIFTY 100 + indices).

The analytics panel (``market_prices``) carries adjusted closes only, which
is all the risk and health measures need. Screeners and candlestick patterns
need open, high, low and volume as well, so the trading surfaces read their
own table: one long parquet, written here, read by
``app.services.screener_service``.

Kept separate on purpose. Folding OHLCV into ``market_prices`` would change
a table the trained models were fitted against.

Output: ``data/processed/universe_daily.parquet`` with columns
date, symbol, open, high, low, close, volume.

Run:  python -m ml.pipelines.p12_fetch_universe [--period 2y]
"""

from __future__ import annotations

import argparse

import pandas as pd

from .common import PROCESSED_DIR, REFERENCE_DIR, PipelineError, Stage, get_logger, write_report

log = get_logger("universe")

OUTPUT = PROCESSED_DIR / "universe_daily.parquet"

# Index series the trading surfaces quote alongside the stocks.
INDEX_SYMBOLS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "INDIAVIX": "^INDIAVIX",
}

# A screener over a few weeks of data cannot compute a 200-day average; a
# universe that came back that thin is a failed fetch, not a smaller result.
MIN_SESSIONS = 220
MIN_SYMBOLS = 80


def fetch(period: str) -> pd.DataFrame:
    import yfinance as yf

    universe = pd.read_csv(REFERENCE_DIR / "nifty100.csv")
    tickers = {f"{s}.NS": s for s in universe["symbol"]}
    tickers.update({v: k for k, v in INDEX_SYMBOLS.items()})

    raw = yf.download(
        list(tickers), period=period, interval="1d", group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )

    frames = []
    for ticker, symbol in tickers.items():
        if ticker not in raw.columns.get_level_values(0):
            log.warning("no data for %s", ticker)
            continue
        one = raw[ticker].dropna(subset=["Close"]).copy()
        if one.empty:
            log.warning("empty series for %s", ticker)
            continue
        one.columns = [c.lower() for c in one.columns]
        one["symbol"] = symbol
        one.index.name = "date"
        frames.append(one.reset_index()[["date", "symbol", "open", "high", "low", "close", "volume"]])

    if not frames:
        raise PipelineError("Yahoo returned nothing for the universe")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2y")
    args = parser.parse_args()

    with Stage(log, f"fetch universe daily OHLCV ({args.period})"):
        frame = fetch(args.period)

    sessions = frame.groupby("symbol")["date"].nunique()
    thin = sessions[sessions < MIN_SESSIONS]
    if len(sessions) < MIN_SYMBOLS:
        raise PipelineError(f"only {len(sessions)} symbols fetched; expected at least {MIN_SYMBOLS}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUTPUT, index=False)
    log.info("wrote %s: %d rows, %d symbols", OUTPUT.name, len(frame), len(sessions))

    write_report("universe_fetch", {
        "symbols": int(len(sessions)),
        "rows": int(len(frame)),
        "first_date": str(frame["date"].min().date()),
        "last_date": str(frame["date"].max().date()),
        "thin_symbols": {k: int(v) for k, v in thin.items()},
        "note": "Daily OHLCV, split/dividend adjusted by Yahoo. Used by screeners only.",
    })


if __name__ == "__main__":
    main()
