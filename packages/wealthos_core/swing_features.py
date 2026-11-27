"""Cross-sectional swing-trading features and targets.

One implementation shared by the training pipeline (``ml/pipelines/p14``) and
the live signal service, so a model scores today's stocks with exactly the
features it was trained on.

Timing contract, enforced by tests:

* A feature dated ``t`` uses prices up to and including the close of ``t``.
* A target dated ``t`` is the return from the **open of t+1** (the first price
  a trader could act on after seeing the close of ``t``) to the close of
  ``t + horizon``.

Stock features are ranked across the eligible universe on each date, into
(0, 1]. Ranking makes the features comparable across 2008 and 2026, across
calm and violent markets, which is what a cross-sectional ranker needs. A few
market-wide context features (index trend, VIX, breadth) are kept raw: they
are identical for every stock on a date and tell the model which regime it is
ranking in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "FEATURE_VERSION",
    "HORIZON",
    "MIN_HISTORY",
    "STOCK_FEATURES",
    "MARKET_FEATURES",
    "FEATURES",
    "FEATURE_LABELS",
    "Wide",
    "to_wide",
    "eligibility",
    "build_features",
    "build_targets",
]

FEATURE_VERSION = "1.0"
HORIZON = 10            # sessions, about two trading weeks
MIN_HISTORY = 252       # sessions of history before a stock can be ranked
# Point-in-time size filter. The symbol list is today's NIFTY 100, so a stock
# that was small in 2014 and grew into the index is in the data *because* it
# rose: momentum-style signals then look brilliant in hindsight. On each date
# only the LIQUID_TOP stocks by trailing six-month traded value are eligible,
# which is what "a large, liquid stock at the time" means. Measured effect
# (2013-2026): equal-weight CAGR falls from 23% (all) to about 18%, and plain
# 12-1 momentum's apparent edge over equal-weight shrinks from 9.5 points to
# under 1. See the swing_features report for the sensitivity table.
LIQUID_TOP = 60
LIQUIDITY_WINDOW = 126
MIN_STOCKS_PER_DATE = 20

STOCK_FEATURES = [
    "f_ret_5", "f_ret_10", "f_ret_21", "f_ret_63", "f_ret_126", "f_ret_252",
    "f_mom_12_1", "f_dist_52w_high", "f_dist_52w_low",
    "f_px_sma20", "f_px_sma50", "f_px_sma200",
    "f_rsi_14", "f_macd_hist",
    "f_atr_pct", "f_vol_20", "f_vol_60", "f_downside_vol_60", "f_vol_of_vol",
    "f_beta_126", "f_idio_vol_126",
    "f_volume_z_20", "f_turnover_change", "f_amihud_21",
    "f_max_ret_21", "f_skew_63", "f_sector_rel_21",
]
MARKET_FEATURES = [
    "m_index_ret_21", "m_index_vol_20", "m_vix", "m_vix_change_5",
    "m_breadth_200", "m_dispersion_21",
]
FEATURES = STOCK_FEATURES + MARKET_FEATURES

# Plain-language names, used to explain a score ("why this stock").
FEATURE_LABELS = {
    "f_ret_5": "1-week return", "f_ret_10": "2-week return", "f_ret_21": "1-month return",
    "f_ret_63": "3-month return", "f_ret_126": "6-month return", "f_ret_252": "12-month return",
    "f_mom_12_1": "12-1 month momentum", "f_dist_52w_high": "distance from 52-week high",
    "f_dist_52w_low": "distance from 52-week low", "f_px_sma20": "price vs 20-day average",
    "f_px_sma50": "price vs 50-day average", "f_px_sma200": "price vs 200-day average",
    "f_rsi_14": "RSI (14)", "f_macd_hist": "MACD histogram", "f_atr_pct": "average true range",
    "f_vol_20": "1-month volatility", "f_vol_60": "3-month volatility",
    "f_downside_vol_60": "downside volatility", "f_vol_of_vol": "volatility of volatility",
    "f_beta_126": "beta to NIFTY", "f_idio_vol_126": "stock-specific volatility",
    "f_volume_z_20": "volume surge", "f_turnover_change": "turnover trend",
    "f_amihud_21": "illiquidity", "f_max_ret_21": "biggest daily jump (1 month)",
    "f_skew_63": "return skew", "f_sector_rel_21": "1-month return vs sector",
    "m_index_ret_21": "NIFTY 1-month return", "m_index_vol_20": "NIFTY volatility",
    "m_vix": "India VIX", "m_vix_change_5": "India VIX 1-week change",
    "m_breadth_200": "share of stocks above 200-day average",
    "m_dispersion_21": "spread of 1-month returns across stocks",
}

INDEX_SYMBOL = "NIFTY"
VIX_SYMBOL = "INDIAVIX"
MARKET_SERIES = {"NIFTY", "BANKNIFTY", "INDIAVIX", "SENSEX", "FINNIFTY", "MIDCPNIFTY"}


@dataclass
class Wide:
    """OHLCV as date x symbol frames on one shared session calendar."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    index_close: pd.Series | None
    vix_close: pd.Series | None

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close.index)


