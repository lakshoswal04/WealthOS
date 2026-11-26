"""Stage 06 — generate the synthetic investor cohort and simulate it forward.

Builds N investors from the latent archetypes, gives each a portfolio drawn
from Big Sharks-derived popularity priors, and simulates them month by month
against the real adjusted price panel, producing:

    data/synthetic/investors.parquet    one row per investor
    data/synthetic/snapshots.parquet    one row per investor-month
    data/synthetic/transactions.parquet trades and cash flows
    ml/reports/cohort.json              composition and sanity checks

Everything here is simulated and is labelled as such throughout. Only the
prices are real.

The simulation is vectorised across investors: the state is an
(investors x assets) quantity matrix stepped once per month, rather than a
Python loop per investor. At 10,000 investors and 179 months that is the
difference between seconds and many minutes.

Run:  python -m ml.pipelines.p06_generate_cohort --investors 500
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from ml.synthetic.archetypes import ARCHETYPES, sample_profile

from .common import (
    PROCESSED_DIR,
    SYNTHETIC_DIR,
    PipelineError,
    Stage,
    get_logger,
    load_universe,
    write_report,
)

log = get_logger("cohort")

RANDOM_SEED = 42
MONTHS_PER_YEAR = 12

# Investors must have joined early enough to have a usable history.
MIN_MONTHS_OF_HISTORY = 24


def _month_end_prices(panel: pd.DataFrame) -> pd.DataFrame:
    """Last traded price in each calendar month."""
    monthly = panel.resample("ME").last()
    # Carry a price forward across a month with no trade rather than
    # treating the position as worthless.
    return monthly.ffill()


def _build_target_weights(
    profiles: list[dict], assets: list[str], asset_classes: dict[str, str],
    popularity: pd.Series, rng: np.random.Generator,
) -> np.ndarray:
    """An (investors x assets) matrix of target portfolio weights.

    Equity names are drawn without replacement using Big Sharks popularity,
    so the cohort concentrates in the stocks Indian investors actually hold
    rather than spreading uniformly across the NIFTY 50.
    """
    index = {symbol: i for i, symbol in enumerate(assets)}
    by_class: dict[str, list[str]] = {}
    for symbol in assets:
        by_class.setdefault(asset_classes.get(symbol, "equity"), []).append(symbol)

    equity_pool = by_class.get("equity", [])
    equity_probabilities = np.array(
        [popularity.get(s, popularity.min() if len(popularity) else 1.0) for s in equity_pool],
        dtype="float64",
    )
    equity_probabilities /= equity_probabilities.sum()

    weights = np.zeros((len(profiles), len(assets)), dtype="float64")

    for row, profile in enumerate(profiles):
        for asset_class, class_weight in profile["target_allocation"].items():
            if class_weight <= 0:
                continue
            pool = by_class.get(asset_class, [])
            if not pool:
                continue

            if asset_class == "equity" and equity_pool:
                count = min(profile["n_equity_holdings"], len(equity_pool))
                chosen = rng.choice(
                    len(equity_pool), size=count, replace=False, p=equity_probabilities
                )
                names = [equity_pool[i] for i in chosen]
                # A low alpha concentrates the money in one or two names even
                # when several are held.
                inner = rng.dirichlet(np.full(count, profile["equity_weight_alpha"]))
            else:
                count = min(len(pool), 2)
                names = list(rng.choice(pool, size=count, replace=False))
                inner = rng.dirichlet(np.full(count, 6.0))

            for name, share in zip(names, inner):
                weights[row, index[name]] += class_weight * share

    # Guard against an investor whose draws all landed on empty pools.
    totals = weights.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    return weights / totals


def simulate(
    profiles: list[dict], weights: np.ndarray, prices: pd.DataFrame,
    asset_class_of: np.ndarray, start_month_index: np.ndarray,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Step every investor's portfolio forward, month by month.

    State is an (investors x assets) quantity matrix. Each month: value the
    holdings at real prices, add contributions allocated to target weights,
    rebalance those due, apply discretionary turnover, and record a snapshot.
    """
    n_investors, n_assets = weights.shape
    n_months = len(prices)
    price_matrix = prices.to_numpy(dtype="float64")
    # A missing price must not create or destroy value.
    price_matrix = np.where(np.isfinite(price_matrix) & (price_matrix > 0), price_matrix, np.nan)

    quantities = np.zeros((n_investors, n_assets), dtype="float64")

    monthly_savings = np.array([p["monthly_savings"] for p in profiles])
    contribution_probability = np.array([p["contribution_probability"] for p in profiles])
    annual_turnover = np.array([p["annual_turnover"] for p in profiles])
    rebalance_months = np.array([p["rebalance_months"] for p in profiles])
    lump_sum = monthly_savings * np.array([p["lump_sum_multiple"] for p in profiles])
    monthly_turnover = annual_turnover / MONTHS_PER_YEAR

    blank = lambda: np.full((n_investors, n_months), np.nan, dtype="float64")
    state = {
        name: blank() for name in
        ("value", "contribution", "turnover_value", "n_trades", "invested",
         "hhi", "top_weight", "n_holdings")
    }
    classes = ("equity", "etf", "gold", "debt", "cash")
    allocation = {name: blank() for name in classes}
    class_masks = {name: (asset_class_of == name) for name in classes}

    active = np.zeros(n_investors, dtype=bool)
    invested_total = np.zeros(n_investors)

    def normalised_targets(tradeable: np.ndarray) -> np.ndarray:
        """Target weights restricted to assets priced this month."""
        target = weights * tradeable
        total = target.sum(axis=1, keepdims=True)
        total[total == 0] = 1.0
        return target / total

    for month in range(n_months):
        prices_now = price_matrix[month]
        tradeable = np.isfinite(prices_now)
        safe_prices = np.where(tradeable, prices_now, 1.0)
        priced = np.where(tradeable, prices_now, 0.0)

        joining = start_month_index == month
        if joining.any():
            active |= joining
            spend = np.where(joining, lump_sum, 0.0)
            quantities += (spend[:, None] * normalised_targets(tradeable)) / safe_prices
            invested_total += spend

        if not active.any():
            continue

        # --- contributions ---
        funded = (rng.random(n_investors) < contribution_probability) & active
        contribution = np.where(funded, monthly_savings, 0.0)
        if contribution.any():
            quantities += (contribution[:, None] * normalised_targets(tradeable)) / safe_prices
            invested_total += contribution

        # --- scheduled rebalancing ---
        rebalanced_value = np.zeros(n_investors)
        due = active & (rebalance_months > 0)
        if due.any():
            period = np.where(rebalance_months > 0, rebalance_months, 1)
            due = due & ((month + 1) % period == 0)
        if due.any():
            values = quantities * priced
            total_value = values.sum(axis=1)
            desired = total_value[:, None] * normalised_targets(tradeable)
            # Half the absolute weight change is the value that changed hands.
            rebalanced_value = np.where(due, np.abs(desired - values).sum(axis=1) / 2.0, 0.0)
            quantities = np.where(due[:, None], desired / safe_prices, quantities)

        # --- discretionary turnover ---
        # Selling a slice and buying it back across the same targets: it moves
        # money and registers activity without taking a directional view,
        # which is what turnover measures.
        churn = np.zeros(n_investors)
        trading = active & (monthly_turnover > 0)
        if trading.any():
            # Lognormal jitter makes trading bursty rather than identical
            # every month.
            intensity = np.clip(monthly_turnover * rng.lognormal(0.0, 0.6, n_investors), 0.0, 0.5)
            values = quantities * priced
            churn = np.where(trading, values.sum(axis=1) * intensity, 0.0)

        # --- record ---
        values = quantities * priced
        total_value = values.sum(axis=1)
        safe_total = np.where(total_value > 0, total_value, np.nan)
        holding_weights = values / safe_total[:, None]

        state["value"][active, month] = total_value[active]
        state["contribution"][active, month] = contribution[active]
        state["turnover_value"][active, month] = (churn + rebalanced_value)[active]
        state["invested"][active, month] = invested_total[active]
        state["n_trades"][active, month] = (
            (churn > 0).astype(float) + (rebalanced_value > 0).astype(float)
        )[active]

        state["hhi"][active, month] = np.nansum(holding_weights ** 2, axis=1)[active]
        state["top_weight"][active, month] = np.nanmax(
            np.where(np.isfinite(holding_weights), holding_weights, 0.0), axis=1
        )[active]
        state["n_holdings"][active, month] = (values > 1.0).sum(axis=1)[active]

        for name, mask in class_masks.items():
            allocation[name][active, month] = (
                values[:, mask].sum(axis=1) / safe_total
            )[active]

    return {"state": state, "allocation": allocation, "quantities": quantities}


