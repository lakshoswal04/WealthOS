"""Behavioural features from what the investor actually did.

``monthly_history`` reconstructs a portfolio path by valuing *today's*
holdings back through price history. That is the right method for the
question the Risk page asks -- "how risky is what I hold now" -- but it is
the wrong method for behaviour, and the reconstruction says so itself:

    frame["turnover"] = 0.0
    frame["n_trades"] = 0.0

Quantities are held constant, so there is no trading to measure, and both
columns were hard-coded to zero. Every live user therefore reached the
clustering model looking like a buy-and-hold investor regardless of how they
actually behave, which biases the cluster assignment toward the passive
archetypes. ``docs/limitations.md`` records the symptom; this module removes
the cause where the data allows.

The ``transactions`` table is real. It is written by CSV import and by every
holdings mutation, and it carries the symbol, the direction, the quantity,
the price and the date. Turnover, trade frequency, contribution consistency
and funding rate are all directly observable from it.

What matters as much as the numbers is saying which is which. A feature
derived from recorded transactions is an observation; the same feature taken
from the reconstruction is an inference, and for turnover it is an inference
known to be biased to zero. Every feature returned here is labelled, and
``MIN_MONTHS_FOR_OBSERVED`` is the point below which the observed path is too
short to prefer. Nothing is invented: where neither source has anything to
say, the feature is reported absent rather than defaulted.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionType, User

__all__ = [
    "MIN_MONTHS_FOR_OBSERVED",
    "MIN_TRADES_FOR_OBSERVED",
    "OBSERVABLE_FEATURES",
    "observed_activity",
    "behavioural_provenance",
]

# Below this many distinct months of recorded transactions, the observed path
# is shorter than the reconstructed one and a turnover figure drawn from it
# would describe a few weeks rather than a habit.
MIN_MONTHS_FOR_OBSERVED = 6

# And below this many directional trades there is no trading pattern to see,
# only a handful of events.
MIN_TRADES_FOR_OBSERVED = 4

# The features the transaction record can speak to. Everything else in the
# clustering vector describes the portfolio's present state -- allocations,
# concentration, holding count -- which the reconstruction gets right because
# it reads today's holdings directly.
OBSERVABLE_FEATURES = (
    "turnover",
    "trades_per_month",
    "contribution_consistency",
    "contribution_rate",
    "allocation_volatility",
)

_DIRECTIONAL = (TransactionType.BUY, TransactionType.SELL)
_FLOWS = (TransactionType.CONTRIBUTION, TransactionType.WITHDRAWAL)


def _transactions(db: Session, user: User) -> list[Transaction]:
    return list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == user.id)
            .order_by(Transaction.date)
        ).all()
    )


def observed_activity(db: Session, user: User) -> pd.DataFrame:
    """Monthly trading and funding activity, as recorded.

    One row per month in which anything happened, with:

    ``traded_value``   the sum of buy and sell values. Turnover is derived
                       from the smaller of the two sides elsewhere; here both
                       are kept so the caller can choose.
    ``bought``/``sold`` the two sides separately.
    ``n_trades``       count of directional transactions.
    ``net_flow``       contributions less withdrawals.

    An empty frame means no transactions, which is different from a month of
    zero activity and is left for the caller to distinguish.
    """
    rows = _transactions(db, user)
    if not rows:
        return pd.DataFrame()

    records = []
    for entry in rows:
        stamp = pd.Timestamp(entry.date) + pd.offsets.MonthEnd(0)
        value = float(entry.value or 0.0)
        records.append({
            "month": stamp,
            "bought": value if entry.transaction_type == TransactionType.BUY else 0.0,
            "sold": value if entry.transaction_type == TransactionType.SELL else 0.0,
            "n_trades": 1.0 if entry.transaction_type in _DIRECTIONAL else 0.0,
            "net_flow": (
                value if entry.transaction_type == TransactionType.CONTRIBUTION
                else -value if entry.transaction_type == TransactionType.WITHDRAWAL
                else 0.0
            ),
        })

    frame = pd.DataFrame(records).groupby("month", as_index=False).sum()
    frame["traded_value"] = frame["bought"] + frame["sold"]
    return frame.sort_values("month").reset_index(drop=True)


def _observed_features(
    activity: pd.DataFrame, history: pd.DataFrame
) -> tuple[dict[str, float], dict]:
    """Behavioural features computed from recorded activity.

    Turnover uses the smaller of total buys and total sells over the window,
    divided by average portfolio value. Taking the smaller side is the
    standard convention and it matters here: a year of pure accumulation is
    not high turnover, however much was bought.
    """
    if activity.empty:
        return {}, {"months": 0, "trades": 0}

    span = pd.period_range(
        activity["month"].min().to_period("M"),
        activity["month"].max().to_period("M"),
        freq="M",
    )
    elapsed = max(len(span), 1)
    n_trades = float(activity["n_trades"].sum())

    average_value = float(history["total_value"].mean()) if not history.empty else 0.0
    bought = float(activity["bought"].sum())
    sold = float(activity["sold"].sum())
    years = elapsed / 12.0

    features: dict[str, float] = {}
    if average_value > 0 and years > 0:
        features["turnover"] = min(bought, sold) / average_value / years
    features["trades_per_month"] = n_trades / elapsed

    funded = int((activity["net_flow"] > 0).sum())
    features["contribution_consistency"] = funded / elapsed
    if average_value > 0:
        total_in = float(activity.loc[activity["net_flow"] > 0, "net_flow"].sum())
        features["contribution_rate"] = total_in / average_value / max(years, 1e-9)

    context = {
        "months": elapsed,
        "months_with_activity": int(len(activity)),
        "trades": int(n_trades),
        "first_month": str(activity["month"].min().date()),
        "last_month": str(activity["month"].max().date()),
    }
    return features, context


def behavioural_provenance(
    db: Session,
    user: User,
    reconstructed: dict[str, float],
    history: pd.DataFrame,
) -> tuple[dict[str, float], dict]:
    """Merge observed behaviour over reconstructed, and say which is which.

    Returns ``(features, provenance)``. ``features`` is the reconstructed
    vector with observed values substituted where the transaction record is
    long enough to prefer them. ``provenance`` labels every observable
    feature and carries a confidence score.

    The confidence is not a probability and is not presented as one. It is
    the share of the reconstructed history that the transaction record
    covers, capped at 1.0: a user with three years of price history and three
    months of recorded trades gets a low number, which is the honest summary
    of how much the observed figures can be trusted to describe a habit.
    """
    activity = observed_activity(db, user)
    observed, context = _observed_features(activity, history)

    enough_months = context.get("months", 0) >= MIN_MONTHS_FOR_OBSERVED
    enough_trades = context.get("trades", 0) >= MIN_TRADES_FOR_OBSERVED

    features = dict(reconstructed)
    labels: dict[str, str] = {}

    for name in OBSERVABLE_FEATURES:
        if name == "allocation_volatility":
            # Not observable from transactions alone: it needs a valued
            # allocation path, which only the reconstruction provides.
            labels[name] = "reconstructed" if name in features else "unavailable"
            continue

        if name in observed and enough_months and (
            enough_trades or name in ("contribution_consistency", "contribution_rate")
        ):
            features[name] = float(observed[name])
            labels[name] = "observed"
        elif name in features:
            labels[name] = "reconstructed"
        else:
            labels[name] = "unavailable"

    months_of_history = int(len(history))
    coverage = (
        min(1.0, context.get("months", 0) / months_of_history)
        if months_of_history else 0.0
    )

    observed_count = sum(1 for v in labels.values() if v == "observed")
    provenance = {
        "sources": labels,
        "observed_feature_count": observed_count,
        "observable_feature_count": len(OBSERVABLE_FEATURES),
        "confidence": round(float(coverage), 3),
        "confidence_basis": (
            "The share of the reconstructed price history that the recorded "
            "transactions cover. It is not a probability: it says how much of "
            "the period the observed figures actually describe."
        ),
        "transaction_record": context,
        "thresholds": {
            "min_months_for_observed": MIN_MONTHS_FOR_OBSERVED,
            "min_trades_for_observed": MIN_TRADES_FOR_OBSERVED,
        },
        "note": (
            "Features marked `reconstructed` come from valuing today's "
            "holdings back through price history, which holds quantities "
            "fixed. Turnover and trade frequency are therefore biased "
            "towards zero under that method, and a profile built mostly from "
            "reconstructed features will tend towards the passive archetypes "
            "whatever the investor actually does."
            if observed_count == 0 else
            f"{observed_count} of {len(OBSERVABLE_FEATURES)} behavioural "
            "features come from recorded transactions; the rest are "
            "reconstructed and biased towards passive behaviour."
        ),
    }
    return features, provenance
