"""Assembles the Portfolio Health Score from the analytics layer."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from wealthos_core.health import HealthInputs, compute_health_score, sensitivity_analysis
from wealthos_core.health_v2 import compute_health_score_v2
from app.models import Transaction, TransactionType, User
from app.services import goal_service, portfolio_service, risk_service
from app.services.market_service import market_cache

BEHAVIOUR_WINDOW_DAYS = 365

# Allocation drift needs at least this many month-end observations to mean
# anything: two points give one change, which is an event rather than a drift.
MIN_MONTHS_FOR_DRIFT = 4


def _allocation_drift(db: Session, user: User) -> tuple[float, str]:
    """Annualised share of the portfolio that changed asset class over a year.

    Defined as the mean month-to-month L1 distance between successive
    asset-class weight vectors, halved and annualised. Halving is what makes
    the number readable: moving ten percent of a portfolio from equity to
    debt raises equity's weight by 0.10 and lowers debt's by 0.10, an L1
    distance of 0.20, and the intuitive answer is "ten percent moved".

    Two sources, and which one was used is reported rather than hidden:

    ``transactions`` -- the real article. Quantities are accumulated from the
    user's own recorded buys and sells, so the path reflects what they
    actually did, and drift caused by trading is visible.

    ``price_drift`` -- the fallback. ``monthly_history`` reconstructs the path
    with *today's* quantities held constant across history, so it can only
    show drift caused by prices moving, never by the investor acting. It is
    still a real measurement of whether the mix has wandered, but it is a
    different quantity and is labelled as one. ``docs/limitations.md``
    records the same caveat for the rest of the reconstruction.

    Returns ``(nan, "unavailable")`` when neither path has enough data. This
    field was hardcoded to NaN before Phase 2, so the behaviour component
    always scored on two of its three sub-scores.
    """
    observed = _drift_from_transactions(db, user)
    if not np.isnan(observed):
        return observed, "transactions"

    from app.ml_runtime.features import monthly_history

    history = monthly_history(db, user)
    if history.empty or len(history) < MIN_MONTHS_FOR_DRIFT:
        return float("nan"), "unavailable"

    columns = [c for c in history.columns if c.endswith("_allocation")]
    if not columns:
        return float("nan"), "unavailable"

    weights = history[columns].to_numpy(dtype="float64")
    return _mean_annualised_l1(weights), "price_drift"


def _drift_from_transactions(db: Session, user: User) -> float:
    """The allocation path implied by the user's own recorded trades."""
    rows = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.asset_id.isnot(None))
            .order_by(Transaction.date)
        ).all()
    )
    directional = [
        t for t in rows
        if t.transaction_type in (TransactionType.BUY, TransactionType.SELL)
        and t.quantity and t.asset is not None
    ]
    if not directional:
        return float("nan")

    months = sorted({(t.date.year, t.date.month) for t in directional})
    if len(months) < MIN_MONTHS_FOR_DRIFT:
        return float("nan")

    symbols = sorted({t.asset.symbol for t in directional})
    panel = market_cache.price_history(db, symbols)
    if panel.empty:
        return float("nan")
    monthly_prices = panel.resample("ME").last().ffill()

    classes = {t.asset.symbol: str(t.asset.asset_class).lower() for t in directional}
    class_names = sorted(set(classes.values()))

    held: dict[str, float] = {s: 0.0 for s in symbols}
    path: list[list[float]] = []

    for year, month in months:
        for t in directional:
            if (t.date.year, t.date.month) != (year, month):
                continue
            sign = 1.0 if t.transaction_type == TransactionType.BUY else -1.0
            held[t.asset.symbol] = max(
                0.0, held[t.asset.symbol] + sign * float(t.quantity)
            )

        stamp = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        available = monthly_prices.loc[monthly_prices.index <= stamp]
        if available.empty:
            continue
        prices = available.iloc[-1]

        by_class = {name: 0.0 for name in class_names}
        for symbol, quantity in held.items():
            price = prices.get(symbol)
            if quantity <= 0 or price is None or pd.isna(price):
                continue
            by_class[classes[symbol]] += quantity * float(price)

        total = sum(by_class.values())
        if total <= 0:
            continue
        path.append([by_class[name] / total for name in class_names])

    if len(path) < MIN_MONTHS_FOR_DRIFT:
        return float("nan")
    return _mean_annualised_l1(np.asarray(path, dtype="float64"))


