"""The shared assumptions, pinned.

`constants.py` opens by promising that "every assumption that affects a
reported number lives here so it can be cited in the project report and
changed in exactly one place". These tests hold it to that: a value that
drifts, or a second definition appearing elsewhere, fails here.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import wealthos_core as core
from wealthos_core import constants as C

REPO = pathlib.Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# The benchmark
# --------------------------------------------------------------------------

def test_benchmark_symbol_is_the_symbol_not_the_display_name():
    """`NIFTY50` is the key in the `assets` table; `NIFTY 50` is the label.

    This constant read "NIFTY 50" until Phase 1. No asset has that symbol, so
    a lookup returns nothing: the benchmark series comes back empty and beta
    and alpha are NaN, with no error raised anywhere. The spelling is the
    whole defect, so it is asserted exactly.
    """
    assert C.BENCHMARK_SYMBOL == "NIFTY50"
    assert C.BENCHMARK_NAME == "NIFTY 50"
    assert " " not in C.BENCHMARK_SYMBOL


def test_benchmark_symbol_is_exported_from_the_package_root():
    # Callers import from `wealthos_core`, not `wealthos_core.constants`.
    assert core.BENCHMARK_SYMBOL == C.BENCHMARK_SYMBOL
    assert core.BENCHMARK_NAME == C.BENCHMARK_NAME


@pytest.mark.parametrize("module", [
    "backend/app/services/risk_service.py",
    "backend/app/ml_runtime/features.py",
    "ml/pipelines/p07_features.py",
])
def test_no_module_hardcodes_the_benchmark_symbol(module):
    """Every price-panel consumer must import the constant, not retype it.

    Four modules each had their own copy of this string, and one of them
    disagreed with the others. Docstrings and UI labels are exempt — those
    are prose, and `BENCHMARK_NAME` covers the display case.
    """
    source = (REPO / module).read_text()
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    assert '"NIFTY50"' not in code, (
        f"{module} hardcodes the benchmark symbol; import BENCHMARK_SYMBOL "
        "from wealthos_core instead"
    )


# --------------------------------------------------------------------------
# Minimum data requirements
# --------------------------------------------------------------------------

def test_the_risk_floor_is_sixty_trading_days():
    """Pinned at 60, which is what every published figure was computed with.

    The old comment claimed "a year of daily observations is the minimum"
    directly above a constant of 60 — roughly three months. The constant was
    the truth and the comment was aspiration; raising the floor to 252 would
    silently invalidate the project's existing numbers, so the comment was
    corrected instead and the real minimum documented.
    """
    assert C.MIN_OBSERVATIONS_FOR_RISK == 60


def test_the_reliability_threshold_is_a_full_trading_year():
    assert C.RELIABLE_OBSERVATIONS_FOR_RISK == C.TRADING_DAYS_PER_YEAR == 252


def test_the_floor_is_below_the_reliability_threshold():
    # Otherwise no window could ever be labelled "provisional".
    assert C.MIN_OBSERVATIONS_FOR_RISK < C.RELIABLE_OBSERVATIONS_FOR_RISK


def test_symbol_coverage_threshold_is_ninety_percent():
    assert C.MIN_SYMBOL_COVERAGE == 0.9
    assert 0.0 < C.MIN_SYMBOL_COVERAGE < 1.0


# --------------------------------------------------------------------------
# Rates and periods
# --------------------------------------------------------------------------

def test_risk_free_rate_is_six_percent():
    """An assumption, not an observation — every Sharpe figure depends on it."""
    assert C.DEFAULT_RISK_FREE_RATE == 0.06


def test_cash_annual_return_is_five_point_five_percent():
    assert C.CASH_ANNUAL_RETURN == 0.055


def test_periods_per_year_annualisation_factors():
    # Each entry must be the number of periods of that length in one year.
    assert C.PERIODS_PER_YEAR == {
        "daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4, "annual": 1,
    }


def test_asset_classes_and_liquidity_scores_cover_the_same_set():
    # A class present in one and absent from the other silently scores as
    # missing in the Health Score's liquidity component.
    assert set(C.ASSET_CLASSES) == set(C.ASSET_CLASS_LIQUIDITY)


def test_liquidity_scores_are_ordered_cash_first_equity_last():
    scores = C.ASSET_CLASS_LIQUIDITY
    assert scores["cash"] == 1.00
    assert scores["equity"] == 0.70
    assert scores["cash"] == max(scores.values())
    assert scores["equity"] == min(scores.values())
