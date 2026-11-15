"""Stage 02 — fetch the prices the Kaggle dataset does not contain.

Two gaps motivate this stage:

1. The Kaggle set has no gold and no ETF series, yet the product universe is
   "NIFTY 50 plus ETF/gold/debt/cash". GOLDBEES and NIFTYBEES supply real
   rupee-denominated history for those classes.
2. The Kaggle set stops on 2021-07-01, a limitation the PRD itself flags.
   Fetching the same symbols forward extends the universe to the present.

Output: one parquet per symbol under ``data/external/yahoo/``, plus a
manifest. The fetch runs once; every later stage reads the cache, so the
pipeline is reproducible offline.

Run:  python -m ml.pipelines.p02_fetch_external [--refresh] [--symbols A,B]
"""

from __future__ import annotations

import argparse
import json
import time

import httpx
import pandas as pd

from .common import (
    EXTERNAL_DIR,
    PipelineError,
    Stage,
    get_logger,
    load_universe,
    write_report,
)

log = get_logger("fetch")

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CACHE_DIR = EXTERNAL_DIR / "yahoo"

# A generic client identifier. No user or project information is sent.
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; wealthos-research/0.1)"}

# 2000-01-01 through a far-future bound, so one request returns all history.
PERIOD_START = 946684800
PERIOD_END = 2000000000

REQUEST_DELAY_SECONDS = 0.6  # courtesy pacing between requests


def _parse_chart(payload: dict, symbol: str) -> pd.DataFrame:
    """Turn a Yahoo chart response into a tidy OHLCV frame."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise PipelineError(f"{symbol}: {chart['error']}")

    results = chart.get("result") or []
    if not results:
        raise PipelineError(f"{symbol}: empty response")

    result = results[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        raise PipelineError(f"{symbol}: no timestamps returned")

    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(
                "Asia/Kolkata"
            ).normalize().tz_localize(None),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        }
    )

    # adjclose is corrected for splits *and* dividends. It is the only series
    # from which a correct total return can be computed, so it is kept
    # separately from the raw close rather than overwriting it.
    adj = result["indicators"].get("adjclose")
    frame["adj_close"] = adj[0]["adjclose"] if adj else frame["close"]

    frame["symbol"] = symbol
    frame = frame.dropna(subset=["close"]).drop_duplicates("date")
    return frame.sort_values("date").reset_index(drop=True)


def fetch_symbol(client: httpx.Client, yahoo_symbol: str) -> pd.DataFrame:
    """Request one symbol's full daily history."""
    response = client.get(
        YAHOO_CHART_URL.format(symbol=yahoo_symbol),
        params={
            "interval": "1d",
            "period1": PERIOD_START,
            "period2": PERIOD_END,
            "events": "div,split",
        },
        headers=REQUEST_HEADERS,
        timeout=30.0,
    )
    response.raise_for_status()
    return _parse_chart(response.json(), yahoo_symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch external price history")
    parser.add_argument("--refresh", action="store_true", help="re-fetch cached symbols")
    parser.add_argument("--symbols", type=str, default=None, help="comma-separated subset")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = load_universe()

    targets = universe[universe["yahoo_symbol"].notna() & (universe["yahoo_symbol"] != "")]
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",")}
        targets = targets[targets["symbol"].str.upper().isin(wanted)]

    log.info("%d symbols to fetch (cache: %s)", len(targets), CACHE_DIR)

    manifest: dict[str, dict] = {}
    fetched = cached = failed = 0

    with httpx.Client(follow_redirects=True) as client:
        for _, row in targets.iterrows():
            symbol, yahoo_symbol = row["symbol"], row["yahoo_symbol"]
            # '/' and os separators would break the filename.
            path = CACHE_DIR / f"{symbol.replace('/', '_')}.parquet"

            if path.exists() and not args.refresh:
                frame = pd.read_parquet(path)
                cached += 1
            else:
                try:
                    frame = fetch_symbol(client, yahoo_symbol)
                    frame.to_parquet(path, index=False)
                    fetched += 1
                    time.sleep(REQUEST_DELAY_SECONDS)
                except Exception as exc:
                    log.warning("  %-12s FAILED  %s", symbol, str(exc)[:90])
                    manifest[symbol] = {"status": "failed", "error": str(exc)[:200]}
                    failed += 1
                    continue

            manifest[symbol] = {
                "status": "ok",
                "yahoo_symbol": yahoo_symbol,
                "asset_class": row["asset_class"],
                "rows": int(len(frame)),
                "start": str(frame["date"].min().date()),
                "end": str(frame["date"].max().date()),
                "path": str(path.relative_to(EXTERNAL_DIR.parent.parent)),
            }

    log.info("fetched %d, from cache %d, failed %d", fetched, cached, failed)

    ok = {k: v for k, v in manifest.items() if v["status"] == "ok"}
    if ok:
        latest = max(v["end"] for v in ok.values())
        log.info("most recent observation across all symbols: %s", latest)

    # Gold and an equity ETF are the two series the Kaggle set cannot supply.
    for required in ("GOLDBEES", "NIFTYBEES"):
        if manifest.get(required, {}).get("status") != "ok":
            log.error(
                "%s is unavailable — the %s asset class would have no real price "
                "history", required, "gold" if required == "GOLDBEES" else "etf",
            )

    path = write_report("external_fetch", {"symbols": manifest})
    log.info("manifest → %s", path)


if __name__ == "__main__":
    main()
