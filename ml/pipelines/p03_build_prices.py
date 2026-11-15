"""Stage 03 — assemble one validated, corporate-action-adjusted price panel.

Why this stage is not a simple concatenation
--------------------------------------------
The Kaggle NSE closing prices are **not adjusted for corporate actions**.
RELIANCE shows -50.3% on 2017-09-07 and TCS -50.5% on 2018-05-31; both are
1:1 bonus issues, not crashes. Across the 51-name MVP universe there are 78
such phantom moves. Computing volatility, drawdown, Sharpe or beta from that
series would produce confidently wrong numbers.

Yahoo's ``adj_close`` is adjusted for splits, bonuses and dividends and spans
2000-2026, which covers the whole simulation window. It is therefore the
price source for every tradeable asset. The Kaggle data keeps three jobs it
is uniquely good at: the 1990-2021 index history, the 2,096-symbol breadth
used for sector assignment and EDA, and independent cross-validation.

Splices and their gates
-----------------------
Two kinds of join happen here and they are held to different standards:

``same_instrument``  the two sources carry the identical series (Kaggle
                     "NIFTY 50" and Yahoo ^NSEI). Demands return correlation
                     >= 0.95 and level-ratio drift < 2%.
``proxy_handoff``    one instrument takes over from a related but distinct
                     one (NIFTY GS Composite -> GILT5YBEES for the debt
                     class). Demands correlation >= 0.80 and volatility
                     within 2x, and is recorded in the data dictionary as an
                     instrument change rather than a continuation.

Outputs
    data/processed/prices.parquet      long: date, symbol, price, source
    data/processed/returns.parquet     wide: date x symbol daily returns
    data/processed/price_panel.parquet wide: date x symbol prices
    ml/reports/price_build.json        splice evidence and gate results

Run:  python -m ml.pipelines.p03_build_prices
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .common import (
    EXTERNAL_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    PipelineError,
    Stage,
    get_logger,
    load_universe,
    write_report,
)

log = get_logger("prices")

SIMULATION_START = pd.Timestamp("2012-01-01")

# Validation thresholds. A failed gate aborts the stage rather than writing a
# series that looks plausible and is silently wrong.
SAME_INSTRUMENT_MIN_CORR = 0.95
SAME_INSTRUMENT_MAX_DRIFT = 0.02
PROXY_MIN_CORR = 0.80
PROXY_MAX_VOL_RATIO = 2.0
MAX_PLAUSIBLE_DAILY_MOVE = 0.50

CASH_ANNUAL_RETURN = 0.055


def _yahoo_series(symbol: str, column: str = "adj_close") -> pd.Series:
    path = EXTERNAL_DIR / "yahoo" / f"{symbol}.parquet"
    if not path.exists():
        raise PipelineError(f"missing cached fetch for {symbol}; run stage 02")
    frame = pd.read_parquet(path).set_index("date").sort_index()
    series = frame[column].dropna()
    return series[~series.index.duplicated(keep="last")]


def _kaggle_index(name: str, indices: pd.DataFrame) -> pd.Series:
    series = indices[indices["symbol"] == name].set_index("date")["close"].sort_index().dropna()
    if series.empty:
        raise PipelineError(f"index {name!r} not present in the Kaggle index data")
    return series[~series.index.duplicated(keep="last")]


def repair_reverting_spikes(
    series: pd.Series,
    label: str,
    jump_factor: float = 1.8,
    lookahead: int = 5,
    tolerance: float = 0.10,
) -> tuple[pd.Series, list[dict]]:
    """Null out isolated price excursions that reverse themselves.

    Yahoo occasionally applies a split adjustment to a couple of days and then
    reverts it. NIFTYBEES, BANKBEES and GOLDBEES each show exactly this on
    2019-12-19/20: the price drops to a tenth (a hundredth for GOLDBEES),
    holds for two sessions, then returns to its previous level. A real split
    never reverts, so a round trip of that magnitude is a feed defect.

    Only round trips are repaired. A jump that does *not* come back is left
    alone so the validation gate still fails on a genuine unadjusted
    corporate action rather than having it quietly smoothed away.
    """
    values = series.dropna()
    if len(values) < 3:
        return series, []

    repairs: list[dict] = []
    prices = values.to_numpy(dtype="float64")
    dates = values.index
    flagged = np.zeros(len(prices), dtype=bool)

    index = 1
    while index < len(prices):
        previous = prices[index - 1]
        if previous <= 0:
            index += 1
            continue

        ratio = prices[index] / previous
        if (1 / jump_factor) < ratio < jump_factor:
            index += 1
            continue

        # Does the price come back to where it was, within `lookahead` days?
        recovery = None
        for ahead in range(index + 1, min(index + 1 + lookahead, len(prices))):
            if abs(prices[ahead] / previous - 1.0) <= tolerance:
                recovery = ahead
                break

        if recovery is None:
            index += 1  # one-way move: leave it for the gate to judge
            continue

        flagged[index:recovery] = True
        repairs.append(
            {
                "from": str(dates[index].date()),
                "to": str(dates[recovery - 1].date()),
                "days": int(recovery - index),
                "excursion_ratio": round(float(ratio), 5),
                "level_before": round(float(previous), 4),
                "level_after": round(float(prices[recovery]), 4),
            }
        )
        index = recovery

    if not repairs:
        return series, []

    cleaned = series.copy()
    cleaned.loc[dates[flagged]] = np.nan
    total = int(flagged.sum())
    log.warning(
        "  %-12s repaired %d reverting observation(s) across %d episode(s): %s",
        label, total, len(repairs), [r["from"] for r in repairs],
    )
    return cleaned, repairs


def _splice(
    historical: pd.Series,
    recent: pd.Series,
    kind: str,
    label: str,
) -> tuple[pd.Series, dict]:
    """Join a historical series onto a recent one on the recent one's scale.

    The two series are rescaled rather than concatenated, because they sit on
    different bases: an unadjusted index level and an adjusted ETF price are
    not the same number even when they track the same exposure.
    """
    joined = pd.concat(
        [historical.rename("hist"), recent.rename("recent")], axis=1, join="inner"
    ).dropna()

    evidence: dict = {
        "kind": kind,
        "overlap_days": int(len(joined)),
        "historical_span": [str(historical.index.min().date()), str(historical.index.max().date())],
        "recent_span": [str(recent.index.min().date()), str(recent.index.max().date())],
    }

    if len(joined) < 30:
        raise PipelineError(
            f"{label}: overlap of {len(joined)} days is too short to validate a splice"
        )

    returns = pd.concat(
        [joined["hist"].pct_change(), joined["recent"].pct_change()], axis=1
    ).dropna()
    correlation = float(returns.iloc[:, 0].corr(returns.iloc[:, 1]))

    ratio = joined["recent"] / joined["hist"]
    scale = float(ratio.median())
    drift = float(abs(ratio.iloc[-1] / ratio.iloc[0] - 1.0))

    hist_vol = float(returns.iloc[:, 0].std() * np.sqrt(252))
    recent_vol = float(returns.iloc[:, 1].std() * np.sqrt(252))
    vol_ratio = recent_vol / hist_vol if hist_vol > 0 else float("inf")

    evidence.update(
        {
            "return_correlation": round(correlation, 4),
            "scale_factor": round(scale, 6),
            "ratio_drift": round(drift, 4),
            "historical_ann_vol": round(hist_vol, 4),
            "recent_ann_vol": round(recent_vol, 4),
            "vol_ratio": round(vol_ratio, 3),
        }
    )

    if kind == "same_instrument":
        if correlation < SAME_INSTRUMENT_MIN_CORR:
            raise PipelineError(
                f"{label}: return correlation {correlation:.4f} < {SAME_INSTRUMENT_MIN_CORR}; "
                "the two sources do not carry the same series"
            )
        if drift > SAME_INSTRUMENT_MAX_DRIFT:
            raise PipelineError(
                f"{label}: level ratio drifted {drift:.2%} across the overlap, so a single "
                "scale factor cannot align them"
            )
    elif kind == "proxy_handoff":
        if correlation < PROXY_MIN_CORR:
            raise PipelineError(
                f"{label}: return correlation {correlation:.4f} < {PROXY_MIN_CORR}; "
                "these instruments are too dissimilar to hand off between"
            )
        if not (1 / PROXY_MAX_VOL_RATIO) <= vol_ratio <= PROXY_MAX_VOL_RATIO:
            raise PipelineError(
                f"{label}: volatility ratio {vol_ratio:.2f} is outside "
                f"{1/PROXY_MAX_VOL_RATIO:.2f}-{PROXY_MAX_VOL_RATIO:.2f}; the successor has a "
                "materially different risk profile"
            )
    else:
        raise ValueError(f"unknown splice kind {kind!r}")

    # Put the history on the recent series' scale, then hand over at the first
    # date the recent series covers.
    handover = recent.index.min()
    rescaled = historical[historical.index < handover] * scale
    combined = pd.concat([rescaled, recent]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]

    # The join itself must not manufacture a jump.
    joined_returns = combined.pct_change().dropna()
    window = joined_returns[
        (joined_returns.index >= handover - pd.Timedelta(days=7))
        & (joined_returns.index <= handover + pd.Timedelta(days=7))
    ]
    worst = float(window.abs().max()) if len(window) else 0.0
    evidence["max_move_at_join"] = round(worst, 4)
    if worst > MAX_PLAUSIBLE_DAILY_MOVE:
        raise PipelineError(
            f"{label}: the join produced a {worst:.1%} single-day move, which is an artifact "
            "of misaligned scales rather than a real price change"
        )

    evidence["handover_date"] = str(handover.date())
    evidence["result_span"] = [str(combined.index.min().date()), str(combined.index.max().date())]
    evidence["result_rows"] = int(len(combined))
    log.info(
        "  %-22s corr=%.4f scale=%.4g drift=%.2f%% join_move=%.2f%% → %d rows",
        label, correlation, scale, 100 * drift, 100 * worst, len(combined),
    )
    return combined, evidence


def build_cash_series(index: pd.DatetimeIndex) -> pd.Series:
    """A deterministic cash accrual, compounded daily on trading days.

    Liquid ETFs such as LIQUIDBEES hold their NAV at a constant and pay their
    return out as dividends, so their price series shows a flat line. Reading
    that as "cash returns nothing" would be wrong, so cash is modelled at an
    explicit documented rate instead of being read off a price.
    """
    daily = (1.0 + CASH_ANNUAL_RETURN) ** (1.0 / 252.0) - 1.0
    return pd.Series((1.0 + daily) ** np.arange(len(index)) * 100.0, index=index, name="CASH")


def main() -> None:
    universe = load_universe()
    indices = pd.read_parquet(RAW_DIR / "nse_index.parquet")

    series: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    report: dict = {"splices": {}, "assets": {}}

    with Stage(log, "benchmark: splice Kaggle NIFTY 50 with Yahoo ^NSEI"):
        benchmark, evidence = _splice(
            _kaggle_index("NIFTY 50", indices),
            _yahoo_series("NIFTY50", "close"),
            kind="same_instrument",
            label="NIFTY50",
        )
        series["NIFTY50"] = benchmark
        sources["NIFTY50"] = "kaggle_index+yahoo(spliced)"
        report["splices"]["NIFTY50"] = evidence

    with Stage(log, "debt: hand off NIFTY GS Composite to GILT5YBEES"):
        debt, evidence = _splice(
            _kaggle_index("NIFTY GS COMPSITE", indices),
            _yahoo_series("GILT5YBEES"),
            kind="proxy_handoff",
            label="DEBT",
        )
        series["DEBT"] = debt
        sources["DEBT"] = "kaggle_gs_composite+gilt5ybees(handoff)"
        report["splices"]["DEBT"] = evidence

    with Stage(log, "tradeable assets from adjusted Yahoo prices"):
        tradeable = universe[
            (universe["status"] == "active")
            & universe["asset_class"].isin(["equity", "etf", "gold"])
            & universe["yahoo_symbol"].notna()
            & (universe["yahoo_symbol"] != "")
        ]
        for _, row in tradeable.iterrows():
            symbol = row["symbol"]
            try:
                raw = _yahoo_series(symbol)
            except PipelineError as exc:
                log.warning("  skipping %s: %s", symbol, exc)
                continue
            cleaned, repairs = repair_reverting_spikes(raw, symbol)
            series[symbol] = cleaned.ffill()
            sources[symbol] = "yahoo_adj_close"
            if repairs:
                report.setdefault("repairs", {})[symbol] = repairs
        log.info("  loaded %d tradeable assets", len(tradeable))

    with Stage(log, "assemble the panel"):
        panel = pd.DataFrame(series).sort_index()
        panel = panel[panel.index >= SIMULATION_START]
        # Carry the last observation across non-trading gaps so assets with
        # different holiday calendars stay aligned, but never invent a price
        # before an asset's first real observation.
        panel = panel.ffill()
        panel["CASH"] = build_cash_series(panel.index)
        sources["CASH"] = "modelled_accrual_5.5pct"

        log.info("  panel: %d dates x %d assets", len(panel), panel.shape[1])
        log.info("  span : %s → %s", panel.index.min().date(), panel.index.max().date())

    with Stage(log, "validate the assembled panel"):
        returns = panel.pct_change()
        extreme = (returns.abs() > MAX_PLAUSIBLE_DAILY_MOVE).sum()
        offenders = extreme[extreme > 0]
        if len(offenders):
            detail = offenders.to_dict()
            raise PipelineError(
                "implausible daily moves survived into the panel, which indicates an "
                f"unadjusted corporate action: {detail}"
            )
        log.info("  no daily move exceeds %.0f%% in any asset", 100 * MAX_PLAUSIBLE_DAILY_MOVE)

        coverage = panel.notna().mean()
        thin = coverage[coverage < 0.5]
        if len(thin):
            log.warning("  assets covering under half the window: %s", thin.round(2).to_dict())

        for symbol in panel.columns:
            column = panel[symbol].dropna()
            daily = column.pct_change().dropna()
            report["assets"][symbol] = {
                "source": sources.get(symbol, "unknown"),
                "rows": int(len(column)),
                "start": str(column.index.min().date()) if len(column) else None,
                "end": str(column.index.max().date()) if len(column) else None,
                "ann_return_pct": round(
                    float(((1 + daily).prod() ** (252 / len(daily)) - 1) * 100), 2
                ) if len(daily) > 252 else None,
                "ann_vol_pct": round(float(daily.std() * np.sqrt(252) * 100), 2)
                if len(daily) > 2 else None,
            }

    with Stage(log, "write outputs"):
        panel.to_parquet(PROCESSED_DIR / "price_panel.parquet")
        returns.to_parquet(PROCESSED_DIR / "returns.parquet")

        long = panel.stack().rename("price").reset_index()
        long.columns = ["date", "symbol", "price"]
        long["source"] = long["symbol"].map(sources)
        long.to_parquet(PROCESSED_DIR / "prices.parquet", index=False)

        report["panel"] = {
            "start": str(panel.index.min().date()),
            "end": str(panel.index.max().date()),
            "trading_days": int(len(panel)),
            "assets": int(panel.shape[1]),
            "simulation_start": str(SIMULATION_START.date()),
        }
        path = write_report("price_build", report)
        log.info("  evidence → %s", path)


if __name__ == "__main__":
    main()
