"""Volatility features and the HAR-RV forecaster (Corsi, 2009).

Volatility is far more predictable than returns: it clusters, and the
average of the last day, week and month of realised volatility forecasts the
next fortnight well. HAR-RV is exactly that regression, and is the standard
baseline any fancier volatility model has to beat.

Everything here works on wide (date x symbol) frames so the same code builds
the training panel and today's forecasts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["VOL_FEATURES", "parkinson_variance", "vol_design", "forward_realised_vol", "HAR"]

VOL_FEATURES = ["rv_1", "rv_5", "rv_22", "pk_5", "pk_22", "neg_rv_5", "abs_ret_1"]


def parkinson_variance(high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    """Daily range-based variance estimate; zero ranges (stale Yahoo rows) are NaN."""
    hl = np.log(high / low)
    return (hl ** 2 / (4.0 * np.log(2.0))).where(hl > 0)


def vol_design(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Annualised volatility inputs known at each close."""
    r = np.log(close.ffill(limit=5)).diff()
    sq = r ** 2
    pk = parkinson_variance(high, low)
    ann = 252.0
    return {
        "rv_1": np.sqrt(sq * ann),
        "rv_5": np.sqrt(sq.rolling(5, min_periods=4).mean() * ann),
        "rv_22": np.sqrt(sq.rolling(22, min_periods=18).mean() * ann),
        "pk_5": np.sqrt(pk.rolling(5, min_periods=3).mean() * ann),
        "pk_22": np.sqrt(pk.rolling(22, min_periods=15).mean() * ann),
        "neg_rv_5": np.sqrt((r.clip(upper=0) ** 2).rolling(5, min_periods=4).mean() * ann),
        "abs_ret_1": r.abs() * np.sqrt(ann),
    }


def forward_realised_vol(close: pd.DataFrame, horizon: int = 10) -> pd.DataFrame:
    """Annualised realised volatility over the next ``horizon`` sessions (t+1..t+h)."""
    r = np.log(close.ffill(limit=5)).diff()
    fwd = (r ** 2).rolling(horizon, min_periods=horizon - 2).mean().shift(-horizon)
    return np.sqrt(fwd * 252.0)


class HAR:
    """log RV_{t+1..t+h} = b0 + b1 log RV_d + b2 log RV_w + b3 log RV_m (pooled OLS).

    Fitted in logs so forecasts are positive and the heavy right tail of
    volatility does not dominate the least-squares fit.
    """

    inputs = ("rv_1", "rv_5", "rv_22")

    def __init__(self) -> None:
        self.coef_: np.ndarray | None = None
        self.resid_var_: float = 0.0

    @staticmethod
    def _x(frame: pd.DataFrame) -> np.ndarray:
        cols = [np.log(np.clip(frame[c].to_numpy(float), 1e-4, None)) for c in HAR.inputs]
        return np.column_stack([np.ones(len(frame))] + cols)

    def fit(self, frame: pd.DataFrame, target: pd.Series) -> HAR:
        ok = frame[list(self.inputs)].notna().all(axis=1) & target.notna() & (target > 0)
        x = self._x(frame.loc[ok])
        y = np.log(target.loc[ok].to_numpy(float))
        self.coef_, *_ = np.linalg.lstsq(x, y, rcond=None)
        # errstate: macOS Accelerate raises spurious matmul warnings on finite input.
        with np.errstate(all="ignore"):
            self.resid_var_ = float(np.var(y - x @ self.coef_))
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("HAR is not fitted")
        x = self._x(frame)
        # exp(E[log v] + var/2) is the mean of a log-normal, not its median.
        with np.errstate(all="ignore"):
            return np.exp(x @ self.coef_ + self.resid_var_ / 2.0)
