"""Concentration measures checked against hand-computed values."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from wealthos_core import concentration as C


def test_hhi_of_a_single_holding_is_one():
    assert C.herfindahl_index({"RELIANCE": 100.0}) == pytest.approx(1.0)


def test_hhi_of_four_equal_holdings_is_one_quarter():
    # Four weights of 0.25: 4 * 0.25^2 = 0.25, which is 1/n.
    weights = {"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0}
    assert C.herfindahl_index(weights) == pytest.approx(0.25)


def test_hhi_hand_calculated_for_an_uneven_portfolio():
    # Weights 0.5, 0.3, 0.2 -> 0.25 + 0.09 + 0.04 = 0.38.
    assert C.herfindahl_index({"A": 0.5, "B": 0.3, "C": 0.2}) == pytest.approx(0.38)


def test_weights_are_normalised_before_squaring():
    # Raw values that do not sum to 1 must be rescaled first, so these two
    # portfolios -- identical in proportion -- score identically.
    assert C.herfindahl_index({"A": 50, "B": 30, "C": 20}) == pytest.approx(
        C.herfindahl_index({"A": 5000, "B": 3000, "C": 2000})
    )


def test_percentages_and_fractions_give_the_same_answer():
    assert C.herfindahl_index({"A": 40, "B": 60}) == pytest.approx(
        C.herfindahl_index({"A": 0.40, "B": 0.60})
    )


def test_normalized_hhi_is_zero_for_an_equal_weighted_portfolio():
    # The rescaled index removes the 1/n floor, so equal weighting scores 0
    # whether the portfolio holds 4 names or 40.
    four = {chr(65 + i): 1.0 for i in range(4)}
    forty = {str(i): 1.0 for i in range(40)}

    assert C.normalized_herfindahl_index(four) == pytest.approx(0.0, abs=1e-12)
    assert C.normalized_herfindahl_index(forty) == pytest.approx(0.0, abs=1e-12)


def test_normalized_hhi_is_one_for_a_single_holding():
    assert C.normalized_herfindahl_index({"A": 1.0}) == pytest.approx(1.0)


def test_raw_hhi_cannot_compare_across_sizes_but_normalized_hhi_can():
    # This is the reason the normalised form exists: an equal-weighted 4-stock
    # portfolio has a higher RAW hhi than an equal-weighted 40-stock one, yet
    # neither is concentrated relative to its own size.
    four = {chr(65 + i): 1.0 for i in range(4)}
    forty = {str(i): 1.0 for i in range(40)}

    assert C.herfindahl_index(four) > C.herfindahl_index(forty)
    assert C.normalized_herfindahl_index(four) == pytest.approx(
        C.normalized_herfindahl_index(forty), abs=1e-12
    )


def test_effective_holdings_of_equal_weights_equals_the_holding_count():
    weights = {chr(65 + i): 1.0 for i in range(10)}
    assert C.effective_number_of_holdings(weights) == pytest.approx(10.0)


def test_effective_holdings_exposes_hidden_concentration():
    # 20 names but 80% in one: the portfolio behaves like roughly 1.5 equally
    # weighted positions, not like 20.
    weights = {"BIG": 80.0}
    weights.update({f"S{i}": 20.0 / 19 for i in range(19)})

    effective = C.effective_number_of_holdings(weights)
    assert 1.0 < effective < 2.0


def test_top_k_weight_sums_the_largest_positions():
    weights = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}

    assert C.top_k_weight(weights, 1) == pytest.approx(0.5)
    assert C.top_k_weight(weights, 2) == pytest.approx(0.8)
    assert C.top_k_weight(weights, 10) == pytest.approx(1.0)  # k beyond n is clamped


def test_concentration_by_group_aggregates_sector_weights():
    weights = {"TCS": 0.3, "INFY": 0.2, "HDFCBANK": 0.5}
    sectors = {"TCS": "IT", "INFY": "IT", "HDFCBANK": "Financials"}

    by_sector = C.concentration_by_group(weights, sectors)

    assert by_sector["IT"] == pytest.approx(0.5)
    assert by_sector["Financials"] == pytest.approx(0.5)


def test_unmapped_holdings_become_unknown_rather_than_vanishing():
    # Dropping them would renormalise the rest to 1.0 and hide the gap.
    weights = {"TCS": 0.5, "MYSTERY": 0.5}
    sectors = {"TCS": "IT"}

    by_sector = C.concentration_by_group(weights, sectors)

    assert by_sector["Unknown"] == pytest.approx(0.5)
    assert by_sector.sum() == pytest.approx(1.0)


def test_concentration_report_covers_asset_sector_and_class():
    weights = {"TCS": 40.0, "INFY": 30.0, "GOLDBEES": 30.0}
    sectors = {"TCS": "IT", "INFY": "IT", "GOLDBEES": "Commodities"}
    classes = {"TCS": "equity", "INFY": "equity", "GOLDBEES": "gold"}

    report = C.concentration_report(weights, sectors, classes)

    assert report["n_holdings"] == 3
    assert report["largest_holding"] == "TCS"
    assert report["sector_weights"]["IT"] == pytest.approx(0.7)
    assert report["asset_class_weights"]["equity"] == pytest.approx(0.7)
    assert report["max_sector_weight"] == pytest.approx(0.7)


def test_negative_weights_are_excluded():
    # The MVP does not model short positions; a negative entry must not be
    # allowed to distort the normalising total.
    assert C.herfindahl_index({"A": 1.0, "B": -0.5}) == pytest.approx(1.0)


def test_empty_portfolio_returns_nan_not_an_error():
    assert math.isnan(C.herfindahl_index({}))
    assert math.isnan(C.effective_number_of_holdings({}))
