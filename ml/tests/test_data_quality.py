"""Data-quality gates on the processed market data.

These assert properties the pipeline promises. A failure here means the data
every model and every page is built on has a defect, so they are worth
running before any model result is believed.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml.pipelines.common import PROCESSED_DIR, REPORT_DIR, load_universe

pytestmark = pytest.mark.skipif(
    not (PROCESSED_DIR / "price_panel.parquet").exists(),
    reason="run the data pipeline first (ml/pipelines/p01…p04)",
)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")


@pytest.fixture(scope="module")
def universe() -> pd.DataFrame:
    return load_universe()


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------

def test_panel_is_indexed_by_a_sorted_unique_date(panel):
    assert isinstance(panel.index, pd.DatetimeIndex)
    assert panel.index.is_monotonic_increasing
    assert panel.index.is_unique


def test_every_price_is_positive(panel):
    # A zero or negative price is not a price; the ingest converts those
    # placeholders to missing.
    numeric = panel.to_numpy(dtype="float64")
    present = numeric[np.isfinite(numeric)]
    assert (present > 0).all()


def test_panel_covers_the_declared_simulation_window(panel):
    assert panel.index.min() <= pd.Timestamp("2012-01-05")
    # The data pull is from late 2026; allow slack rather than pinning a day.
    assert panel.index.max() >= pd.Timestamp("2026-06-01")


def test_every_asset_class_is_represented(panel, universe):
    priced = set(panel.columns)
    active = universe[universe.status == "active"]
    for asset_class in ("equity", "etf", "gold", "debt", "cash"):
        members = set(active.loc[active.asset_class == asset_class, "symbol"])
        assert members & priced, f"no priced asset in class {asset_class}"


# --------------------------------------------------------------------------
# Corporate actions — the defect that motivated the whole price pipeline
# --------------------------------------------------------------------------

def test_no_phantom_crash_survives_into_the_panel(panel):
    # The Kaggle source is unadjusted, so a 1:1 bonus reads as a -50% day.
    # Nothing of that magnitude may reach the panel.
    returns = panel.pct_change()
    extreme = (returns.abs() > 0.5).sum()
    offenders = extreme[extreme > 0]
    assert offenders.empty, f"implausible daily moves survived: {offenders.to_dict()}"


def test_reliance_bonus_date_is_adjusted(panel):
    # RELIANCE went ex-bonus on 2017-09-07 and the raw source shows -50.3%.
    # The panel starts in 2012, so the date is inside it.
    if "RELIANCE" not in panel.columns:
        pytest.skip("RELIANCE not priced")
    returns = panel["RELIANCE"].pct_change()
    window = returns.loc["2017-09-01":"2017-09-15"]
    assert window.abs().max() < 0.2


def test_benchmark_returns_are_realistic(panel):
    # A benchmark whose long-run figures are implausible means the splice or
    # the adjustment went wrong, however clean the series looks.
    if "NIFTY50" not in panel.columns:
        pytest.skip("benchmark not priced")
    returns = panel["NIFTY50"].pct_change().dropna()
    annual_return = (1 + returns).prod() ** (252 / len(returns)) - 1
    annual_vol = returns.std() * np.sqrt(252)

    assert 0.03 < annual_return < 0.25, f"benchmark return {annual_return:.1%} is implausible"
    assert 0.08 < annual_vol < 0.30, f"benchmark volatility {annual_vol:.1%} is implausible"


def test_cash_grows_steadily_and_never_falls(panel):
    if "CASH" not in panel.columns:
        pytest.skip("cash not priced")
    returns = panel["CASH"].pct_change().dropna()
    assert (returns >= -1e-12).all()
    assert returns.std() < 1e-9  # modelled at a constant rate


def test_debt_is_less_volatile_than_equity(panel):
    if not {"DEBT", "NIFTY50"} <= set(panel.columns):
        pytest.skip("debt or benchmark not priced")
    debt_vol = panel["DEBT"].pct_change().std()
    equity_vol = panel["NIFTY50"].pct_change().std()
    assert debt_vol < equity_vol


# --------------------------------------------------------------------------
# Splice evidence
# --------------------------------------------------------------------------

def test_splice_evidence_was_recorded_and_passed_its_gates():
    path = REPORT_DIR / "price_build.json"
    if not path.exists():
        pytest.skip("price build report not present")
    report = json.loads(path.read_text())

    benchmark = report["splices"]["NIFTY50"]
    assert benchmark["kind"] == "same_instrument"
    assert benchmark["return_correlation"] >= 0.95
    assert benchmark["overlap_days"] >= 30

    debt = report["splices"]["DEBT"]
    # A proxy handoff is a change of instrument, held to a lower bar and
    # labelled as such rather than passed off as a continuation.
    assert debt["kind"] == "proxy_handoff"
    assert debt["return_correlation"] >= 0.80
    assert 0.5 <= debt["vol_ratio"] <= 2.0


def test_adjustment_impact_was_quantified():
    path = REPORT_DIR / "adjustment_impact.json"
    if not path.exists():
        pytest.skip("adjustment impact report not present")
    summary = json.loads(path.read_text())

    # The report exists to justify not using the raw source. If it showed no
    # impact, that justification would be gone.
    assert summary["symbols_with_phantom_moves"] > 0
    assert summary["volatility_overstated_pp"]["max"] > 0


# --------------------------------------------------------------------------
# Synthetic cohort
# --------------------------------------------------------------------------

@pytest.mark.skipif(
    not (PROCESSED_DIR.parent / "synthetic" / "snapshots.parquet").exists(),
    reason="generate the cohort first (ml/pipelines/p06)",
)
class TestCohort:
    @pytest.fixture(scope="class")
    def snapshots(self) -> pd.DataFrame:
        path = PROCESSED_DIR.parent / "synthetic" / "snapshots.parquet"
        # A million rows is more than these checks need.
        return pd.read_parquet(path).sample(frac=0.1, random_state=0)

    def test_allocations_sum_to_one(self, snapshots):
        columns = [c for c in snapshots.columns if c.endswith("_allocation")]
        normal = snapshots[snapshots.is_anomaly == 0]
        totals = normal[columns].sum(axis=1)
        assert (totals - 1.0).abs().max() < 1e-6

    def test_no_portfolio_goes_negative(self, snapshots):
        assert (snapshots.total_value >= 0).all()

    def test_drawdown_is_never_positive(self, snapshots):
        assert snapshots.current_drawdown.max() <= 1e-9

    def test_archetypes_are_behaviourally_distinct(self, snapshots):
        # If the archetypes did not separate, clustering would have nothing
        # real to recover and its ARI would be meaningless.
        by_archetype = snapshots[snapshots.is_anomaly == 0].groupby("archetype")
        equity = by_archetype.equity_allocation.mean()
        turnover = by_archetype.turnover.mean()

        assert equity.max() - equity.min() > 0.3
        assert turnover.max() > turnover.min() * 5

    def test_anomalies_are_rare_and_labelled(self, snapshots):
        rate = snapshots.is_anomaly.mean()
        assert 0 < rate < 0.05, "anomalies should be rare, as they are in reality"
        flagged = snapshots[snapshots.is_anomaly == 1]
        assert (flagged.anomaly_type != "").all()

    def test_returns_resemble_a_real_market(self, snapshots):
        returns = snapshots[snapshots.is_anomaly == 0].period_return.dropna()
        returns = returns[returns.between(-0.6, 0.6)]
        annualised = returns.mean() * 12
        volatility = returns.std() * np.sqrt(12)

        assert 0.0 < annualised < 0.35
        assert 0.03 < volatility < 0.40
        # Equity markets fall faster than they rise.
        assert returns.skew() < 0.5