# --------------------------------------------------------------------------
# Anomalies
# --------------------------------------------------------------------------

ANOMALY_TYPES = (
    "allocation_shock",
    "concentration_spike",
    "turnover_spike",
    "panic_sell",
    "dormancy_break",
)

ANOMALY_INVESTOR_SHARE = 0.12   # share of the cohort that receives anomalies
ANOMALY_MIN_HISTORY = 12        # months of normal behaviour required first

# A dormancy break is defined by the silence before it, so the generator has
# to produce that silence. Three to six months of no contributions and no
# trades is long enough to be unambiguous against ordinary lumpy saving and
# short enough to leave room for several events in one investor's history.
ANOMALY_QUIET_MIN: int = 3
ANOMALY_QUIET_MAX: int = 6


def _spaced_choice(
    candidates: np.ndarray, count: int, min_gap: int, rng: np.random.Generator
) -> np.ndarray:
    """Pick up to ``count`` values at least ``min_gap`` apart.

    Anomaly injection writes backwards in time for dormancy breaks, so two
    events closer together than the quiet stretch would corrupt each other:
    the earlier injection would be zeroed out by the later one's silence and
    the row would keep a label describing something no longer in the data.
    """
    pool = list(rng.permutation(candidates))
    chosen: list[int] = []
    for value in pool:
        if len(chosen) >= count:
            break
        if all(abs(int(value) - int(taken)) >= min_gap for taken in chosen):
            chosen.append(int(value))
    return np.array(sorted(chosen), dtype=int)