def _mean_annualised_l1(weights: np.ndarray) -> float:
    """Mean monthly L1 change in a weight path, halved and annualised."""
    if weights.shape[0] < 2:
        return float("nan")
    steps = np.abs(np.diff(weights, axis=0)).sum(axis=1) / 2.0
    steps = steps[np.isfinite(steps)]
    if steps.size == 0:
        return float("nan")
    return float(np.mean(steps) * 12.0)


def _behaviour_metrics(db: Session, user: User, portfolio_value: float) -> dict:
    """Turnover, contribution consistency and allocation drift.

    All three need transaction history. Where there is none they are left as
    NaN so the health score drops the component rather than scoring the user
    on an assumption.
    """
    since = date.today() - timedelta(days=BEHAVIOUR_WINDOW_DAYS)
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user.id, Transaction.date >= since
            )
        ).all()
    )

    drift, drift_source = _allocation_drift(db, user)

    if not transactions:
        return {
            "annual_turnover": float("nan"),
            "contribution_consistency": float("nan"),
            # Drift does not need the 365-day transaction window the other two
            # do -- it can come from the reconstructed price path -- so it is
            # reported even here rather than blanked with the rest.
            "allocation_drift": drift,
            "allocation_drift_source": drift_source,
            "n_transactions": 0,
        }

    # Turnover: the smaller of total buys and total sells, over average
    # portfolio value. Using the smaller side is the standard convention; it
    # stops a year of pure accumulation from reading as high turnover.
    buys = sum(t.value for t in transactions if t.transaction_type == TransactionType.BUY)
    sells = sum(t.value for t in transactions if t.transaction_type == TransactionType.SELL)
    turnover = (
        min(buys, sells) / portfolio_value if portfolio_value > 0 else float("nan")
    )

    contributions = [
        t for t in transactions if t.transaction_type == TransactionType.CONTRIBUTION
    ]
    if contributions:
        funded_months = {(t.date.year, t.date.month) for t in contributions}
        earliest = min(t.date for t in contributions)
        elapsed_months = max(
            1, (date.today().year - earliest.year) * 12 + date.today().month - earliest.month + 1
        )
        consistency = min(1.0, len(funded_months) / elapsed_months)
    else:
        consistency = float("nan")

    return {
        "annual_turnover": float(turnover),
        "contribution_consistency": float(consistency),
        "allocation_drift": drift,
        "allocation_drift_source": drift_source,
        "n_transactions": len(transactions),
    }


def _or_nan(value: float | None) -> float:
    """None means "not measured"; any float, including 0.0, is a measurement."""
    return float("nan") if value is None else float(value)


def build_health_inputs(db: Session, user: User) -> tuple[HealthInputs, dict]:
    """Gather every measurement the score needs."""
    context: dict = {}

    concentration: dict = {}
    try:
        concentration = risk_service.concentration(db, user)
        context["concentration"] = True
    except risk_service.InsufficientHistory:
        context["concentration"] = False

    risk_summary: dict = {}
    try:
        returns, benchmark, metadata = risk_service.portfolio_return_series(db, user)
        from wealthos_core import performance_summary

        risk_summary = performance_summary(returns, benchmark)
        context["risk_window"] = [metadata["start"], metadata["end"]]
        context["risk_observations"] = metadata["observations"]
    except risk_service.InsufficientHistory as exc:
        context["risk_unavailable"] = str(exc)

    alignment = goal_service.portfolio_goal_alignment(db, user)
    summary = portfolio_service.build_summary(db, user)
    behaviour = _behaviour_metrics(db, user, summary.total_value)
    context["behaviour"] = behaviour

    asset_class_weights = {
        slice_.label: slice_.weight for slice_ in summary.allocation_by_class
    }

    inputs = HealthInputs(
        n_holdings=concentration.get("n_holdings", summary.n_holdings),
        n_sectors=concentration.get("n_sectors", summary.n_sectors),
        n_asset_classes=len(asset_class_weights),
        hhi_normalized=concentration.get("hhi_normalized", float("nan")),
        # `or float("nan")` here would be wrong: 0.0 is falsy, and a mean
        # pairwise correlation of exactly 0.0 is the *ideal* result — holdings
        # that move independently. Treating it as unmeasurable dropped
        # diversification's correlation term for the best portfolios.
        average_pairwise_correlation=_or_nan(
            concentration.get("average_pairwise_correlation")
        ),
        annualized_volatility=risk_summary.get("annualized_volatility", float("nan")),
        max_drawdown=risk_summary.get("max_drawdown", float("nan")),
        risk_tolerance=str(user.risk_tolerance or "moderate"),
        top_1_weight=concentration.get("top_1_weight", float("nan")),
        top_5_weight=concentration.get("top_5_weight", float("nan")),
        max_sector_weight=concentration.get("max_sector_weight", float("nan")),
        asset_class_weights=asset_class_weights,
        has_goals=alignment["has_goals"],
        goal_progress_ratio=alignment["goal_progress_ratio"],
        goal_funding_ratio=alignment["goal_funding_ratio"],
        annual_turnover=behaviour["annual_turnover"],
        contribution_consistency=behaviour["contribution_consistency"],
        allocation_drift=behaviour["allocation_drift"],
    )
    return inputs, context


