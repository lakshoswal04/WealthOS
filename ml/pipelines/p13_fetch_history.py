"""Stage 13 — long daily history for the swing-trading models.

Stage 12 keeps two years of OHLCV for the live screeners. That is far too
short to train or honestly evaluate a market model: two years is one regime,
and a walk-forward test needs many independent years. This stage fetches the
full Yahoo history for the same NIFTY 100 universe plus the market series the
features use (NIFTY 50, NIFTY Bank, India VIX).

Output: ``data/processed/history_daily.parquet`` (date, symbol, open, high,
low, close, volume), separate from ``universe_daily.parquet`` so the live
app's file is untouched.

Known bias, recorded in the report rather than hidden: the symbol list is
*today's* NIFTY 100. Stocks that left the index (often because they fell) are
missing, so absolute backtest returns are flattered. The swing models are
therefore judged against an equal-weight portfolio of the same universe, which
carries the same bias. NSE's historical constituent files cannot be fetched
automatically (its site refuses automated clients).

Run:  python -m ml.pipelines.p13_fetch_history [--period max]
"""

from __future__ import annotations

import argparse

import pandas as pd

from .common import PROCESSED_DIR, REFERENCE_DIR, PipelineError, Stage, get_logger, write_report

log = get_logger("history")

OUTPUT = PROCESSED_DIR / "history_daily.parquet"

MARKET_SYMBOLS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "INDIAVIX": "^INDIAVIX",
}

MIN_SYMBOLS = 80
MIN_MEDIAN_YEARS = 8.0


def fetch(period: str) -> pd.DataFrame:
    import yfinance as yf

    universe = pd.read_csv(REFERENCE_DIR / "nifty100.csv")
    tickers = {f"{s}.NS": s for s in universe["symbol"]}
    tickers.update({v: k for k, v in MARKET_SYMBOLS.items()})

    frames = []
    # Batches keep one failed request from losing the whole universe.
    names = list(tickers)
    for start in range(0, len(names), 25):
        batch = names[start:start + 25]
        raw = yf.download(
            batch, period=period, interval="1d", group_by="ticker",
            auto_adjust=True, progress=False, threads=True,
        )
        for ticker in batch:
            if ticker not in raw.columns.get_level_values(0):
                log.warning("no data for %s", ticker)
                continue
            one = raw[ticker].dropna(subset=["Close"]).copy()
            if one.empty:
                log.warning("empty series for %s", ticker)
                continue
            one.columns = [c.lower() for c in one.columns]
            one["symbol"] = tickers[ticker]
            one.index.name = "date"
            frames.append(one.reset_index()[["date", "symbol", "open", "high", "low", "close", "volume"]])

    if not frames:
        raise PipelineError("Yahoo returned nothing for the history fetch")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    out = out.drop_duplicates(["symbol", "date"], keep="last")
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def clean(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop rows that cannot be traded on and record how many were dropped."""
    before = len(frame)
    bad_price = (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    # Yahoo sometimes back-fills open/high/low with the close for old sessions;
    # those rows are usable (the close is real) but the range is not. Keep them
    # and let ATR-style features read a zero range rather than invent one.
    frame = frame.loc[~bad_price].copy()
    stocks = frame["symbol"].isin(MARKET_SYMBOLS) == False  # noqa: E712
    zero_volume = stocks & (frame["volume"] <= 0)
    frame = frame.loc[~zero_volume]
    return frame.reset_index(drop=True), {
        "rows_before": int(before),
        "dropped_non_positive_price": int(bad_price.sum()),
        "dropped_zero_volume_stock_sessions": int(zero_volume.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="max")
    args = parser.parse_args()

    with Stage(log, f"fetch daily history ({args.period})"):
        frame = fetch(args.period)
    frame, cleaning = clean(frame)

    stocks = frame.loc[~frame["symbol"].isin(MARKET_SYMBOLS)]
    span_years = stocks.groupby("symbol")["date"].agg(lambda d: (d.max() - d.min()).days / 365.25)
    if stocks["symbol"].nunique() < MIN_SYMBOLS:
        raise PipelineError(f"only {stocks['symbol'].nunique()} stocks fetched; expected {MIN_SYMBOLS}")
    if span_years.median() < MIN_MEDIAN_YEARS:
        raise PipelineError(f"median history {span_years.median():.1f}y; expected {MIN_MEDIAN_YEARS}y")
    missing_market = [m for m in MARKET_SYMBOLS if m not in set(frame["symbol"])]
    if "NIFTY" in missing_market:
        raise PipelineError("NIFTY history is required for the market features")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUTPUT, index=False)
    log.info("wrote %s: %d rows, %d series", OUTPUT.name, len(frame), frame["symbol"].nunique())

    market = frame.loc[frame["symbol"].isin(MARKET_SYMBOLS)].groupby("symbol")["date"].agg(["min", "max", "count"])
    write_report("history_fetch", {
        "stocks": int(stocks["symbol"].nunique()),
        "rows": int(len(frame)),
        "first_date": str(frame["date"].min().date()),
        "last_date": str(frame["date"].max().date()),
        "median_years_per_stock": round(float(span_years.median()), 1),
        "shortest_histories": {k: round(float(v), 1) for k, v in span_years.nsmallest(10).items()},
        "market_series": {k: {"first": str(r["min"].date()), "last": str(r["max"].date()), "sessions": int(r["count"])}
                          for k, r in market.iterrows()},
        "missing_market_series": missing_market,
        "cleaning": cleaning,
        "biases": {
            "survivorship": ("The universe is today's NIFTY 100; stocks that left the index are absent. "
                             "Models are judged against an equal-weight portfolio of the same universe, "
                             "which carries the same bias."),
            "dividends": ("Stock prices are dividend-adjusted by Yahoo; ^NSEI is a price index. "
                          "NIFTY is therefore a secondary benchmark that understates total return."),
        },
    })


if __name__ == "__main__":
    main()