def to_wide(panel: pd.DataFrame) -> Wide:
    """Long OHLCV (date, symbol, open, high, low, close, volume) to wide frames.

    The session calendar is every date on which at least ``MIN_STOCKS_PER_DATE``
    stocks traded, so a stray holiday row for one symbol does not create a
    session for everyone else.
    """
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    is_market = panel["symbol"].isin(MARKET_SERIES)
    stocks = panel.loc[~is_market]
    counts = stocks.groupby("date")["symbol"].nunique()
    calendar = counts.index[counts >= min(MIN_STOCKS_PER_DATE, max(1, stocks["symbol"].nunique()))]
    calendar = pd.DatetimeIndex(sorted(calendar))

    def pivot(field: str) -> pd.DataFrame:
        frame = stocks.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        return frame.reindex(calendar).sort_index(axis=1).astype(float)

    def series(symbol: str) -> pd.Series | None:
        one = panel.loc[panel["symbol"] == symbol].set_index("date")["close"]
        if one.empty:
            return None
        one = one[~one.index.duplicated(keep="last")].astype(float)
        # Index and VIX are carried forward across the odd missing session
        # (Yahoo gaps); they are context, not something traded.
        return one.reindex(calendar).ffill()

    return Wide(
        open=pivot("open"), high=pivot("high"), low=pivot("low"),
        close=pivot("close"), volume=pivot("volume"),
        index_close=series(INDEX_SYMBOL), vix_close=series(VIX_SYMBOL),
    )


def eligibility(w: Wide, liquid_top: int | None = LIQUID_TOP) -> pd.DataFrame:
    """True where a stock may be ranked on a date.

    It needs a price today, a year of history, and (unless ``liquid_top`` is
    None) a place among the ``liquid_top`` most-traded stocks by trailing
    six-month traded value, measured with data up to that date only.
    """
    history = w.close.notna().cumsum()
    base = w.close.notna() & (history >= MIN_HISTORY)
    if liquid_top is None:
        return base
    traded = (w.close * w.volume).rolling(LIQUIDITY_WINDOW, min_periods=100).mean().where(base)
    return base & (traded.rank(axis=1, ascending=False, method="first") <= liquid_top)


