"""Stage 03b — quantify what corporate-action adjustment changes.

Evidence for the project report. The Kaggle NSE closing prices are raw and
unadjusted, so a 1:1 bonus issue reads as a 50% crash. This stage recomputes
the headline risk metrics both ways over the overlapping window and records
the difference.

The result is the justification for not using the raw Kaggle closes in any
portfolio calculation.

Run:  python -m ml.pipelines.p03b_validate_adjustment
"""

from __future__ import annotations

import pandas as pd

from wealthos_core import (
    annualized_return,
    annualized_volatility,
    max_drawdown,
    sharpe_ratio,
)

from .common import PROCESSED_DIR, RAW_DIR, Stage, get_logger, load_universe, write_report

log = get_logger("adjust-check")

COMPARISON_START = "2012-01-01"
COMPARISON_END = "2021-07-01"   # the last date the Kaggle data covers
PHANTOM_MOVE_THRESHOLD = 0.35   # a one-day move this large is almost never real


def main() -> None:
    equities = pd.read_parquet(RAW_DIR / "nse_equity.parquet")
    panel = pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")
    universe = load_universe()

    symbols = [
        s for s in universe.loc[
            (universe.asset_class == "equity") & (universe.status == "active"), "symbol"
        ]
        if s in panel.columns
    ]

    rows = []
    with Stage(log, f"compare {len(symbols)} symbols, {COMPARISON_START} to {COMPARISON_END}"):
        for symbol in symbols:
            raw = equities[
                (equities.symbol == symbol)
                & (equities.date >= COMPARISON_START)
                & (equities.date <= COMPARISON_END)
            ].set_index("date")["close"].sort_index()
            adjusted = panel.loc[COMPARISON_START:COMPARISON_END, symbol].dropna()

            if len(raw) < 250 or len(adjusted) < 250:
                continue

            raw_returns = raw.pct_change().dropna()
            adj_returns = adjusted.pct_change().dropna()

            rows.append(
                {
                    "symbol": symbol,
                    "phantom_moves": int((raw_returns.abs() > PHANTOM_MOVE_THRESHOLD).sum()),
                    "vol_unadjusted": annualized_volatility(raw_returns),
                    "vol_adjusted": annualized_volatility(adj_returns),
                    "mdd_unadjusted": max_drawdown(raw_returns),
                    "mdd_adjusted": max_drawdown(adj_returns),
                    "sharpe_unadjusted": sharpe_ratio(raw_returns),
                    "sharpe_adjusted": sharpe_ratio(adj_returns),
                    "return_unadjusted": annualized_return(raw_returns),
                    "return_adjusted": annualized_return(adj_returns),
                }
            )

    frame = pd.DataFrame(rows)
    frame["vol_error"] = frame.vol_unadjusted - frame.vol_adjusted
    frame["mdd_error"] = frame.mdd_unadjusted - frame.mdd_adjusted
    frame["sharpe_error"] = frame.sharpe_unadjusted - frame.sharpe_adjusted
    # The most damaging consequence: a profitable holding judged unprofitable.
    frame["sharpe_sign_flip"] = (
        frame.sharpe_unadjusted * frame.sharpe_adjusted < 0
    )

    summary = {
        "window": [COMPARISON_START, COMPARISON_END],
        "symbols_compared": int(len(frame)),
        "symbols_with_phantom_moves": int((frame.phantom_moves > 0).sum()),
        "total_phantom_moves": int(frame.phantom_moves.sum()),
        "volatility_overstated_pp": {
            "median": round(float(frame.vol_error.median() * 100), 2),
            "max": round(float(frame.vol_error.max() * 100), 2),
        },
        "max_drawdown_overstated_pp": {
            "median": round(float(-frame.mdd_error.median() * 100), 2),
            "max": round(float(-frame.mdd_error.min() * 100), 2),
        },
        "sharpe_understated": {
            "median": round(float(-frame.sharpe_error.median()), 3),
            "max": round(float(-frame.sharpe_error.min()), 3),
        },
        "sharpe_sign_flips": int(frame.sharpe_sign_flip.sum()),
        "worst_cases": frame.nlargest(5, "vol_error")[
            ["symbol", "phantom_moves", "vol_unadjusted", "vol_adjusted",
             "mdd_unadjusted", "mdd_adjusted", "sharpe_unadjusted", "sharpe_adjusted"]
        ].round(3).to_dict("records"),
    }

    log.info("symbols with phantom moves : %d of %d",
             summary["symbols_with_phantom_moves"], summary["symbols_compared"])
    log.info("volatility overstated by   : %.2f pp median, %.2f pp worst",
             summary["volatility_overstated_pp"]["median"],
             summary["volatility_overstated_pp"]["max"])
    log.info("max drawdown overstated by : %.2f pp median, %.2f pp worst",
             summary["max_drawdown_overstated_pp"]["median"],
             summary["max_drawdown_overstated_pp"]["max"])
    log.info("Sharpe sign flips          : %d (a profitable holding judged unprofitable)",
             summary["sharpe_sign_flips"])

    frame.round(4).to_csv(RAW_DIR.parent / "processed" / "adjustment_impact.csv", index=False)
    path = write_report("adjustment_impact", summary)
    log.info("evidence → %s", path)


if __name__ == "__main__":
    main()