def inject_anomalies(
    state: dict[str, np.ndarray], allocation: dict[str, np.ndarray],
    rng: np.random.Generator,
) -> np.ndarray:
    """Introduce labelled anomalous months into a minority of investors.

    Applied to the recorded snapshots rather than threaded through the
    simulation, so each anomaly's location and type are known exactly. That
    exact ground truth is what lets the autoencoder be scored on real
    precision and recall instead of on reconstruction error alone.

    These are injected anomalies, not observed ones. They are deliberately
    unambiguous, so detection metrics computed against them are an upper
    bound on performance against real, subtler behaviour. The report must
    say so.
    """
    n_investors, n_months = state["value"].shape
    labels = np.zeros((n_investors, n_months), dtype="int8")
    type_labels = np.full((n_investors, n_months), "", dtype=object)

    n_affected = max(1, int(n_investors * ANOMALY_INVESTOR_SHARE))
    chosen = rng.choice(n_investors, size=n_affected, replace=False)

    for investor in chosen:
        observed = np.flatnonzero(np.isfinite(state["value"][investor]))
        if len(observed) < ANOMALY_MIN_HISTORY + 3:
            continue

        # Leave room before the chosen month for a dormancy quiet stretch, and
        # keep events far enough apart that one does not overwrite another's
        # run-up -- two dormancy breaks three months apart would leave the
        # first one's injection sitting inside the second one's silence.
        eligible = observed[ANOMALY_MIN_HISTORY + ANOMALY_QUIET_MAX:]
        if len(eligible) == 0:
            continue
        n_events = int(rng.integers(1, 6))
        months = _spaced_choice(
            eligible, n_events, ANOMALY_QUIET_MAX + 1, rng
        )

        for month in months:
            kind = str(rng.choice(ANOMALY_TYPES))

            if kind == "allocation_shock":
                # Move 35-60% of the portfolio from equity into cash in one
                # month, far beyond ordinary drift.
                shift = float(rng.uniform(0.35, 0.60))
                moved = min(shift, float(allocation["equity"][investor, month] or 0.0))
                allocation["equity"][investor, month] -= moved
                allocation["cash"][investor, month] += moved

            elif kind == "concentration_spike":
                top = float(rng.uniform(0.65, 0.90))
                state["top_weight"][investor, month] = top
                state["hhi"][investor, month] = top ** 2 + (1 - top) ** 2 / 4
                state["n_holdings"][investor, month] = max(
                    1.0, state["n_holdings"][investor, month] * 0.3
                )

            elif kind == "turnover_spike":
                multiple = float(rng.uniform(5.0, 12.0))
                base = state["turnover_value"][investor, month]
                reference = base if base and base > 0 else state["value"][investor, month] * 0.02
                state["turnover_value"][investor, month] = reference * multiple
                state["n_trades"][investor, month] += float(rng.integers(8, 25))

            elif kind == "panic_sell":
                # Liquidate most equity into cash and stop contributing.
                equity = float(allocation["equity"][investor, month] or 0.0)
                etf = float(allocation["etf"][investor, month] or 0.0)
                allocation["cash"][investor, month] += equity * 0.8 + etf * 0.8
                allocation["equity"][investor, month] = equity * 0.2
                allocation["etf"][investor, month] = etf * 0.2
                state["contribution"][investor, month] = 0.0
                state["turnover_value"][investor, month] = (
                    state["value"][investor, month] * 0.8
                )

            else:  # dormancy_break
                # A large one-off injection AFTER A QUIET STRETCH -- and the
                # quiet stretch has to be created, not merely described.
                #
                # This branch used to write the injection alone, leaving the
                # preceding months exactly as the simulation produced them:
                # still contributing, still trading. So the row labelled
                # "dormancy_break" was a large contribution and nothing more,
                # indistinguishable from an ordinary investor receiving a
                # bonus. docs/EXPLAINER.md explained the resulting low recall
                # with a story about preceding inactivity that the generator
                # never produced, and a model cannot learn a pattern that is
                # absent from the data describing it.
                quiet_months = int(rng.integers(ANOMALY_QUIET_MIN, ANOMALY_QUIET_MAX + 1))
                start = max(0, int(month) - quiet_months)
                if start < month:
                    state["contribution"][investor, start:month] = 0.0
                    state["n_trades"][investor, start:month] = 0.0
                    state["turnover_value"][investor, start:month] = 0.0

                state["contribution"][investor, month] = (
                    state["value"][investor, month] * float(rng.uniform(0.3, 0.8))
                )
                # Re-entering the market after a pause means placing trades.
                state["n_trades"][investor, month] += float(rng.integers(1, 5))

            labels[investor, month] = 1
            type_labels[investor, month] = kind

    return labels, type_labels


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

