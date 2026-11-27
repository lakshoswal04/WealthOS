"""Walk-forward evaluation and hyperparameter search for the forecasts.

Why this module exists, in one measurement. The forecast features are
dominated by market-level variables that are identical for every investor in
a given month, and 47-63% of the target's variance is between-month rather
than between-investor. So the effective sample for a market-driven forecast
is the number of distinct months, not the number of rows:

    train        121 months     9,743 investors    675,724 rows
    validation    18 months     9,963 investors    177,884 rows
    test          29 months    10,000 investors    289,897 rows

Eighteen months is one small draw of market regimes. Early stopping against
it is early stopping against noise, which is exactly what happened: all four
XGBoost configurations stopped at iteration 0 with validation RMSE differing
in the fifth decimal place. That was read as "the model is barely trained".
It was the opposite -- early stopping was working correctly and declining to
fit a relationship that eighteen months could not confirm.

A ridge regression makes the same point from the other side: in-sample the
month-mean target correlates with market volatility at r = 0.24 to 0.52 over
121 months, significant at every horizon (t = 2.6 to 6.6), yet it generalises
to the validation block with *negative* skill at all four horizons. Real
signal, unmeasurable on one block.

Walk-forward folds are the fix. Instead of one 18-month judgement, the
training period is cut into several expanding-window folds, each training on
everything before a boundary and scoring the months after it. Ten judgements
over ten regimes is a usable signal where one was not, and the spread across
folds is itself the honest error bar on any skill claim.

The test split is never touched here. It is scored once, at the end, by the
caller.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = ["Fold", "make_folds", "walk_forward_score", "fold_summary"]


@dataclass(frozen=True)
class Fold:
    """One expanding-window fold, described by month boundaries."""

    index: int
    train_end: pd.Timestamp
    score_start: pd.Timestamp
    score_end: pd.Timestamp
    n_train_months: int
    n_score_months: int

    def as_dict(self) -> dict:
        return {
            "fold": self.index,
            "train_through": str(self.train_end.date()),
            "scored_from": str(self.score_start.date()),
            "scored_to": str(self.score_end.date()),
            "train_months": self.n_train_months,
            "scored_months": self.n_score_months,
        }


def make_folds(
    dates: pd.Series,
    n_folds: int = 6,
    score_months: int = 6,
    min_train_months: int = 36,
) -> list[Fold]:
    """Expanding-window folds over the distinct months in ``dates``.

    Each fold trains on everything up to a boundary and scores the next
    ``score_months``. The window expands rather than slides, because a
    forecaster deployed today would have all of history available, and
    discarding the early years to keep folds the same size would answer a
    question nobody is asking.

    ``min_train_months`` guards the first fold: a model fitted on two years
    of one market regime tells you about that regime, not about the method.
    """
    months = pd.Index(sorted(pd.to_datetime(pd.Series(dates)).dt.to_period("M").unique()))
    if len(months) < min_train_months + score_months:
        return []

    last_start = len(months) - score_months
    first_start = max(min_train_months, last_start - n_folds * score_months)
    starts = list(range(first_start, last_start + 1, score_months))[-n_folds:]

    folds = []
    for position, start in enumerate(starts):
        scored = months[start : start + score_months]
        folds.append(Fold(
            index=position,
            train_end=months[start - 1].to_timestamp(how="end").normalize(),
            score_start=scored[0].to_timestamp(how="start").normalize(),
            score_end=scored[-1].to_timestamp(how="end").normalize(),
            n_train_months=start,
            n_score_months=len(scored),
        ))
    return folds


def walk_forward_score(
    frame: pd.DataFrame,
    folds: list[Fold],
    target: str,
    fit_predict,
    date_column: str = "date",
) -> list[dict]:
    """Run ``fit_predict`` over each fold and report skill against the mean.

    ``fit_predict(train_frame, score_frame)`` returns predictions for
    ``score_frame``. Skill is measured against the training-period mean,
    which is the reference a forecaster has to beat to be worth running: the
    zero baseline flatters, because a portfolio receiving contributions grows
    on average and predicting zero excess growth is already wrong in a
    predictable direction.

    The mean reference is computed on each fold's own training window, never
    on the months being scored.
    """
    dates = pd.to_datetime(frame[date_column])
    results = []

    for fold in folds:
        train_mask = dates <= fold.train_end
        score_mask = (dates >= fold.score_start) & (dates <= fold.score_end)
        train_part = frame[train_mask]
        score_part = frame[score_mask]
        if train_part.empty or score_part.empty:
            continue

        actual = score_part[target].to_numpy(dtype="float64")
        reference = np.full(len(score_part), float(train_part[target].mean()))
        predicted = np.asarray(fit_predict(train_part, score_part), dtype="float64")

        model_rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
        reference_rmse = float(np.sqrt(np.mean((actual - reference) ** 2)))
        results.append({
            **fold.as_dict(),
            "rows_scored": int(len(score_part)),
            "model_rmse": round(model_rmse, 6),
            "mean_baseline_rmse": round(reference_rmse, 6),
            "skill_vs_mean": round(
                1.0 - model_rmse / reference_rmse if reference_rmse > 0 else 0.0, 4
            ),
            "residual_std": round(float(np.std(actual - predicted)), 6),
        })
    return results


def fold_summary(fold_results: list[dict]) -> dict:
    """Aggregate fold skills into a claim with an error bar on it.

    ``folds_won`` is the number that beat the mean baseline. It is reported
    alongside the average because an average skill of +0.01 drawn from folds
    of +0.30 and -0.28 is not a forecaster, it is a coin flip with extra
    steps, and the two cases must not look the same in a report.
    """
    if not fold_results:
        return {"folds": 0, "usable": False,
                "note": "not enough months to build walk-forward folds"}

    skills = np.array([r["skill_vs_mean"] for r in fold_results], dtype="float64")
    residual_stds = np.array([r["residual_std"] for r in fold_results], dtype="float64")
    won = int((skills > 0).sum())

    return {
        "folds": len(fold_results),
        "usable": True,
        "mean_skill_vs_mean": round(float(skills.mean()), 4),
        "median_skill_vs_mean": round(float(np.median(skills)), 4),
        "std_skill_vs_mean": round(float(skills.std()), 4),
        "worst_fold_skill": round(float(skills.min()), 4),
        "best_fold_skill": round(float(skills.max()), 4),
        "folds_beating_mean_baseline": won,
        "beats_baseline_consistently": bool(won == len(skills)),
        "beats_baseline_on_balance": bool(skills.mean() > 0 and won > len(skills) / 2),
        "pooled_residual_std": round(float(np.sqrt((residual_stds ** 2).mean())), 6),
        "per_fold": fold_results,
    }
