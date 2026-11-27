"""Stage 14 — swing feature and target tables, plus the bias study.

Builds ``features_swing.parquet`` and ``targets_swing.parquet`` with the
shared ``wealthos_core.swing_features`` code that the live signal service
also uses. The report records:

* coverage: dates, rows per year, eligible stocks per date;
* the survivorship-bias sensitivity study: equal-weight and plain momentum
  returns with and without the point-in-time liquidity filter;
* univariate ICs of every feature (descriptive only; no feature is selected
  on them, so they cannot leak).

Run:  python -m ml.pipelines.p14_build_swing_features
"""

from __future__ import annotations

import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.backtest_xs import rank_portfolio_backtest
from wealthos_core.validation import daily_rank_ic, ic_summary

from .common import Stage, get_logger, write_report
from .swing_common import (FEATURES_PATH, FIRST_TEST_YEAR, TARGETS_PATH, clean_json, load_wide, sectors,
                           series_summary)

log = get_logger("swing-features")


def bias_study(w: sf.Wide) -> list[dict]:
    rows = []
    start = f"{FIRST_TEST_YEAR}-01-01"
    unfiltered = sf.build_features(w, sectors(), liquid_top=None)
    mom_all = unfiltered["f_mom_12_1"].unstack().reindex(index=w.close.index, columns=w.close.columns)
    for top in (None, 70, sf.LIQUID_TOP, 50):
        elig = sf.eligibility(w, top)
        ew = rank_portfolio_backtest(elig.astype(float).where(elig), w.open, w.close,
                                     top_n=None, buffer=None, start=start).summary()
        mom = rank_portfolio_backtest(mom_all.where(elig), w.open, w.close, start=start).summary()
        rows.append({
            "eligible": "all of today's NIFTY 100" if top is None else f"top {top} by traded value at the time",
            "avg_eligible_stocks": float(elig.loc[start:].sum(axis=1).mean()),
            "equal_weight_cagr": ew["cagr"], "equal_weight_max_drawdown": ew["max_drawdown"],
            "momentum_top10_cagr": mom["cagr"], "momentum_top10_max_drawdown": mom["max_drawdown"],
            "momentum_edge_over_equal_weight": mom["cagr"] - ew["cagr"],
            "chosen": top == sf.LIQUID_TOP,
        })
    return rows


def main() -> None:
    w = load_wide()
    with Stage(log, "build features"):
        features = sf.build_features(w, sectors())
    with Stage(log, "build targets"):
        targets = sf.build_targets(w)
    features.to_parquet(FEATURES_PATH)
    targets.to_parquet(TARGETS_PATH)
    log.info("features %s, targets %s", features.shape, targets.shape)

    with Stage(log, "survivorship-bias study"):
        study = bias_study(w)

    joined = features.join(targets, how="inner")
    univariate = {}
    with Stage(log, "univariate ICs"):
        for name in sf.FEATURES:
            if name.startswith("m_"):
                continue
            frame = joined[[name, "excess"]].rename(columns={name: "score"})
            univariate[name] = ic_summary(daily_rank_ic(frame), sf.HORIZON)["mean_ic"]

    dates = pd.DatetimeIndex(features.index.get_level_values("date"))
    per_date = features.groupby(level="date").size()
    nifty = w.index_close.loc[f"{FIRST_TEST_YEAR}-01-01":].pct_change().dropna()
    write_report("swing_features", clean_json({
        "feature_version": sf.FEATURE_VERSION,
        "horizon_sessions": sf.HORIZON,
        "features": sf.FEATURES,
        "feature_labels": sf.FEATURE_LABELS,
        "rows": int(len(features)),
        "labelled_rows": int(len(targets)),
        "first_date": str(dates.min().date()),
        "last_date": str(dates.max().date()),
        "rows_per_year": {int(k): int(v) for k, v in pd.Series(dates.year).value_counts().sort_index().items()},
        "eligible_per_date": {"median": float(per_date.median()), "min": int(per_date.min()), "max": int(per_date.max())},
        "liquid_top": sf.LIQUID_TOP,
        "target": ("Return from the next session's open to the close ten sessions later, "
                   "minus the eligible universe's mean that day."),
        "survivorship_study": study,
        "nifty_price_index_since_first_test_year": series_summary(nifty),
        "univariate_ic": dict(sorted(univariate.items(), key=lambda kv: -(kv[1] or 0))),
        "note": ("Univariate ICs are descriptive over the full sample. No feature is chosen or dropped "
                 "on them, so they do not leak into the walk-forward evaluation."),
    }))


if __name__ == "__main__":
    main()