def build_snapshots(
    profiles: list[dict], state: dict[str, np.ndarray],
    allocation: dict[str, np.ndarray], months: pd.DatetimeIndex,
    anomaly_labels: np.ndarray, anomaly_types: np.ndarray,
) -> pd.DataFrame:
    """Turn the simulation matrices into a tidy investor-month table.

    Returns are time-weighted: the month's contribution is removed before
    dividing by the opening value. Without that step a steady contributor in
    a flat market would show large positive returns and the entire
    behavioural feature set would be built on a false signal.
    """
    values = state["value"]
    contributions = np.nan_to_num(state["contribution"])
    n_investors, n_months = values.shape

    previous = np.full_like(values, np.nan)
    previous[:, 1:] = values[:, :-1]

    with np.errstate(invalid="ignore", divide="ignore"):
        period_return = (values - contributions) / previous - 1.0
    period_return[~np.isfinite(previous) | (previous <= 0)] = np.nan
    period_return = np.where(np.isfinite(period_return), period_return, np.nan)

    # Trailing 12-month volatility, annualised, and running drawdown.
    volatility = np.full_like(values, np.nan)
    cumulative = np.full_like(values, np.nan)
    drawdown = np.full_like(values, np.nan)
    max_drawdown = np.full_like(values, np.nan)
    turnover_12m = np.full_like(values, np.nan)

    turnover_value = np.nan_to_num(state["turnover_value"])

    for i in range(n_investors):
        observed = np.flatnonzero(np.isfinite(values[i]))
        if len(observed) < 2:
            continue
        first, last = observed[0], observed[-1]
        returns = period_return[i, first : last + 1]

        wealth = np.nancumprod(np.where(np.isfinite(returns), 1 + returns, 1.0))
        peak = np.maximum.accumulate(wealth)
        running_drawdown = wealth / np.where(peak > 0, peak, 1.0) - 1.0

        cumulative[i, first : last + 1] = wealth - 1.0
        drawdown[i, first : last + 1] = running_drawdown
        max_drawdown[i, first : last + 1] = np.minimum.accumulate(running_drawdown)

        series = pd.Series(returns)
        volatility[i, first : last + 1] = (
            series.rolling(12, min_periods=6).std().to_numpy() * np.sqrt(MONTHS_PER_YEAR)
        )

        traded = pd.Series(turnover_value[i, first : last + 1])
        held = pd.Series(values[i, first : last + 1])
        rolling_traded = traded.rolling(12, min_periods=6).sum()
        rolling_value = held.rolling(12, min_periods=6).mean()
        turnover_12m[i, first : last + 1] = (
            rolling_traded / rolling_value.replace(0, np.nan)
        ).to_numpy()

    observed_mask = np.isfinite(values)
    investor_idx, month_idx = np.nonzero(observed_mask)

    frame = pd.DataFrame({
        "investor_id": investor_idx + 1,
        "date": months.to_numpy()[month_idx],
        "total_value": values[observed_mask],
        "invested_amount": state["invested"][observed_mask],
        "net_contribution": contributions[observed_mask],
        "period_return": period_return[observed_mask],
        "cumulative_return": cumulative[observed_mask],
        "volatility": volatility[observed_mask],
        "current_drawdown": drawdown[observed_mask],
        "max_drawdown": max_drawdown[observed_mask],
        "hhi": state["hhi"][observed_mask],
        "top_holding_weight": state["top_weight"][observed_mask],
        "n_holdings": state["n_holdings"][observed_mask],
        "turnover": turnover_12m[observed_mask],
        "n_trades": state["n_trades"][observed_mask],
        "is_anomaly": anomaly_labels[observed_mask],
        "anomaly_type": anomaly_types[observed_mask],
    })

    for name, matrix in allocation.items():
        frame[f"{name}_allocation"] = matrix[observed_mask]

    archetypes = np.array([p["archetype"] for p in profiles])
    frame["archetype"] = archetypes[investor_idx]
    return frame.sort_values(["investor_id", "date"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic investor cohort")
    parser.add_argument("--investors", type=int, default=500)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    report: dict = {"n_investors": args.investors, "seed": args.seed}

    with Stage(log, "load prices and priors"):
        panel = pd.read_parquet(PROCESSED_DIR / "price_panel.parquet")
        monthly = _month_end_prices(panel)
        universe = load_universe()

        tradeable = universe[
            (universe.status == "active") & (universe.asset_class != "index")
        ]
        assets = [s for s in tradeable.symbol if s in monthly.columns]
        monthly = monthly[assets]
        asset_classes = dict(zip(tradeable.symbol, tradeable.asset_class))

        popularity_path = PROCESSED_DIR / "holding_popularity.csv"
        if not popularity_path.exists():
            raise PipelineError("run stage 05 first to build the holding priors")
        popularity = pd.read_csv(popularity_path).set_index("symbol")["weight"]

        log.info("  %d tradeable assets, %d months (%s → %s)",
                 len(assets), len(monthly),
                 monthly.index.min().date(), monthly.index.max().date())

    with Stage(log, f"sample {args.investors} investors"):
        shares = np.array([a.share for a in ARCHETYPES])
        shares = shares / shares.sum()
        assignment = rng.choice(len(ARCHETYPES), size=args.investors, p=shares)
        profiles = [sample_profile(ARCHETYPES[i], rng) for i in assignment]

        counts = pd.Series([p["archetype"] for p in profiles]).value_counts()
        for name, count in counts.items():
            log.info("  %-20s %5d (%.1f%%)", name, count, 100 * count / args.investors)

        mismatched = sum(1 for p in profiles if not p["risk_matches_archetype"])
        log.info("  stated risk inconsistent with behaviour: %d (%.1f%%)",
                 mismatched, 100 * mismatched / args.investors)
        report["archetype_counts"] = counts.to_dict()
        report["risk_mismatch_count"] = mismatched

    with Stage(log, "assign holdings from popularity priors"):
        weights = _build_target_weights(profiles, assets, asset_classes, popularity, rng)
        held = (weights > 1e-6).sum(axis=1)
        log.info("  holdings per investor: median %d, range %d-%d",
                 int(np.median(held)), int(held.min()), int(held.max()))
        report["holdings_per_investor"] = {
            "median": int(np.median(held)), "min": int(held.min()), "max": int(held.max()),
        }

    with Stage(log, "assign join dates"):
        latest_start = max(1, len(monthly) - MIN_MONTHS_OF_HISTORY)
        # Skewed toward earlier joins, so most investors have a long history
        # while some are genuinely new.
        start_month_index = (rng.beta(1.6, 3.0, args.investors) * latest_start).astype(int)
        log.info("  join month index: median %d of %d (median history %d months)",
                 int(np.median(start_month_index)), len(monthly),
                 len(monthly) - int(np.median(start_month_index)))

    with Stage(log, "simulate portfolios"):
        asset_class_of = np.array([asset_classes.get(a, 'equity') for a in assets])
        result = simulate(
            profiles, weights, monthly, asset_class_of, start_month_index, rng
        )
        state = result["state"]
        values = state["value"]
        simulated = np.isfinite(values).sum()
        log.info("  %d investor-months simulated", simulated)
        report["investor_months"] = int(simulated)

    with Stage(log, "sanity-check the simulation"):
        final_values = np.array([
            row[np.isfinite(row)][-1] if np.isfinite(row).any() else np.nan for row in values
        ])
        invested = np.array([
            row[np.isfinite(row)][-1] if np.isfinite(row).any() else np.nan
            for row in state["invested"]
        ])
        multiple = final_values / np.where(invested > 0, invested, np.nan)

        log.info("  final value: median Rs %.0f", float(np.nanmedian(final_values)))
        log.info("  growth multiple vs money invested: median %.2fx, p10 %.2fx, p90 %.2fx",
                 float(np.nanmedian(multiple)),
                 float(np.nanquantile(multiple, 0.10)),
                 float(np.nanquantile(multiple, 0.90)))

        if np.nanmin(final_values) < 0:
            raise PipelineError("a portfolio went negative, which the simulation cannot produce")
        report["final_value"] = {
            "median": round(float(np.nanmedian(final_values)), 2),
            "p10": round(float(np.nanquantile(final_values, 0.10)), 2),
            "p90": round(float(np.nanquantile(final_values, 0.90)), 2),
        }
        report["growth_multiple"] = {
            "median": round(float(np.nanmedian(multiple)), 3),
            "p10": round(float(np.nanquantile(multiple, 0.10)), 3),
            "p90": round(float(np.nanquantile(multiple, 0.90)), 3),
        }

    with Stage(log, "inject labelled anomalies"):
        anomaly_labels, anomaly_types = inject_anomalies(
            state, result["allocation"], rng
        )
        total = int(anomaly_labels.sum())
        affected = int((anomaly_labels.sum(axis=1) > 0).sum())
        log.info("  %d anomalous months across %d investors (%.2f%% of all months)",
                 total, affected, 100 * total / max(1, int(np.isfinite(values).sum())))
        kinds = pd.Series(anomaly_types[anomaly_labels == 1]).value_counts()
        for kind, count in kinds.items():
            log.info("    %-22s %d", kind, count)
        report["anomalies"] = {
            "months": total, "investors": affected,
            "by_type": {str(k): int(v) for k, v in kinds.items()},
            "caveat": (
                "Injected, not observed. They are deliberately unambiguous, so "
                "detection scores against them are an upper bound on real-world "
                "performance."
            ),
        }

    with Stage(log, "build snapshots"):
        snapshots = build_snapshots(
            profiles, state, result["allocation"], monthly.index,
            anomaly_labels, anomaly_types,
        )
        log.info("  %d investor-month rows x %d columns",
                 len(snapshots), snapshots.shape[1])

    with Stage(log, "write cohort"):
        investors = pd.DataFrame(profiles)
        investors.insert(0, "investor_id", np.arange(1, len(profiles) + 1))
        investors["join_date"] = monthly.index[np.clip(start_month_index, 0, len(monthly) - 1)]
        investors["is_synthetic"] = True
        # Nested dict will not serialise to parquet; split it into columns.
        allocation_frame = pd.json_normalize(investors.pop("target_allocation"))
        allocation_frame.columns = [f"target_{c}" for c in allocation_frame.columns]
        investors = pd.concat([investors, allocation_frame], axis=1)

        investors.to_parquet(SYNTHETIC_DIR / "investors.parquet", index=False)
        snapshots.to_parquet(SYNTHETIC_DIR / "snapshots.parquet", index=False)
        log.info("  → data/synthetic/investors.parquet (%d rows)", len(investors))
        log.info("  → data/synthetic/snapshots.parquet (%d rows)", len(snapshots))

        report["snapshot_rows"] = int(len(snapshots))
        report["snapshot_columns"] = list(snapshots.columns)

    write_report("cohort", report)
    log.info("cohort report written")


if __name__ == "__main__":
    main()