# Which methodology the top-level fields describe. Both are always computed;
# this only decides which one `total`, `grade` and `components` carry, so an
# existing client keeps working unchanged while the comparison is available
# to any caller that wants it.
DEFAULT_METHODOLOGY = "v1"
METHODOLOGIES = ("v1", "v2")

_METHODOLOGY_NOTES = {
    "v1": (
        "A weighted average of six measured components, each a documented "
        "function of portfolio metrics rather than a learned model. "
        "Components whose inputs are unavailable are excluded and the "
        "remaining weights renormalised, so an unmeasurable component neither "
        "helps nor penalises the score. Note that in this version the "
        "per-component contributions are computed against raw weights while "
        "the total uses the renormalised denominator, so where a component "
        "could not be measured the contributions do not sum to the total."
    ),
    "v2": (
        "The same six components and the same weights as v1, with six "
        "measurement defects corrected: the holdings curve now implements the "
        "8-and-25 rationale v1 only described, a drawdown inside the "
        "investor's stated tolerance scores full marks instead of half, "
        "liquidity measures the cash-and-debt buffer alongside the "
        "asset-class blend so the component can discriminate, weight "
        "dispersion is counted once in concentration rather than twice, every "
        "narrative is derived from the sub-scores so text cannot contradict "
        "the number, and contributions are computed against renormalised "
        "weights so they sum to the total."
    ),
}


def health_score(
    db: Session,
    user: User,
    include_sensitivity: bool = False,
    methodology: str = DEFAULT_METHODOLOGY,
) -> dict:
    """The decomposable Portfolio Health Score, in both methodologies.

    Both versions are computed on every call and returned together under
    ``versions``, because a score that changed without the old one visible
    beside it is a score nobody can check. ``methodology`` selects only which
    version populates the top-level fields.
    """
    if methodology not in METHODOLOGIES:
        raise ValueError(
            f"unknown methodology {methodology!r}; expected one of {METHODOLOGIES}"
        )

    inputs, context = build_health_inputs(db, user)
    computed = {
        "v1": compute_health_score(inputs).as_dict(),
        "v2": compute_health_score_v2(inputs).as_dict(),
    }

    payload = dict(computed[methodology])
    payload["methodology_version"] = methodology
    payload["methodology"] = _METHODOLOGY_NOTES[methodology]
    payload["context"] = context
    payload["weights"] = {c["name"]: c["weight"] for c in payload["components"]}

    payload["versions"] = {
        version: {
            "total": body["total"],
            "grade": body["grade"],
            "summary": body["summary"],
            "missing_inputs": body["missing_inputs"],
            "components": body["components"],
            "methodology": _METHODOLOGY_NOTES[version],
        }
        for version, body in computed.items()
    }

    v1_total, v2_total = computed["v1"]["total"], computed["v2"]["total"]
    payload["version_comparison"] = {
        "v1_total": v1_total,
        "v2_total": v2_total,
        "difference": (
            None if v1_total is None or v2_total is None
            else round(v2_total - v1_total, 2)
        ),
        "note": (
            "Both methodologies use identical inputs and identical component "
            "weights, so any difference is attributable to the measurement "
            "changes in v2 rather than to re-weighting."
        ),
    }

    if include_sensitivity:
        payload["sensitivity"] = sensitivity_analysis(inputs)

    return payload
