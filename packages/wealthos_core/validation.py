"""Purged walk-forward validation and cross-sectional signal metrics.

A swing label dated ``t`` looks ``horizon`` sessions into the future. If a
training row's label window overlaps the test block, the model has been
trained on the very returns it is then scored on. Purging removes those rows;
an extra embargo gap guards against slower leaks (volatility clustering,
serial correlation in the features).

The monthly ``ml/pipelines/walkforward.py`` serves the investor-cohort
forecasts; this module serves daily, cross-sectional market models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

__all__ = [
    "Fold",
    "yearly_folds",
    "daily_rank_ic",
    "ic_summary",
    "hit_rates",
    "decile_spread",
    "signal_report",
]


@dataclass(frozen=True)
class Fold:
    index: int
    test_year: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp      # last date a training row may carry
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_train_dates: int
    n_test_dates: int

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("train_start", "train_end", "test_start", "test_end"):
            d[k] = str(pd.Timestamp(d[k]).date())
        return d


def yearly_folds(
    dates: pd.DatetimeIndex | pd.Series,
    first_test_year: int,
    last_test_year: int | None = None,
    horizon: int = 10,
    embargo: int = 5,
    min_train_years: float = 3.0,
) -> list[Fold]:
    """Expanding-window folds with one calendar year per test block.

    The last training date sits ``horizon + embargo`` sessions before the test
    block starts, so no training label window reaches into the test year.
    """
    sessions = pd.DatetimeIndex(sorted(pd.unique(pd.DatetimeIndex(dates))))
    if len(sessions) == 0:
        return []
    last_test_year = last_test_year or int(sessions[-1].year)
    gap = horizon + embargo
    folds: list[Fold] = []
    for year in range(first_test_year, last_test_year + 1):
        in_year = np.flatnonzero(sessions.year == year)
        if len(in_year) == 0:
            continue
        start_pos = int(in_year[0])
        train_end_pos = start_pos - gap - 1
        if train_end_pos <= 0:
            continue
        train_span = (sessions[train_end_pos] - sessions[0]).days / 365.25
        if train_span < min_train_years:
            continue
        folds.append(Fold(
            index=len(folds),
            test_year=year,
            train_start=sessions[0],
            train_end=sessions[train_end_pos],
            test_start=sessions[start_pos],
            test_end=sessions[int(in_year[-1])],
            n_train_dates=train_end_pos + 1,
            n_test_dates=len(in_year),
        ))
    return folds


def daily_rank_ic(frame: pd.DataFrame, score: str = "score", target: str = "excess") -> pd.Series:
    """Spearman correlation between score and realised target, per date.

    Vectorised (ranks, then a Pearson correlation of the ranks per date):
    hyperparameter search calls this hundreds of times.
    """
    data = frame[[score, target]].dropna()
    key = data.index.get_level_values("date") if "date" in (data.index.names or []) else frame.loc[data.index, "date"]
    ranks = data.groupby(key).rank()
    g = ranks.groupby(key)
    a = ranks[score] - g[score].transform("mean")
    b = ranks[target] - g[target].transform("mean")
    num = (a * b).groupby(key).sum()
    den = np.sqrt((a * a).groupby(key).sum() * (b * b).groupby(key).sum())
    count = data.groupby(key).size()
    ic = (num / den.replace(0, np.nan)).where(count >= 5)
    ic.index.name = "date"
    return ic.dropna()


def ic_summary(ic: pd.Series, horizon: int = 10) -> dict:
    """Mean IC with a t-statistic corrected for overlapping labels.

    Consecutive daily ICs share ``horizon - 1`` days of their label windows,
    so they are far from independent; dividing the sample size by the horizon
    is the standard, conservative correction.
    """
    ic = ic.dropna()
    if ic.empty:
        return {"mean_ic": None, "ic_std": None, "ic_ir": None, "t_stat": None,
                "pct_positive": None, "days": 0}
    mean, std = float(ic.mean()), float(ic.std(ddof=1))
    effective = max(len(ic) / horizon, 1.0)
    return {
        "mean_ic": mean,
        "ic_std": std,
        "ic_ir": mean / std if std > 0 else None,
        "t_stat": mean / std * np.sqrt(effective) if std > 0 else None,
        "pct_positive": float((ic > 0).mean()),
        "days": int(len(ic)),
    }


def _by_date(frame: pd.DataFrame):
    return frame.groupby(level="date") if "date" in (frame.index.names or []) else frame.groupby("date")


def hit_rates(frame: pd.DataFrame, score: str = "score", target: str = "excess",
              raw: str = "fwd_ret") -> dict:
    """Directional accuracy, the figure people usually mean by "accuracy".

    ``relative``: did stocks scored above the day's median beat the universe
    (and those below lag it)? Coin-flip is 50%.
    ``top_decile_positive``: share of top-decile picks with a positive raw
    10-day return.
    ``top_decile_beat_universe``: share of top-decile picks that beat the mean.
    """
    def one(g: pd.DataFrame) -> pd.Series:
        above = g[score] > g[score].median()
        right = np.where(above, g[target] > 0, g[target] <= 0)
        top = g[score] >= g[score].quantile(0.9)
        return pd.Series({
            "relative": float(np.mean(right)),
            "top_pos": float((g.loc[top, raw] > 0).mean()) if raw in g and top.any() else np.nan,
            "top_beat": float((g.loc[top, target] > 0).mean()) if top.any() else np.nan,
        })

    per_day = _by_date(frame).apply(one)
    return {
        "relative": float(per_day["relative"].mean()),
        "top_decile_positive": float(per_day["top_pos"].mean()),
        "top_decile_beat_universe": float(per_day["top_beat"].mean()),
    }


def decile_spread(frame: pd.DataFrame, score: str = "score", target: str = "excess") -> dict:
    """Mean target of the top decile minus the bottom decile, per date."""
    def one(g: pd.DataFrame) -> pd.Series:
        hi = g[score] >= g[score].quantile(0.9)
        lo = g[score] <= g[score].quantile(0.1)
        return pd.Series({"top": g.loc[hi, target].mean(), "bottom": g.loc[lo, target].mean()})

    per_day = _by_date(frame).apply(one).dropna()
    spread = per_day["top"] - per_day["bottom"]
    return {
        "top_decile_mean_excess": float(per_day["top"].mean()),
        "bottom_decile_mean_excess": float(per_day["bottom"].mean()),
        "spread_per_period": float(spread.mean()),
        "spread_positive_share": float((spread > 0).mean()),
    }


def signal_report(frame: pd.DataFrame, horizon: int = 10, score: str = "score") -> dict:
    """IC, hit rates and decile spread for scored rows (index date, symbol)."""
    ic = daily_rank_ic(frame, score=score)
    by_year = ic.groupby(pd.DatetimeIndex(ic.index).year).mean()
    return {
        **ic_summary(ic, horizon),
        "ic_by_year": {int(y): float(v) for y, v in by_year.items()},
        "hit_rate": hit_rates(frame, score=score),
        "deciles": decile_spread(frame, score=score),
    }
