"""Behavioural features: observed where possible, labelled always.

The thing under test is honesty as much as arithmetic. A turnover figure
taken from the reconstruction is biased to zero by construction, so a
profile that mixes observed and inferred features without saying which is
which reports a behavioural verdict it cannot support.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.ml_runtime.behaviour import (
    MIN_MONTHS_FOR_OBSERVED,
    MIN_TRADES_FOR_OBSERVED,
    OBSERVABLE_FEATURES,
    behavioural_provenance,
    observed_activity,
)
from app.models import Asset, Transaction, TransactionType, User

# The schema enforces `ck_transactions_asset_required_for_trades`: a buy or
# sell must name an asset. Contributions and withdrawals must not, since they
# are cash movements rather than positions.
_TRADES = (TransactionType.BUY, TransactionType.SELL)


def _user(db):
    return db.query(User).first()


def _asset_id(db, symbol="RELIANCE"):
    return db.query(Asset).filter(Asset.symbol == symbol).one().id


def _add(db, user, kind, value, when, quantity=1.0, symbol="RELIANCE"):
    db.add(Transaction(
        user_id=user.id,
        asset_id=_asset_id(db, symbol) if kind in _TRADES else None,
        transaction_type=kind,
        date=when, quantity=quantity if kind in _TRADES else None,
        price=(value / max(quantity, 1e-9)) if kind in _TRADES else None,
        value=value, fees=0.0,
    ))
    db.commit()


@pytest.fixture
def account(client, auth, seeded_db):
    """A registered user holding a few positions, so history exists."""
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000), ("DEBT", 400, 50),
    ]:
        assert client.post("/api/v1/portfolio/holdings", headers=auth,
                           json={"symbol": symbol, "quantity": quantity,
                                 "average_price": price}).status_code == 201
    return seeded_db, _user(seeded_db), auth


# --------------------------------------------------------------------------
# observed_activity
# --------------------------------------------------------------------------

def test_no_transactions_gives_an_empty_frame_not_a_zero_row(account):
    """Absent is not the same as zero, and the caller has to be able to tell."""
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()
    assert observed_activity(db, user).empty


def test_activity_is_aggregated_by_month(account):
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    # Two buys in January, one sell in February.
    _add(db, user, TransactionType.BUY, 10_000.0, date(2026, 1, 5))
    _add(db, user, TransactionType.BUY, 5_000.0, date(2026, 1, 20))
    _add(db, user, TransactionType.SELL, 3_000.0, date(2026, 2, 11))

    activity = observed_activity(db, user)
    assert len(activity) == 2

    january = activity.iloc[0]
    assert january["bought"] == pytest.approx(15_000.0)
    assert january["sold"] == pytest.approx(0.0)
    assert january["n_trades"] == pytest.approx(2.0)
    # traded_value is both sides together: 15,000 + 0.
    assert january["traded_value"] == pytest.approx(15_000.0)

    february = activity.iloc[1]
    assert february["sold"] == pytest.approx(3_000.0)
    assert february["n_trades"] == pytest.approx(1.0)


def test_contributions_and_withdrawals_net_against_each_other(account):
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    _add(db, user, TransactionType.CONTRIBUTION, 8_000.0, date(2026, 3, 1))
    _add(db, user, TransactionType.WITHDRAWAL, 3_000.0, date(2026, 3, 15))

    activity = observed_activity(db, user)
    assert activity.iloc[0]["net_flow"] == pytest.approx(5_000.0)
    # A contribution is not a trade.
    assert activity.iloc[0]["n_trades"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Provenance labelling
# --------------------------------------------------------------------------

def test_every_observable_feature_gets_a_label(account):
    db, user, _ = account
    _, provenance = behavioural_provenance(
        db, user, {"turnover": 0.0, "trades_per_month": 0.0}, pd.DataFrame()
    )
    assert set(provenance["sources"]) == set(OBSERVABLE_FEATURES)
    for value in provenance["sources"].values():
        assert value in {"observed", "reconstructed", "unavailable"}


def test_a_thin_transaction_record_is_not_promoted_to_observed(account):
    """Two trades in one month describe an event, not a habit."""
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()
    _add(db, user, TransactionType.BUY, 10_000.0, date(2026, 1, 5))
    _add(db, user, TransactionType.SELL, 9_000.0, date(2026, 1, 20))

    reconstructed = {"turnover": 0.0, "trades_per_month": 0.0}
    features, provenance = behavioural_provenance(
        db, user, reconstructed, pd.DataFrame({"total_value": [100_000.0] * 24})
    )

    assert provenance["sources"]["turnover"] == "reconstructed"
    assert features["turnover"] == 0.0
    assert provenance["observed_feature_count"] == 0
    assert "biased" in provenance["note"]


def test_a_long_active_record_overrides_the_reconstruction(account):
    """The whole point: a real trader must not read as buy-and-hold.

    Twelve months of alternating buys and sells, against an average value of
    100,000. Buys total 120,000 and sells 120,000, so the smaller side is
    120,000 over one year on 100,000 of value -- a turnover of 1.2, which the
    reconstruction reports as 0.0.
    """
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    start = date(2025, 1, 15)
    for month in range(12):
        when = start + timedelta(days=30 * month)
        _add(db, user, TransactionType.BUY, 10_000.0, when)
        _add(db, user, TransactionType.SELL, 10_000.0, when + timedelta(days=5))

    history = pd.DataFrame({"total_value": [100_000.0] * 12})
    features, provenance = behavioural_provenance(
        db, user, {"turnover": 0.0, "trades_per_month": 0.0}, history
    )

    assert provenance["sources"]["turnover"] == "observed"
    assert provenance["sources"]["trades_per_month"] == "observed"
    assert features["turnover"] > 1.0, features["turnover"]
    assert features["trades_per_month"] > 1.0
    assert provenance["transaction_record"]["trades"] == 24


def test_turnover_uses_the_smaller_side_so_accumulation_is_not_churn(account):
    """A year of buying and never selling is not high turnover."""
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    start = date(2025, 1, 15)
    for month in range(12):
        _add(db, user, TransactionType.BUY, 10_000.0,
             start + timedelta(days=30 * month))

    history = pd.DataFrame({"total_value": [100_000.0] * 12})
    features, provenance = behavioural_provenance(
        db, user, {"turnover": 0.0}, history
    )

    # min(bought=120_000, sold=0) is 0, so turnover is 0 despite 12 trades.
    assert features["turnover"] == pytest.approx(0.0)
    assert provenance["transaction_record"]["trades"] == 12


def test_contribution_consistency_is_observed_without_needing_trades(account):
    """Funding regularly is behaviour even from someone who never trades.

    The trade threshold must not gate the contribution features, or a
    disciplined passive saver would have their real funding record discarded
    in favour of an inference.
    """
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    start = date(2025, 1, 10)
    for month in range(12):
        _add(db, user, TransactionType.CONTRIBUTION, 5_000.0,
             start + timedelta(days=30 * month))

    history = pd.DataFrame({"total_value": [100_000.0] * 12})
    features, provenance = behavioural_provenance(
        db, user, {"contribution_consistency": 0.0}, history
    )

    assert provenance["sources"]["contribution_consistency"] == "observed"
    assert features["contribution_consistency"] > 0.9
    # No directional trades at all, so trade-gated features are not observed.
    # The reconstructed dict passed in has no turnover either, so the label is
    # "unavailable" rather than "reconstructed" -- absent, not inferred.
    assert provenance["transaction_record"]["trades"] == 0
    assert provenance["sources"]["turnover"] == "unavailable"


def test_allocation_volatility_is_never_claimed_as_observed(account):
    """It needs a valued allocation path, which transactions alone cannot give."""
    db, user, _ = account
    _, provenance = behavioural_provenance(
        db, user, {"allocation_volatility": 0.03},
        pd.DataFrame({"total_value": [100_000.0] * 24}),
    )
    assert provenance["sources"]["allocation_volatility"] == "reconstructed"


def test_confidence_is_the_share_of_history_the_record_covers(account):
    """Six months of trades against two years of prices is not full confidence."""
    db, user, _ = account
    db.query(Transaction).delete()
    db.commit()

    start = date(2025, 7, 10)
    for month in range(6):
        when = start + timedelta(days=30 * month)
        _add(db, user, TransactionType.BUY, 10_000.0, when)
        _add(db, user, TransactionType.SELL, 10_000.0, when + timedelta(days=4))

    history = pd.DataFrame({"total_value": [100_000.0] * 24})
    _, provenance = behavioural_provenance(db, user, {"turnover": 0.0}, history)

    # 6 months of record over 24 months of history.
    assert provenance["confidence"] == pytest.approx(6 / 24, abs=0.05)
    assert 0.0 < provenance["confidence"] < 1.0
    assert "not a probability" in provenance["confidence_basis"]


def test_the_thresholds_are_reported_so_the_rule_is_inspectable(account):
    db, user, _ = account
    _, provenance = behavioural_provenance(db, user, {}, pd.DataFrame())
    assert provenance["thresholds"] == {
        "min_months_for_observed": MIN_MONTHS_FOR_OBSERVED,
        "min_trades_for_observed": MIN_TRADES_FOR_OBSERVED,
    }


# --------------------------------------------------------------------------
# The reconstruction itself no longer reports a constant zero
# --------------------------------------------------------------------------

def test_monthly_history_reports_real_trading_activity(account):
    """turnover and n_trades were hard-coded to 0.0 for every live user.

    That is a train/serve mismatch, not just a gap: the anomaly detector was
    fitted on a cohort where turnover varies and was served a column that was
    always zero.

    Note what this test had to do to exist. Creating a holding does not write
    a transaction -- only POST /transactions and, since Phase 4, a dated CSV
    import do -- so the trades have to be recorded explicitly.
    """
    from app.ml_runtime.features import monthly_history

    db, user, _ = account
    history = monthly_history(db, user)
    if history.empty:
        pytest.skip("no reconstructable history for this fixture")

    month_ends = set(pd.to_datetime(history["date"]))
    assert month_ends, "no month ends in the reconstructed history"
    when = max(month_ends).date()

    _add(db, user, TransactionType.BUY, 25_000.0, when, quantity=25.0)
    refreshed = monthly_history(db, user)

    assert refreshed["n_trades"].sum() > 0, "the recorded trade never reached the frame"
    assert refreshed["turnover"].sum() == pytest.approx(25_000.0)


def test_a_dated_csv_import_records_its_purchases(client, auth):
    """The onboarding path has to populate the behavioural record.

    Before Phase 4, nothing but POST /transactions wrote to the table, so a
    user who onboarded by CSV -- the documented route -- had no transaction
    history at all, and every behavioural feature was inferred.
    """
    csv_body = (
        "symbol,quantity,average_price,purchase_date\n"
        "RELIANCE,20,1000,2024-03-15\n"
        "TCS,10,3000,2024-05-20\n"
    )
    response = client.post(
        "/api/v1/portfolio/import", headers=auth,
        files={"file": ("holdings.csv", csv_body, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] is True

    recorded = client.get("/api/v1/portfolio/transactions", headers=auth).json()
    buys = [t for t in recorded if t["transaction_type"] == "buy"]
    assert len(buys) == 2
    assert {t["symbol"] for t in buys} == {"RELIANCE", "TCS"}
    assert {t["date"] for t in buys} == {"2024-03-15", "2024-05-20"}


def test_an_undated_csv_import_invents_no_history(client, auth):
    """A holding of unknown vintage is not a purchase made today."""
    csv_body = "symbol,quantity,average_price\nRELIANCE,20,1000\n"
    response = client.post(
        "/api/v1/portfolio/import", headers=auth,
        files={"file": ("holdings.csv", csv_body, "text/csv")},
    )
    assert response.status_code == 200, response.text

    recorded = client.get("/api/v1/portfolio/transactions", headers=auth).json()
    assert [t for t in recorded if t["transaction_type"] == "buy"] == []
    # And the user is told why their behavioural analysis will be inferred.
    assert any("no transaction history was recorded" in w
               for w in response.json()["warnings"])


def test_the_profile_endpoint_exposes_provenance(client, auth):
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000), ("DEBT", 400, 50),
    ]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity,
                          "average_price": price})

    body = client.get("/api/v1/profile", headers=auth).json()
    if not body.get("available"):
        pytest.skip(f"profile unavailable: {body.get('reason')}")

    provenance = body["feature_provenance"]
    assert set(provenance["sources"]) == set(OBSERVABLE_FEATURES)
    assert 0.0 <= provenance["confidence"] <= 1.0
    # The old blanket caveat claimed everything was reconstructed; the new one
    # has to point at the per-feature record instead.
    assert "feature_provenance" in body["caveat"]
