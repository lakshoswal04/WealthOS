"""Walk-forward folds and their summary.

These replace a single 18-month validation block as the basis for every skill
claim, so the fold construction has to be right: a fold that leaks future
months into its training window would manufacture skill out of nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.pipelines.walkforward import (
    Fold, fold_summary, make_folds, walk_forward_score,
)


def _months(n: int, start: str = "2012-01-31") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="ME"))


# --------------------------------------------------------------------------
# Fold construction
# --------------------------------------------------------------------------

def test_folds_are_built_over_the_requested_shape():
    folds = make_folds(_months(121), n_folds=6, score_months=6, min_train_months=36)
    assert len(folds) == 6
    for fold in folds:
        assert fold.n_score_months == 6


def test_the_training_window_never_reaches_past_its_boundary():
    """The property that makes the whole thing valid.

    A fold that trained on a month it then scored would report skill it did
    not have, and the failure would look like success.
    """
    for fold in make_folds(_months(121)):
        assert fold.train_end < fold.score_start, fold.as_dict()


def test_the_window_expands_rather_than_slides():
    """A forecaster deployed today has all of history available.

    Discarding the early years to keep folds equally sized would answer a
    question nobody is asking.
    """
    folds = make_folds(_months(121))
    sizes = [f.n_train_months for f in folds]
    assert sizes == sorted(sizes)
    assert sizes[-1] > sizes[0]


def test_folds_do_not_overlap_in_the_months_they_score():
    folds = make_folds(_months(121))
    for earlier, later in zip(folds, folds[1:]):
        assert earlier.score_end < later.score_start


def test_the_first_fold_respects_the_minimum_training_period():
    """A model fitted on two years of one regime describes that regime."""
    folds = make_folds(_months(121), min_train_months=36)
    assert folds[0].n_train_months >= 36


def test_too_little_history_yields_no_folds_rather_than_a_bad_one():
    # 30 months cannot support a 36-month minimum plus a 6-month score window.
    assert make_folds(_months(30), min_train_months=36, score_months=6) == []


def test_a_fold_describes_itself_for_the_report():
    fold = make_folds(_months(121))[0]
    body = fold.as_dict()
    assert set(body) == {
        "fold", "train_through", "scored_from", "scored_to",
        "train_months", "scored_months",
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _frame(n_months: int = 121, investors: int = 20, seed: int = 0):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2012-01-31", periods=n_months, freq="ME")
    rows = []
    for month_index, month in enumerate(months):
        # A market-level signal shared by every investor in the month, which
        # is the structure the real features have.
        market = np.sin(month_index / 7.0)
        for investor in range(investors):
            rows.append({
                "date": month, "investor_id": investor,
                "x": market + rng.normal(0, 0.05),
                "y": market * 0.5 + rng.normal(0, 0.1),
            })
    return pd.DataFrame(rows)


def test_a_perfect_predictor_scores_skill_near_one():
    frame = _frame()
    folds = make_folds(frame["date"])

    def oracle(_train, score):
        return score["y"].to_numpy()

    results = walk_forward_score(frame, folds, "y", oracle)
    assert results
    for row in results:
        assert row["skill_vs_mean"] > 0.99


def test_predicting_the_training_mean_scores_about_zero():
    """The reference the skill score is measured against."""
    frame = _frame()
    folds = make_folds(frame["date"])

    def constant(train, score):
        return np.full(len(score), train["y"].mean())

    for row in walk_forward_score(frame, folds, "y", constant):
        assert abs(row["skill_vs_mean"]) < 1e-9


def test_a_deliberately_bad_predictor_scores_negative():
    frame = _frame()
    folds = make_folds(frame["date"])

    def inverted(train, score):
        return -score["y"].to_numpy() + 2 * train["y"].mean()

    skills = [r["skill_vs_mean"] for r in walk_forward_score(frame, folds, "y", inverted)]
    assert all(s < 0 for s in skills), skills


def test_the_reference_mean_comes_from_the_training_window_only():
    """Using the scored months' own mean would be leakage dressed as a baseline."""
    frame = _frame()
    folds = make_folds(frame["date"])
    seen = []

    def spy(train, score):
        seen.append((train["date"].max(), score["date"].min()))
        return np.full(len(score), train["y"].mean())

    walk_forward_score(frame, folds, "y", spy)
    assert seen
    for train_end, score_start in seen:
        assert train_end < score_start


def test_each_fold_reports_what_it_scored():
    frame = _frame()
    results = walk_forward_score(
        frame, make_folds(frame["date"]), "y",
        lambda train, score: np.full(len(score), train["y"].mean()),
    )
    for row in results:
        assert row["rows_scored"] > 0
        assert row["mean_baseline_rmse"] > 0
        assert row["residual_std"] >= 0


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def test_the_summary_separates_consistent_skill_from_a_coin_flip():
    """The distinction the report exists to make.

    A mean skill of +0.01 drawn from folds of +0.30 and -0.28 is not a
    forecaster, and must not look like one that is mildly positive throughout.
    """
    lucky = fold_summary([
        {"skill_vs_mean": 0.30, "residual_std": 0.1},
        {"skill_vs_mean": -0.28, "residual_std": 0.1},
    ])
    steady = fold_summary([
        {"skill_vs_mean": 0.02, "residual_std": 0.1},
        {"skill_vs_mean": 0.01, "residual_std": 0.1},
    ])

    assert lucky["folds_beating_mean_baseline"] == 1
    assert lucky["beats_baseline_consistently"] is False
    assert lucky["beats_baseline_on_balance"] is False
    assert lucky["std_skill_vs_mean"] > steady["std_skill_vs_mean"] * 10

    assert steady["folds_beating_mean_baseline"] == 2
    assert steady["beats_baseline_consistently"] is True
    assert steady["beats_baseline_on_balance"] is True


def test_the_summary_reports_the_worst_fold_not_just_the_average():
    summary = fold_summary([
        {"skill_vs_mean": 0.4, "residual_std": 0.1},
        {"skill_vs_mean": -0.2, "residual_std": 0.1},
        {"skill_vs_mean": 0.1, "residual_std": 0.1},
    ])
    assert summary["worst_fold_skill"] == -0.2
    assert summary["best_fold_skill"] == 0.4
    assert summary["mean_skill_vs_mean"] == pytest.approx(0.1, abs=1e-9)


def test_an_empty_fold_list_is_reported_as_unusable_not_as_zero_skill():
    summary = fold_summary([])
    assert summary["usable"] is False
    assert summary["folds"] == 0
    assert "mean_skill_vs_mean" not in summary


def test_the_pooled_residual_std_is_a_quadratic_mean():
    # sqrt((0.1^2 + 0.3^2) / 2) = sqrt(0.05) = 0.2236
    summary = fold_summary([
        {"skill_vs_mean": 0.0, "residual_std": 0.1},
        {"skill_vs_mean": 0.0, "residual_std": 0.3},
    ])
    assert summary["pooled_residual_std"] == pytest.approx(0.223607, abs=1e-5)
