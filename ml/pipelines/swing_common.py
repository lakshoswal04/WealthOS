"""Shared plumbing for the swing-trading stages (13-19).

Loading, the fold design, baselines and the deployment gate live here so
every stage evaluates on identical splits with identical rules.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.backtest_xs import BacktestResult, rank_portfolio_backtest
from wealthos_core.validation import Fold, yearly_folds

from .common import MODEL_DIR, PROCESSED_DIR, REFERENCE_DIR, PipelineError

RANDOM_STATE = 42
HISTORY = PROCESSED_DIR / "history_daily.parquet"
FEATURES_PATH = PROCESSED_DIR / "features_swing.parquet"
TARGETS_PATH = PROCESSED_DIR / "targets_swing.parquet"
OOS_PATH = PROCESSED_DIR / "swing_oos_scores.parquet"
VOL_OOS_PATH = PROCESSED_DIR / "swing_oos_vol.parquet"
REGIME_OOS_PATH = PROCESSED_DIR / "swing_oos_regime.parquet"

START = "2007-01-01"          # NIFTY on Yahoo begins 2007-09; a year of warm-up after that
FIRST_TEST_YEAR = 2013
TUNING_YEARS = (2011, 2012)   # hyperparameters are chosen here and frozen before 2013
EMBARGO = 5
TOP_N = 10
REBALANCE_EVERY = 5
BUFFER = 20

MODEL_VERSION = "1.0.0"


def sectors() -> dict[str, str]:
    return pd.read_csv(REFERENCE_DIR / "nifty100.csv").set_index("symbol")["sector"].to_dict()


def load_wide() -> sf.Wide:
    if not HISTORY.exists():
        raise PipelineError(f"{HISTORY.name} missing; run p13_fetch_history first")
    panel = pd.read_parquet(HISTORY)
    panel = panel.loc[panel["date"] >= START]
    return sf.to_wide(panel)


def load_panel() -> pd.DataFrame:
    """Features joined to targets, index (date, symbol)."""
    if not FEATURES_PATH.exists() or not TARGETS_PATH.exists():
        raise PipelineError("swing feature tables missing; run p14_build_swing_features first")
    f = pd.read_parquet(FEATURES_PATH)
    y = pd.read_parquet(TARGETS_PATH)
    return f.join(y, how="inner").sort_index()


def folds(dates: pd.Index, first_test_year: int = FIRST_TEST_YEAR) -> list[Fold]:
    return yearly_folds(pd.DatetimeIndex(dates), first_test_year=first_test_year,
                        horizon=sf.HORIZON, embargo=EMBARGO, min_train_years=3.0)


def date_level(frame: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(frame.index.get_level_values("date"))


def backtest_scores(scores: pd.Series, w: sf.Wide, start: str | pd.Timestamp, **kwargs) -> BacktestResult:
    """Top-10, weekly, buffered, cost-aware backtest of a (date, symbol) score series."""
    wide = scores.unstack("symbol").reindex(index=w.close.index, columns=w.close.columns)
    params = {"top_n": TOP_N, "rebalance_every": REBALANCE_EVERY, "buffer": BUFFER}
    params.update(kwargs)
    return rank_portfolio_backtest(wide, w.open, w.close, start=start, **params)


def benchmarks(w: sf.Wide, start: str | pd.Timestamp) -> dict[str, BacktestResult | pd.Series]:
    """Equal-weight of the eligible universe (costs included) and NIFTY price index."""
    eligible = sf.eligibility(w)
    ew = rank_portfolio_backtest(eligible.astype(float).where(eligible), w.open, w.close,
                                 top_n=None, rebalance_every=REBALANCE_EVERY, buffer=None, start=start)
    nifty = w.index_close.loc[pd.Timestamp(start):].pct_change().dropna() if w.index_close is not None else None
    return {"equal_weight": ew, "nifty": nifty}


def series_summary(r: pd.Series) -> dict:
    from wealthos_core.metrics import performance_summary

    s = performance_summary(r, risk_free_rate=0.0)
    return {"cagr": s["annualized_return"], "volatility": s["annualized_volatility"],
            "sharpe": s["sharpe_ratio"], "max_drawdown": s["max_drawdown"]}


def curve_of(r: pd.Series, every: int = 5) -> list[dict]:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    pts = eq.iloc[::every]
    if len(eq) and pts.index[-1] != eq.index[-1]:
        pts = pd.concat([pts, eq.iloc[[-1]]])
    return [{"date": str(d.date()), "value": round(float(v), 5)} for d, v in pts.items()]


def gate(signal: dict, momentum_ic: float | None, book: dict, ew_book: dict) -> dict:
    """The deployment rule, recorded with the numbers that decided it."""
    ic = signal.get("mean_ic") or 0.0
    checks = {
        "ic_positive": ic > 0,
        "ic_beats_momentum": momentum_ic is None or ic > momentum_ic,
        "cagr_beats_equal_weight_after_costs": (book.get("cagr") or -1) > (ew_book.get("cagr") or 0),
        "drawdown_within_1_2x_equal_weight": (book.get("max_drawdown") or -1) >= 1.2 * (ew_book.get("max_drawdown") or 0),
    }
    return {"recommended": all(checks.values()), "checks": checks}


def clean_json(obj):
    """Floats to plain floats, NaN to None, so reports and API payloads are valid JSON."""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if np.isnan(f) or np.isinf(f) else round(f, 6)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def model_path(name: str):
    return MODEL_DIR / name
