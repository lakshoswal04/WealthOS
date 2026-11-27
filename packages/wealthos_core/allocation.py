"""Position sizing for swing baskets: risk profiles, HRP and volatility targeting.

Hierarchical Risk Parity (López de Prado, 2016) clusters stocks by
correlation and splits capital between clusters in inverse proportion to
their variance. Unlike mean-variance optimisation it never inverts the
covariance matrix, so it does not blow up on a few years of noisy daily
returns. The covariance is Ledoit-Wolf shrunk for the same reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

__all__ = ["RiskProfile", "PROFILES", "profile_for", "hrp_weights", "inverse_vol_weights",
           "vol_target_scale", "shrunk_covariance", "regime_exposure", "size_basket"]


@dataclass(frozen=True)
class RiskProfile:
    name: str
    max_names: int            # positions in the swing basket
    max_weight: float         # per stock, share of the swing allocation
    vol_target: float         # annualised portfolio volatility the sizing aims for
    max_exposure: float       # share of the amount that may be invested at all
    stop_multiple: float      # stop distance in units of 10-day forecast volatility
    target_multiple: float    # target distance, same units
    regime_floor: float       # minimum exposure multiplier in a stress regime

    def as_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, RiskProfile] = {
    "conservative": RiskProfile("conservative", max_names=10, max_weight=0.12, vol_target=0.12,
                                max_exposure=0.6, stop_multiple=1.0, target_multiple=1.5, regime_floor=0.0),
    "moderate": RiskProfile("moderate", max_names=8, max_weight=0.18, vol_target=0.18,
                            max_exposure=0.85, stop_multiple=1.25, target_multiple=2.0, regime_floor=0.25),
    "aggressive": RiskProfile("aggressive", max_names=6, max_weight=0.25, vol_target=0.25,
                              max_exposure=1.0, stop_multiple=1.5, target_multiple=2.5, regime_floor=0.5),
}


def profile_for(risk_tolerance: str | None) -> RiskProfile:
    key = (risk_tolerance or "moderate").lower()
    return PROFILES.get(key, PROFILES["moderate"])


def shrunk_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    from sklearn.covariance import LedoitWolf

    clean = returns.dropna(how="all").fillna(0.0)
    cov = LedoitWolf().fit(clean.to_numpy()).covariance_
    return pd.DataFrame(cov, index=returns.columns, columns=returns.columns)


def inverse_vol_weights(vol: pd.Series) -> pd.Series:
    inv = 1.0 / vol.where(vol > 0)
    inv = inv.fillna(0.0)
    if inv.sum() <= 0:
        return pd.Series(1.0 / len(vol), index=vol.index)
    return inv / inv.sum()


def _cluster_var(cov: pd.DataFrame, members: list[str]) -> float:
    sub = cov.loc[members, members].to_numpy()
    ivp = 1.0 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """HRP weights (non-negative, summing to 1) for the columns of ``returns``."""
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform

    cols = [c for c in returns.columns if returns[c].notna().sum() > 20 and returns[c].std() > 0]
    if len(cols) == 0:
        return pd.Series(dtype=float)
    if len(cols) == 1:
        return pd.Series(1.0, index=cols)
    r = returns[cols]
    cov = shrunk_covariance(r)
    std = np.sqrt(np.diag(cov))
    corr = cov.to_numpy() / np.outer(std, std)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    link = linkage(squareform(dist, checks=False), method="single")
    order = [cols[i] for i in leaves_list(link)]

    w = pd.Series(1.0, index=order)
    clusters = [order]
    while clusters:
        nxt = []
        for cl in clusters:
            if len(cl) <= 1:
                continue
            half = len(cl) // 2
            left, right = cl[:half], cl[half:]
            v_left, v_right = _cluster_var(cov, left), _cluster_var(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right)
            w[left] *= alpha
            w[right] *= 1.0 - alpha
            nxt += [left, right]
        clusters = nxt
    w = w.clip(lower=0.0)
    return (w / w.sum()).reindex(returns.columns).fillna(0.0)


def vol_target_scale(weights: pd.Series, cov: pd.DataFrame, target: float,
                     periods_per_year: int = 252) -> float:
    """Exposure multiplier (<= 1) that brings forecast portfolio vol to ``target``."""
    w = weights.reindex(cov.index).fillna(0.0).to_numpy()
    var = float(w @ cov.to_numpy() @ w) * periods_per_year
    if var <= 0:
        return 1.0
    return float(min(1.0, target / np.sqrt(var)))


def regime_exposure(probabilities: dict | pd.Series | pd.DataFrame, profile: RiskProfile):
    """Share of the amount to invest given regime probabilities (calm/normal/stress).

    calm 100%, normal 80%, stress at the profile's floor; then the profile's
    overall cap. Works on one date (dict/Series) or many (DataFrame).
    """
    p = probabilities
    return (p["calm"] * 1.0 + p["normal"] * 0.8 + p["stress"] * profile.regime_floor) * profile.max_exposure


def size_basket(forecast_vol: pd.Series, trailing_returns: pd.DataFrame, profile: RiskProfile,
                method: str = "inverse_vol") -> tuple[pd.Series, float, float]:
    """Weights for the chosen names, scaled to the profile's volatility target.

    ``forecast_vol``: annualised volatility forecasts, indexed by symbol.
    ``trailing_returns``: recent daily log returns of the same names (their
    correlations are taken from here).

    Returns (weights, scale, forecast portfolio vol before scaling). The
    weights sum to ``scale`` (<= 1); the rest stays in cash.
    """
    names = list(forecast_vol.index)
    window = trailing_returns.reindex(columns=names)
    trailing = window.std() * np.sqrt(252)
    vols = forecast_vol.where(forecast_vol > 0).fillna(trailing)
    vols = vols.where(vols > 0, vols[vols > 0].median() if (vols > 0).any() else 0.25).fillna(0.25)
    if method == "hrp" and len(names) > 1:
        weights = hrp_weights(window).reindex(names).fillna(0.0)
    else:
        weights = inverse_vol_weights(vols)
    if weights.sum() <= 0:
        weights = pd.Series(1.0 / len(names), index=names)
    weights = weights / weights.sum()
    # Cap each name, handing the excess to the others.
    for _ in range(50):
        over = weights > profile.max_weight + 1e-12
        if not over.any() or profile.max_weight * len(weights) < 1.0:
            break
        excess = float((weights[over] - profile.max_weight).sum())
        weights[over] = profile.max_weight
        free = ~over
        weights[free] += excess * weights[free] / weights[free].sum()
    corr = window.corr().reindex(index=names, columns=names).fillna(0.0).to_numpy()
    np.fill_diagonal(corr, 1.0)
    d = vols.to_numpy()
    cov = corr * np.outer(d, d)
    w = weights.to_numpy()
    port_vol = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    scale = min(1.0, profile.vol_target / port_vol) if port_vol > 0 else 1.0
    return weights * scale, scale, port_vol
