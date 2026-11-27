"""Stage 07 — build model-ready feature tables with chronological splits.

Three tables, one per model:

    features_clustering.parquet  one row per investor (behavioural profile)
    features_anomaly.parquet     one row per investor-month, with deltas
    features_forecast.parquet    one row per investor-month, with targets

The forecasting target is the decision that determines whether the reported
accuracy means anything.

A portfolio's value at t+h is dominated by its value at t plus the
contributions made in between. Regressing on raw rupee value therefore
produces an R-squared near 0.99 for almost any model, because the model is
mostly predicting "roughly what it is now, plus the deposits". That number
measures scale, not skill.

So each model predicts **excess log growth** over a contribution baseline:

    baseline_{t+h} = V_t + h * monthly_contribution     (zero market return)
    target         = log(V_{t+h}) - log(baseline_{t+h})

The baseline absorbs the predictable part and the model is left with only
the market-return component, which is the hard part and the only part worth
measuring. Both figures are reported: the scale-inflated R-squared on rupee
value for comparability, and the honest one on excess growth.

Splits are chronological and share a single cut date across all investors,
so no model ever trains on a month that precedes what it is tested on.

Run:  python -m ml.pipelines.p07_features
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from wealthos_core import BENCHMARK_SYMBOL
from wealthos_core.anomaly import derive_anomaly_features

from .common import (
    silence_accelerate_matmul_warnings,
    PROCESSED_DIR,
    SYNTHETIC_DIR,
    PipelineError,
    Stage,
    get_logger,
    write_report,
)

log = get_logger("features")

silence_accelerate_matmul_warnings()

FORECAST_HORIZONS = (1, 3, 6, 12)

# Chronological split boundaries. The test period is fixed and untouched
# until final evaluation.
TRAIN_END = pd.Timestamp("2022-12-31")
VALIDATION_END = pd.Timestamp("2024-06-30")

# A sequence model needs a run-up; investor-months before this are used as
# history but never as a training row.
MIN_HISTORY_MONTHS = 12

ALLOCATION_COLUMNS = [
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation",
]


def _assign_split(dates: pd.Series) -> pd.Series:
    """Label every row train / validation / test by date alone.

    All investors share the same boundaries. Splitting per investor, or at
    random, would let a model learn from a market regime it is later tested
    on, which is the classic way time-series results come out flattering and
    wrong.
    """
    return pd.Series(
        np.select(
            [dates <= TRAIN_END, dates <= VALIDATION_END],
            ["train", "validation"],
            default="test",
        ),
        index=dates.index,
    )


# --------------------------------------------------------------------------
# Clustering features
# --------------------------------------------------------------------------

def build_clustering_features(snapshots: pd.DataFrame, investors: pd.DataFrame) -> pd.DataFrame:
    """One behavioural profile per investor.

    Built only from months up to the training cut, so an investor's cluster
    is not informed by behaviour that occurs after the period the model was
    fitted on.
    """
    history = snapshots[
        (snapshots["date"] <= TRAIN_END) & (snapshots["is_anomaly"] == 0)
    ]

    grouped = history.groupby("investor_id")
    features = grouped.agg(
        equity_allocation=("equity_allocation", "mean"),
        etf_allocation=("etf_allocation", "mean"),
        gold_allocation=("gold_allocation", "mean"),
        debt_allocation=("debt_allocation", "mean"),
        cash_allocation=("cash_allocation", "mean"),
        allocation_volatility=("equity_allocation", "std"),
        turnover=("turnover", "mean"),
        trades_per_month=("n_trades", "mean"),
        portfolio_volatility=("volatility", "mean"),
        max_drawdown=("max_drawdown", "min"),
        hhi=("hhi", "mean"),
        top_holding_weight=("top_holding_weight", "mean"),
        n_holdings=("n_holdings", "mean"),
        months_observed=("date", "count"),
    )

    # Share of observed months in which money was added.
    funded = history.assign(funded=(history["net_contribution"] > 0).astype(float))
    features["contribution_consistency"] = funded.groupby("investor_id")["funded"].mean()

    # Contribution scaled by portfolio size, so a large and a small investor
    # with the same saving discipline look alike to the model.
    rate = history["net_contribution"] / history["total_value"].replace(0, np.nan)
    features["contribution_rate"] = rate.groupby(history["investor_id"]).median()

    profile = investors.set_index("investor_id")
    features = features.join(
        profile[["age", "annual_income", "monthly_savings",
                 "investment_horizon_years", "risk_tolerance", "archetype"]]
    )

    # Investors with almost no history cannot be profiled reliably.
    features = features[features["months_observed"] >= MIN_HISTORY_MONTHS]
    return features.reset_index()


# --------------------------------------------------------------------------
# Anomaly features
# --------------------------------------------------------------------------

def build_anomaly_features(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Per-month state plus how much it moved from the month before.

    Change matters as much as level here. A 70% equity weight is ordinary;
    moving from 70% to 20% in one month is not, and only a delta can see
    that. Three lag features carry what no single month can: a dormancy break
    is a large contribution *after a silence*, and the silence is the part
    that makes it one.

    The derivations themselves live in ``wealthos_core.anomaly`` so that the
    serving path computes the identical columns. They were duplicated here
    and in ``insight_service`` until Phase 3a, which meant a feature added to
    training was silently zero-filled at inference.
    """
    frame = derive_anomaly_features(
        snapshots.sort_values(["investor_id", "date"]), group_key="investor_id"
    )

    feature_columns = (
        ALLOCATION_COLUMNS
        + [f"delta_{c}" for c in ALLOCATION_COLUMNS]
        + ["allocation_shift", "hhi", "delta_hhi", "top_holding_weight",
           "delta_top_holding_weight", "n_holdings", "delta_n_holdings",
           "turnover", "turnover_ratio", "n_trades", "contribution_ratio",
           "period_return", "current_drawdown", "volatility",
           "months_since_contribution", "delta_contribution_ratio",
           "recent_funding_rate"]
    )

    frame["split"] = _assign_split(frame["date"])
    keep = ["investor_id", "date", "split", "is_anomaly", "anomaly_type", "archetype"]
    out = frame[keep + feature_columns]

    # Drop the first month per investor, where every delta is undefined.
    return out.dropna(subset=["delta_equity_allocation"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Forecast features
# --------------------------------------------------------------------------

def build_forecast_features(
    snapshots: pd.DataFrame, investors: pd.DataFrame, market: pd.DataFrame
) -> pd.DataFrame:
    """Per-month features with forward targets at several horizons."""
    frame = snapshots.sort_values(["investor_id", "date"]).copy()
    grouped = frame.groupby("investor_id")

    # --- trailing behaviour, all backward-looking ---
    for window in (1, 3, 6, 12):
        frame[f"return_{window}m"] = grouped["period_return"].transform(
            lambda s, w=window: s.rolling(w, min_periods=max(1, w // 2)).apply(
                lambda x: np.prod(1 + x) - 1, raw=True
            )
        )
    frame["contribution_3m"] = grouped["net_contribution"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    frame["contribution_12m"] = grouped["net_contribution"].transform(
        lambda s: s.rolling(12, min_periods=3).mean()
    )
    frame["months_invested"] = grouped.cumcount() + 1
    frame["log_value"] = np.log(frame["total_value"].clip(lower=1.0))

    # --- market regime, identical for every investor on a date ---
    frame = frame.merge(market, on="date", how="left")

    # --- investor profile ---
    profile = investors[[
        "investor_id", "age", "annual_income", "monthly_savings",
        "investment_horizon_years", "risk_tolerance", "archetype",
    ]]
    frame = frame.merge(profile, on="investor_id", how="left", suffixes=("", "_profile"))

    # --- targets ---
    for horizon in FORECAST_HORIZONS:
        future_value = grouped["total_value"].shift(-horizon)
        frame[f"future_value_{horizon}m"] = future_value

        # The baseline a model has to beat: current value plus the
        # contributions expected over the horizon, assuming zero return.
        baseline = frame["total_value"] + horizon * frame["contribution_3m"].fillna(0.0)
        frame[f"baseline_{horizon}m"] = baseline

        # What the model actually predicts.
        frame[f"excess_log_growth_{horizon}m"] = np.log(
            future_value.clip(lower=1.0)
        ) - np.log(baseline.clip(lower=1.0))

    frame["split"] = _assign_split(frame["date"])
    # A row needs enough history behind it for its trailing features to mean
    # anything.
    frame = frame[frame["months_invested"] >= MIN_HISTORY_MONTHS]
    return frame.reset_index(drop=True)


def build_market_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Market-regime features, shared across investors.

    Everything is computed from data available at the month in question, so
    no future market information enters an investor's feature row.
    """
    monthly = panel.resample("ME").last().ffill()
    benchmark = monthly[BENCHMARK_SYMBOL]
    returns = benchmark.pct_change()

    market = pd.DataFrame({"date": monthly.index})
    market["market_return_1m"] = returns.to_numpy()
    market["market_return_3m"] = benchmark.pct_change(3).to_numpy()
    market["market_return_12m"] = benchmark.pct_change(12).to_numpy()
    market["market_volatility_12m"] = (
        returns.rolling(12, min_periods=6).std().to_numpy() * np.sqrt(12)
    )
    # Distance below the running peak: a simple regime indicator.
    market["market_drawdown"] = (
        benchmark / benchmark.cummax() - 1.0
    ).to_numpy()

    if "GOLDBEES" in monthly.columns:
        market["gold_return_3m"] = monthly["GOLDBEES"].pct_change(3).to_numpy()
    if "DEBT" in monthly.columns:
        market["debt_return_3m"] = monthly["DEBT"].pct_change(3).to_numpy()

    market["month_of_year"] = market["date"].dt.month
    return market


def main() -> None:
    snapshots_path = SYNTHETIC_DIR / "snapshots.parquet"
    if not snapshots_path.exists():
        raise PipelineError("run stage 06 first to generate the cohort")

    report: dict = {
        "split_boundaries": {
            "train_end": str(TRAIN_END.date()),
            "validation_end": str(VALIDATION_END.date()),
        },
        "forecast_horizons": list(FORECAST_HORIZONS),
    }

    with Stage(log, "load cohort"):
        snapshots = pd.read_parquet(snapshots_path)
        investors = pd.read_parquet(SYNTHETIC_DIR / "investors.parquet")
        panel = pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")
        log.info("  %d snapshots, %d investors", len(snapshots), len(investors))

    with Stage(log, "market regime features"):
        market = build_market_features(panel)
        log.info("  %d months of market features", len(market))

    with Stage(log, "clustering features"):
        clustering = build_clustering_features(snapshots, investors)
        clustering.to_parquet(PROCESSED_DIR / "features_clustering.parquet", index=False)
        log.info("  %d investors x %d features", len(clustering), clustering.shape[1])
        report["clustering"] = {
            "rows": int(len(clustering)),
            "columns": [c for c in clustering.columns],
        }

    with Stage(log, "anomaly features"):
        anomaly = build_anomaly_features(snapshots)
        anomaly.to_parquet(PROCESSED_DIR / "features_anomaly.parquet", index=False)
        counts = anomaly.groupby("split")["is_anomaly"].agg(["size", "sum"])
        for split, row in counts.iterrows():
            log.info("  %-11s %8d rows, %4d anomalies (%.3f%%)",
                     split, row["size"], row["sum"], 100 * row["sum"] / row["size"])
        report["anomaly"] = {
            "rows": int(len(anomaly)),
            "by_split": {
                str(k): {"rows": int(v["size"]), "anomalies": int(v["sum"])}
                for k, v in counts.iterrows()
            },
        }

    with Stage(log, "forecast features"):
        forecast = build_forecast_features(snapshots, investors, market)
        forecast.to_parquet(PROCESSED_DIR / "features_forecast.parquet", index=False)

        usable = forecast.dropna(subset=["excess_log_growth_12m"])
        counts = usable.groupby("split").size()
        for split, size in counts.items():
            log.info("  %-11s %8d rows usable at the 12-month horizon", split, size)

        report["forecast"] = {
            "rows": int(len(forecast)),
            "by_split_12m": {str(k): int(v) for k, v in counts.items()},
            "target": "excess_log_growth_{h}m = log(V_{t+h}) - log(V_t + h*contribution)",
            "rationale": (
                "Raw rupee value is dominated by current value plus deposits, so "
                "regressing on it yields a near-0.99 R-squared that measures scale "
                "rather than skill. The baseline absorbs that predictable part and "
                "leaves the model only the market-return component."
            ),
        }

    with Stage(log, "leakage checks"):
        # The split must partition by date with no overlap.
        for name, table in (("anomaly", anomaly), ("forecast", forecast)):
            ranges = table.groupby("split")["date"].agg(["min", "max"])
            train_max = ranges.loc["train", "max"]
            validation_min = ranges.loc["validation", "min"]
            test_min = ranges.loc["test", "min"]
            validation_max = ranges.loc["validation", "max"]

            if not (train_max < validation_min and validation_max < test_min):
                raise PipelineError(
                    f"{name}: split boundaries overlap, so a model would train on "
                    "months it is later tested on"
                )
            log.info("  %-9s train ≤ %s │ validation %s..%s │ test ≥ %s",
                     name, train_max.date(), validation_min.date(),
                     validation_max.date(), test_min.date())

        # No feature column may contain a forward-looking value.
        feature_columns = [
            c for c in forecast.columns
            if not c.startswith(("future_", "excess_log_growth_", "baseline_"))
        ]
        forbidden = [c for c in feature_columns if "future" in c.lower()]
        if forbidden:
            raise PipelineError(f"forward-looking columns left among the features: {forbidden}")
        log.info("  no target column is exposed as a feature")

    write_report("features", report)
    log.info("feature report written")


if __name__ == "__main__":
    main()
