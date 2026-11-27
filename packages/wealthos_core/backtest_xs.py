"""Cross-sectional portfolio backtest for ranked swing signals.

Mechanics, chosen to match what a person could actually do:

* Scores are known at the close of a signal date. Trades happen at the
  **next session's open**.
* Every ``rebalance_every`` sessions the book is rebuilt from the top ranks.
  Names already held are kept while they stay inside the ``buffer`` (top 20 by
  default); turnover, and therefore cost, falls sharply for little lost signal.
* Every buy and sell pays the itemised Indian delivery costs
  (``wealthos_core.costs``).
* Between rebalances positions drift with prices. A stock with no price on a
  day (a halt) keeps its last value; one that stops trading is valued at its
  last close until the next rebalance sells it.
* Uninvested cash earns nothing, which understates a real account slightly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import DELIVERY, CostModel
from .metrics import performance_summary

__all__ = ["BacktestResult", "rank_portfolio_backtest", "select_names", "cap_weights"]


@dataclass
class BacktestResult:
    returns: pd.Series
    equity: pd.Series
    exposure: pd.Series
    turnover_annual: float
    costs_annual: float
    rebalances: int
    avg_names: float
    final_holdings: dict[str, float] = field(default_factory=dict)

    def summary(self, risk_free_rate: float = 0.0) -> dict:
        s = performance_summary(self.returns, risk_free_rate=risk_free_rate)
        return {
            "start": str(self.returns.index[0].date()) if len(self.returns) else None,
            "end": str(self.returns.index[-1].date()) if len(self.returns) else None,
            "cagr": s["annualized_return"],
            "volatility": s["annualized_volatility"],
            "sharpe": s["sharpe_ratio"],
            "sortino": s["sortino_ratio"],
            "max_drawdown": s["max_drawdown"],
            "calmar": s["calmar_ratio"],
            "total_return": s["total_return"],
            "turnover_annual": self.turnover_annual,
            "costs_annual": self.costs_annual,
            "avg_exposure": float(self.exposure.mean()) if len(self.exposure) else None,
            "avg_names": self.avg_names,
            "rebalances": self.rebalances,
        }

    def curve(self, every: int = 5) -> list[dict]:
        eq = self.equity.iloc[::every]
        if len(self.equity) and (len(eq) == 0 or eq.index[-1] != self.equity.index[-1]):
            eq = pd.concat([eq, self.equity.iloc[[-1]]])
        return [{"date": str(d.date()), "value": round(float(v), 5)} for d, v in eq.items()]


def cap_weights(weights: pd.Series, max_weight: float | None) -> pd.Series:
    """Clip weights at ``max_weight`` and hand the excess to the rest, repeatedly."""
    w = weights.clip(lower=0.0)
    total = w.sum()
    if total <= 0:
        return w
    w = w / total
    if not max_weight or max_weight >= 1.0 or max_weight * len(w) < 1.0:
        return w
    for _ in range(50):
        over = w > max_weight + 1e-12
        if not over.any():
            break
        excess = float((w[over] - max_weight).sum())
        w[over] = max_weight
        free = ~over & (w < max_weight)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


def select_names(scores: pd.Series, held: list[str], top_n: int | None, buffer: int | None) -> list[str]:
    """Top ``top_n`` by score, keeping held names that are still inside ``buffer``."""
    ranked = scores.dropna().sort_values(ascending=False)
    if top_n is None:
        return list(ranked.index)
    keep_zone = set(ranked.index[: (buffer or top_n)])
    chosen = [s for s in held if s in keep_zone]
    chosen = sorted(chosen, key=lambda s: -ranked[s])[:top_n]
    for s in ranked.index:
        if len(chosen) >= top_n:
            break
        if s not in chosen:
            chosen.append(s)
    return chosen


def rank_portfolio_backtest(
    scores: pd.DataFrame,
    open_: pd.DataFrame,
    close: pd.DataFrame,
    *,
    top_n: int | None = 10,
    rebalance_every: int = 5,
    buffer: int | None = 20,
    weighting: str = "equal",
    vol: pd.DataFrame | None = None,
    exposure: pd.Series | None = None,
    max_weight: float | None = None,
    weight_fn: Callable[[pd.Timestamp, list[str]], pd.Series] | None = None,
    costs: CostModel = DELIVERY,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> BacktestResult:
    """Simulate a long-only book rebuilt from ``scores`` every few sessions.

    ``scores``: date x symbol, NaN where a stock may not be held.
    ``open_`` / ``close``: date x symbol prices on the same calendar.
    ``exposure``: share of equity to invest, by signal date (regime overlay).
    ``weight_fn``: custom weights for the chosen names (HRP, for example). If
    they sum to less than 1 the remainder stays in cash.
    """
    calendar = pd.DatetimeIndex(close.index)
    symbols = list(close.columns)
    scores = scores.reindex(index=calendar, columns=symbols)
    o = open_.reindex(index=calendar, columns=symbols).to_numpy(float)
    c = close.reindex(columns=symbols).ffill().to_numpy(float)
    if vol is not None:
        vol = vol.reindex(index=calendar, columns=symbols)

    lo = calendar.searchsorted(pd.Timestamp(start)) if start is not None else 0
    hi = calendar.searchsorted(pd.Timestamp(end), side="right") if end is not None else len(calendar)
    signal_days = [i for i in range(lo, hi - 1) if scores.iloc[i].notna().any()]
    if not signal_days:
        empty = pd.Series(dtype=float)
        return BacktestResult(empty, empty, empty, 0.0, 0.0, 0, 0.0)
    rebalance_at = set(signal_days[::rebalance_every])

    units = np.zeros(len(symbols))
    cash = 1.0
    first = signal_days[0]
    prev_equity = 1.0
    rets, eqs, exps, days = [], [], [], []
    traded = 0.0
    paid = 0.0
    names_held = []
    rebalances = 0

    for i in range(first + 1, hi):
        signal = i - 1
        if signal in rebalance_at:
            px_open = np.where(np.isnan(o[i]), c[i - 1], o[i])
            px_open = np.where(np.isnan(px_open), 0.0, px_open)
            equity_open = cash + float(np.nansum(units * px_open))
            row = scores.iloc[signal]
            held = [symbols[j] for j in np.flatnonzero(units > 0)]
            tradable = row[~np.isnan(o[i])]
            chosen = select_names(tradable, held, top_n, buffer)
            gross = 1.0
            if chosen:
                if weight_fn is not None:
                    w = weight_fn(calendar[signal], chosen).reindex(chosen).fillna(0.0)
                    # A custom weighting may invest less than everything
                    # (volatility targeting); keep that gross level.
                    gross = float(np.clip(w.sum(), 0.0, 1.0))
                elif weighting == "inverse_vol" and vol is not None:
                    v = vol.iloc[signal].reindex(chosen)
                    w = (1.0 / v.where(v > 0)).fillna(0.0)
                    if w.sum() <= 0:
                        w = pd.Series(1.0, index=chosen)
                else:
                    w = pd.Series(1.0, index=chosen)
                w = cap_weights(w, max_weight) * gross
            else:
                w = pd.Series(dtype=float)
            scale = 1.0
            if exposure is not None:
                e = exposure.reindex([calendar[signal]]).iloc[0] if calendar[signal] in exposure.index else np.nan
                scale = float(np.clip(e, 0.0, 1.0)) if not np.isnan(e) else 1.0
            target_units = np.zeros(len(symbols))
            stuck = np.isnan(o[i]) & (units > 0)
            target_units[stuck] = units[stuck]
            stuck_value = float(np.sum(units[stuck] * px_open[stuck]))
            investable = max(equity_open * scale - stuck_value, 0.0)
            for s, weight in w.items():
                j = symbols.index(s)
                if weight > 0 and o[i, j] > 0:
                    target_units[j] = investable * weight / o[i, j]
            delta = (target_units - units) * px_open
            bought = float(delta[delta > 0].sum())
            sold = float(-delta[delta < 0].sum())
            cost = costs.cost(bought, sold)
            cash = equity_open - float(np.sum(target_units * px_open)) - cost
            units = target_units
            traded += (bought + sold) / 2.0 / max(equity_open, 1e-12)
            paid += cost / max(equity_open, 1e-12)
            rebalances += 1
            names_held.append(int((units > 0).sum()))

        value = np.where(np.isnan(c[i]), 0.0, c[i])
        equity = cash + float(np.sum(units * value))
        invested = float(np.sum(units * value))
        rets.append(equity / prev_equity - 1.0)
        eqs.append(equity)
        exps.append(invested / equity if equity > 0 else 0.0)
        days.append(calendar[i])
        prev_equity = equity

    index = pd.DatetimeIndex(days)
    years = max(len(days) / 252.0, 1e-9)
    final = {symbols[j]: float(units[j] * (c[hi - 1, j] if not np.isnan(c[hi - 1, j]) else 0.0) / max(eqs[-1], 1e-12))
             for j in np.flatnonzero(units > 0)}
    return BacktestResult(
        returns=pd.Series(rets, index=index),
        equity=pd.Series(eqs, index=index),
        exposure=pd.Series(exps, index=index),
        turnover_annual=traded / years,
        costs_annual=paid / years,
        rebalances=rebalances,
        avg_names=float(np.mean(names_held)) if names_held else 0.0,
        final_holdings=final,
    )