def _xs_rank(frame: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank within each date, over eligible stocks only."""
    masked = frame.where(eligible)
    return masked.rank(axis=1, pct=True)


def _stack(features: dict[str, pd.DataFrame], eligible: pd.DataFrame) -> pd.DataFrame:
    keep = eligible.stack()
    keep = keep[keep]
    out = pd.DataFrame(index=keep.index)
    for name, frame in features.items():
        out[name] = frame.stack(future_stack=True).reindex(keep.index)
    out.index.names = ["date", "symbol"]
    return out


def build_features(w: Wide, sectors: dict[str, str] | None = None,
                   liquid_top: int | None = LIQUID_TOP) -> pd.DataFrame:
    """Feature rows for every eligible (date, symbol), columns ``FEATURES``.

    Uses only information available at each date's close.
    """
    c, h, lo, v = w.close, w.high, w.low, w.volume
    eligible = eligibility(w, liquid_top)
    # Returns over gaps (a missing session) use the last known close so a
    # one-day halt does not erase a stock's momentum.
    cf = c.ffill(limit=5)
    r1 = cf.pct_change(fill_method=None)
    lr1 = np.log(cf).diff()

    raw: dict[str, pd.DataFrame] = {}
    for n in (5, 10, 21, 63, 126, 252):
        raw[f"f_ret_{n}"] = cf / cf.shift(n) - 1.0
    raw["f_mom_12_1"] = cf.shift(21) / cf.shift(252) - 1.0
    raw["f_dist_52w_high"] = cf / cf.rolling(252, min_periods=200).max() - 1.0
    raw["f_dist_52w_low"] = cf / cf.rolling(252, min_periods=200).min() - 1.0
    for n in (20, 50, 200):
        raw[f"f_px_sma{n}"] = cf / cf.rolling(n, min_periods=n).mean() - 1.0

    delta = cf.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    raw["f_rsi_14"] = (100.0 - 100.0 / (1.0 + gain / loss)).where(loss != 0, 100.0)
    line = cf.ewm(span=12, adjust=False, min_periods=12).mean() - cf.ewm(span=26, adjust=False, min_periods=26).mean()
    raw["f_macd_hist"] = (line - line.ewm(span=9, adjust=False, min_periods=9).mean()) / cf

    prev = cf.shift(1)
    true_range = np.fmax(np.fmax(h - lo, (h - prev).abs()), (lo - prev).abs())
    raw["f_atr_pct"] = true_range.rolling(14, min_periods=10).mean() / cf

    vol20 = lr1.rolling(20, min_periods=15).std() * np.sqrt(252)
    raw["f_vol_20"] = vol20
    raw["f_vol_60"] = lr1.rolling(60, min_periods=45).std() * np.sqrt(252)
    raw["f_downside_vol_60"] = np.sqrt((lr1.clip(upper=0.0) ** 2).rolling(60, min_periods=45).mean() * 252)
    raw["f_vol_of_vol"] = vol20.rolling(60, min_periods=45).std() / vol20.rolling(60, min_periods=45).mean()

    if w.index_close is not None:
        m = np.log(w.index_close).diff()
        var_m = m.rolling(126, min_periods=100).var()
        cov = lr1.rolling(126, min_periods=100).cov(m)
        beta = cov.div(var_m, axis=0)
        raw["f_beta_126"] = beta
        var_r = lr1.rolling(126, min_periods=100).var()
        idio = (var_r - beta.pow(2).mul(var_m, axis=0)).clip(lower=0.0)
        raw["f_idio_vol_126"] = np.sqrt(idio * 252)
    else:
        raw["f_beta_126"] = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
        raw["f_idio_vol_126"] = raw["f_vol_60"]

    lv = np.log(v.where(v > 0))
    raw["f_volume_z_20"] = (lv - lv.rolling(20, min_periods=15).mean()) / lv.rolling(20, min_periods=15).std()
    raw["f_turnover_change"] = np.log(
        v.rolling(5, min_periods=3).mean() / v.rolling(63, min_periods=45).mean()
    )
    traded_value = (cf * v).where(v > 0)
    raw["f_amihud_21"] = np.log((r1.abs() / traded_value).rolling(21, min_periods=15).mean() * 1e9)
    raw["f_max_ret_21"] = r1.rolling(21, min_periods=15).max()
    raw["f_skew_63"] = r1.rolling(63, min_periods=45).skew()

    ret21 = raw["f_ret_21"].where(eligible)
    if sectors:
        sector_of = pd.Series({s: sectors.get(s, "Other") for s in c.columns})
        sector_mean = ret21.T.groupby(sector_of).transform("mean").T
        raw["f_sector_rel_21"] = ret21 - sector_mean
    else:
        raw["f_sector_rel_21"] = ret21.sub(ret21.mean(axis=1), axis=0)

    ranked = {name: _xs_rank(frame, eligible) for name, frame in raw.items()}

    # Market context: one value per date, broadcast to every stock.
    market: dict[str, pd.Series] = {}
    if w.index_close is not None:
        idx = w.index_close
        market["m_index_ret_21"] = idx / idx.shift(21) - 1.0
        market["m_index_vol_20"] = np.log(idx).diff().rolling(20, min_periods=15).std() * np.sqrt(252)
    else:
        market["m_index_ret_21"] = pd.Series(np.nan, index=c.index)
        market["m_index_vol_20"] = pd.Series(np.nan, index=c.index)
    if w.vix_close is not None:
        market["m_vix"] = w.vix_close
        market["m_vix_change_5"] = np.log(w.vix_close / w.vix_close.shift(5))
    else:
        market["m_vix"] = pd.Series(np.nan, index=c.index)
        market["m_vix_change_5"] = pd.Series(np.nan, index=c.index)
    above = (cf > cf.rolling(200, min_periods=200).mean()).where(eligible)
    market["m_breadth_200"] = above.sum(axis=1) / eligible.sum(axis=1).replace(0, np.nan)
    market["m_dispersion_21"] = ret21.std(axis=1)

    columns = dict(ranked)
    for name, s in market.items():
        columns[name] = pd.DataFrame(np.repeat(s.to_numpy()[:, None], c.shape[1], axis=1),
                                     index=c.index, columns=c.columns)
    out = _stack({k: columns[k] for k in FEATURES}, eligible)
    return out.astype("float32")


def build_targets(w: Wide, horizon: int = HORIZON, liquid_top: int | None = LIQUID_TOP) -> pd.DataFrame:
    """Forward returns for each eligible (date, symbol).

    ``fwd_ret``: open of t+1 to close of t+horizon.
    ``excess``: ``fwd_ret`` minus the eligible universe's mean that date.
    ``rank``: percentile of ``excess`` within the date.
    ``bucket``: 0..4 quintile of ``rank`` (relevance labels for LambdaRank).
    """
    eligible = eligibility(w, liquid_top)
    entry = w.open.shift(-1)
    exit_ = w.close.shift(-horizon)
    fwd = exit_ / entry - 1.0
    fwd = fwd.where(eligible)
    excess = fwd.sub(fwd.mean(axis=1), axis=0)
    rank = excess.rank(axis=1, pct=True)
    bucket = np.floor(rank * 5).clip(upper=4)
    out = _stack({"fwd_ret": fwd, "excess": excess, "rank": rank, "bucket": bucket}, eligible)
    return out.dropna(subset=["fwd_ret"])
