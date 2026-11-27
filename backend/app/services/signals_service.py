"""Today's swing-model signals: scores, ranges, volatility, regime, reasons.

Everything is computed from the live daily price store (two years of Yahoo
daily bars, refreshed after each close) with the *same* feature code the
models were trained on (``wealthos_core.swing_features``), then cached until
the store changes.

What a user sees for each stock:

* the ensemble score and its rank among the eligible universe;
* a calibrated 80% range for the next 10 sessions' return;
* forecast volatility, and the stop and target it implies for their profile;
* the three features that pushed the score most (from the LightGBM ranker's
  SHAP contributions), in plain words.

Signals are research output for paper trading, never investment advice; every
payload carries that disclaimer and the model's out-of-sample record.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dtime

import numpy as np
import pandas as pd

from app.ml_runtime.registry import registry
from app.services import live_market_service as live
from wealthos_core import swing_features as sf
from wealthos_core.allocation import RiskProfile, profile_for, regime_exposure
from wealthos_core.regime import filtered_probabilities
from wealthos_core.volatility import vol_design

log = logging.getLogger("wealthos.signals")

DISCLAIMER = ("Research signal from models trained on past prices, for paper trading only. "
              "Not investment advice: past out-of-sample results do not promise future returns.")
STATES = ("calm", "normal", "stress")
BAR_FINAL = dtime(16, 0)


class SignalsUnavailable(Exception):
    """The models or the price history needed for signals are missing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Snapshot:
    as_of: pd.Timestamp
    table: pd.DataFrame                      # index symbol, one row per eligible stock
    regime: dict
    card: dict
    wide: sf.Wide
    features: pd.DataFrame                   # full (date, symbol) feature panel
    extras: dict = field(default_factory=dict)


_lock = threading.Lock()
_cache: dict[tuple, Snapshot] = {}


# --------------------------------------------------------------------------- inputs

def _price_panel() -> pd.DataFrame:
    frame = live.daily_store.frame()
    if frame is None or frame.empty:
        raise SignalsUnavailable(
            "market_data_unavailable",
            "Daily price history is not available yet. It downloads on first use; try again in a minute.")
    now = live.now_ist()
    if now.time() < BAR_FINAL:
        # Today's bar is still forming (or Yahoo has not finalised it).
        frame = frame.loc[frame["date"].dt.date < now.date()]
    # A file downloaded during a session holds that session's bar as it was
    # then: partial. A bar counts only if the file was written after that
    # session's bar became final.
    try:
        written = datetime.fromtimestamp(live._daily_path().stat().st_mtime, tz=live.IST)
    except OSError:
        written = now
    if not frame.empty:
        last = frame["date"].max()
        final_at = datetime.combine(last.date(), BAR_FINAL, tzinfo=live.IST)
        if written < final_at:
            frame = frame.loc[frame["date"] < last]
    return frame


def _sectors() -> dict[str, str]:
    uni = live.universe()
    return dict(zip(uni["symbol"], uni["sector"])) if not uni.empty else {}


def _names() -> dict[str, str]:
    uni = live.universe()
    return dict(zip(uni["symbol"], uni["name"])) if not uni.empty else {}


def _require_models() -> dict:
    ranker = registry.swing_ranker()
    if ranker is None:
        raise SignalsUnavailable(
            "models_unavailable",
            "The swing models have not been trained on this server yet. Run `make swing` to train them.")
    return ranker


# --------------------------------------------------------------------------- pieces

def _ridge_scores(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    x = (frame[sf.FEATURES].fillna(bundle["fill"]) - bundle["mu"]) / bundle["sd"]
    return bundle["model"].predict(x.to_numpy())


def model_scores(ranker: dict, rows: pd.DataFrame) -> pd.DataFrame:
    """Each model's raw score and the deployed ensemble (mean of within-date ranks)."""
    x = rows[ranker["features"]]
    out = pd.DataFrame(index=rows.index)
    out["lgbm_ranker"] = ranker["model"].predict(x)
    if ranker.get("regressor") is not None:
        out["lgbm_regressor"] = ranker["regressor"].predict(x)
    if ranker.get("ridge") is not None:
        out["ridge"] = _ridge_scores(ranker["ridge"], rows)
    level = "date" if "date" in (rows.index.names or []) else None
    ranks = out.groupby(level=level).rank(pct=True) if level else out.rank(pct=True)
    out["ensemble"] = ranks.mean(axis=1)
    return out


def _drivers(ranker: dict, rows: pd.DataFrame, k: int = 3) -> list[list[dict]]:
    contrib = ranker["model"].predict(rows[ranker["features"]], pred_contrib=True)[:, :-1]
    names = ranker["features"]
    stock_cols = [i for i, n in enumerate(names) if n in sf.STOCK_FEATURES]
    out = []
    for r, row in enumerate(contrib):
        order = sorted(stock_cols, key=lambda i: -abs(row[i]))[:k]
        items = []
        for i in order:
            pct = rows.iloc[r][names[i]]
            items.append({
                "feature": names[i],
                "label": sf.FEATURE_LABELS.get(names[i], names[i]),
                "percentile": None if pd.isna(pct) else int(round(float(pct) * 100)),
                "effect": "raises" if row[i] > 0 else "lowers",
                "weight": round(float(row[i]), 4),
            })
        out.append(items)
    return out


def _quantiles(rows: pd.DataFrame) -> pd.DataFrame | None:
    q = registry.swing_quantiles()
    if q is None:
        return None
    preds = np.column_stack([q["models"][level].predict(rows[q["features"]]) for level in q["quantiles"]])
    preds = np.sort(preds, axis=1)
    adj = float(q.get("conformal_adjustment", 0.0))
    return pd.DataFrame({"q10": preds[:, 0] - adj, "q50": preds[:, 1], "q90": preds[:, -1] + adj}, index=rows.index)


def _volatility(w: sf.Wide, symbols: list[str]) -> pd.Series:
    """Annualised 10-session volatility forecast per symbol (falls back to trailing)."""
    design = vol_design(w.close, w.high, w.low)
    last = w.close.index[-1]
    frame = pd.DataFrame({k: v.loc[last].reindex(symbols) for k, v in design.items()})
    trailing = frame["rv_22"]
    bundle = registry.swing_vol()
    if bundle is None:
        return trailing
    idx_vol = (np.log(w.index_close).diff().rolling(20, min_periods=15).std() * np.sqrt(252)).iloc[-1] \
        if w.index_close is not None else np.nan
    frame["vix"] = (w.vix_close.iloc[-1] / 100.0) if w.vix_close is not None else np.nan
    frame["index_vol_20"] = idx_vol
    if bundle.get("serving_model") == "lgbm" and bundle.get("lgbm") is not None:
        pred = np.exp(bundle["lgbm"].predict(frame[bundle["lgbm_features"]]) + bundle["lgbm_resid_var"] / 2.0)
    else:
        coef = np.asarray(bundle["har_coef"])
        x = np.column_stack([np.ones(len(frame))] + [np.log(np.clip(frame[c].to_numpy(float), 1e-4, None))
                                                     for c in ("rv_1", "rv_5", "rv_22")])
        with np.errstate(all="ignore"):
            pred = np.exp(x @ coef + bundle["har_resid_var"] / 2.0)
    out = pd.Series(pred, index=symbols)
    return out.where(np.isfinite(out) & (out > 0), trailing)


def _regime(w: sf.Wide) -> dict:
    params = registry.swing_regime()
    if params is None or w.index_close is None or w.vix_close is None:
        return {"available": False, "reason": "The regime model is not trained on this server."}
    from ml.pipelines.p17_train_regime import observations

    obs = observations(w)
    x = (obs[params["observations"]].to_numpy() - np.asarray(params["scaler_mean"])) / np.asarray(params["scaler_std"])
    probs = filtered_probabilities(x, np.asarray(params["startprob"]), np.asarray(params["transmat"]),
                                   np.asarray(params["means"]), np.asarray(params["covars"]))
    frame = pd.DataFrame(probs, index=obs.index, columns=list(params["state_names"]))
    now = frame.iloc[-1]
    state = str(now.idxmax())
    base = float(sum(now[s] * params["exposure"][s] for s in STATES))
    history = frame.iloc[-120:]
    return {
        "available": True,
        "as_of": str(frame.index[-1].date()),
        "state": state,
        "probabilities": {s: round(float(now[s]), 4) for s in STATES},
        "base_exposure": round(base, 4),
        "exposure_map": params["exposure"],
        "history": [{"date": str(d.date()), **{s: round(float(r[s]), 4) for s in STATES}}
                    for d, r in history.iterrows()],
        "trained_through": params.get("trained_through"),
        "method": "Gaussian hidden Markov model on NIFTY return, NIFTY volatility and India VIX; "
                  "filtered probabilities (uses data up to today only).",
    }


def _card(ranker: dict) -> dict:
    oos = ranker.get("oos", {})
    vol = registry.swing_vol()
    return {
        "deployed": ranker.get("deployed", "lgbm_ranker"),
        "version": ranker.get("version"),
        "feature_version": ranker.get("feature_version"),
        "trained_through": ranker.get("trained_through"),
        "recommended": bool(ranker.get("recommended")),
        "oos": {
            "first_test_year": oos.get("first_test_year"),
            "mean_ic": oos.get("mean_ic"),
            "t_stat": oos.get("t_stat"),
            "hit_rate": (oos.get("hit_rate") or {}).get("relative"),
            "top_decile_positive": (oos.get("hit_rate") or {}).get("top_decile_positive"),
            "cagr": (oos.get("backtest") or {}).get("cagr"),
            "max_drawdown": (oos.get("backtest") or {}).get("max_drawdown"),
            "sharpe": (oos.get("backtest") or {}).get("sharpe"),
            "equal_weight_cagr": (oos.get("equal_weight") or {}).get("cagr"),
            "equal_weight_max_drawdown": (oos.get("equal_weight") or {}).get("max_drawdown"),
        },
        "volatility_model": (vol or {}).get("serving_model"),
        "horizon_sessions": ranker.get("horizon", sf.HORIZON),
        "universe": f"Top {ranker.get('liquid_top', sf.LIQUID_TOP)} NIFTY 100 stocks by six-month traded value",
    }


# --------------------------------------------------------------------------- snapshot

def snapshot() -> Snapshot:
    ranker = _require_models()
    frame = _price_panel()
    key = (len(frame), str(frame["date"].max()), ranker.get("version"), ranker.get("trained_through"))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        w = sf.to_wide(frame)
        features = sf.build_features(w, _sectors(), liquid_top=ranker.get("liquid_top", sf.LIQUID_TOP))
        if features.empty:
            raise SignalsUnavailable("market_data_unavailable",
                                     "Not enough price history to compute the swing features yet.")
        last = features.index.get_level_values("date").max()
        rows = features.xs(last, level="date")
        scores = model_scores(ranker, rows)
        table = pd.DataFrame(index=rows.index)
        table["score"] = scores["ensemble"]
        table["rank"] = table["score"].rank(ascending=False, method="first").astype(int)
        table["percentile"] = (table["score"].rank(pct=True) * 100).round(0)
        for col in scores.columns:
            table[f"model_{col}"] = scores[col]
        q = _quantiles(rows)
        if q is not None:
            table = table.join(q)
        symbols = list(rows.index)
        table["vol_annual"] = _volatility(w, symbols)
        table["last_close"] = w.close.loc[last].reindex(symbols)
        table["drivers"] = _drivers(ranker, rows)
        names, sectors = _names(), _sectors()
        table["name"] = [names.get(s, s) for s in symbols]
        table["sector"] = [sectors.get(s, "") for s in symbols]
        snap = Snapshot(as_of=pd.Timestamp(last), table=table.sort_values("rank"), regime=_regime(w),
                        card=_card(ranker), wide=w, features=features)
        _cache.clear()
        _cache[key] = snap
        return snap


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# --------------------------------------------------------------------------- views

def _num(v, digits: int = 4):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    return round(float(v), digits)


def row_view(symbol: str, r: pd.Series, profile: RiskProfile, universe: int) -> dict:
    vol10 = float(r["vol_annual"]) * np.sqrt(sf.HORIZON / 252.0) if pd.notna(r.get("vol_annual")) else None
    close = float(r["last_close"])
    return {
        "symbol": symbol,
        "name": r["name"],
        "sector": r["sector"],
        "score": _num(r["score"]),
        "rank": int(r["rank"]),
        "of": universe,
        "percentile": _num(r["percentile"], 0),
        "last_close": _num(close, 2),
        "range_10d": {"low": _num(r.get("q10")), "mid": _num(r.get("q50")), "high": _num(r.get("q90")),
                      "coverage": 0.8} if "q10" in r else None,
        "vol_annual": _num(r.get("vol_annual")),
        "vol_10d": _num(vol10),
        "stop": _num(close * (1 - profile.stop_multiple * vol10), 2) if vol10 else None,
        "target": _num(close * (1 + profile.target_multiple * vol10), 2) if vol10 else None,
        "drivers": r["drivers"],
        "models": {k.removeprefix("model_"): _num(r[k]) for k in r.index if k.startswith("model_")},
    }


def signals(risk_tolerance: str | None, limit: int = 20) -> dict:
    snap = snapshot()
    profile = profile_for(risk_tolerance)
    n = len(snap.table)
    picks = [row_view(sym, r, profile, n) for sym, r in snap.table.head(limit).iterrows()]
    return {
        "as_of": str(snap.as_of.date()),
        "horizon_sessions": sf.HORIZON,
        "universe_size": n,
        "profile": profile.as_dict(),
        "regime": {k: v for k, v in snap.regime.items() if k != "history"},
        "model": snap.card,
        "picks": picks,
        "price_source": "Yahoo daily closes",
        "disclaimer": DISCLAIMER,
    }


def signal_for(symbol: str, risk_tolerance: str | None) -> dict:
    snap = snapshot()
    symbol = symbol.upper()
    profile = profile_for(risk_tolerance)
    base = {"symbol": symbol, "as_of": str(snap.as_of.date()), "model": snap.card, "disclaimer": DISCLAIMER}
    if symbol not in snap.table.index:
        uni = set(live.universe()["symbol"])
        reason = ("Not in the NIFTY 100, which is the universe the swing models were trained on."
                  if symbol not in uni else
                  "Not among today's 60 most-traded NIFTY 100 stocks (six-month traded value), "
                  "so the models do not rank it.")
        return {**base, "eligible": False, "reason": reason}
    return {**base, "eligible": True, **row_view(symbol, snap.table.loc[symbol], profile, len(snap.table))}


def regime() -> dict:
    snap = snapshot()
    return {**snap.regime, "disclaimer": DISCLAIMER}


def profile_exposure(snap: Snapshot, profile: RiskProfile) -> float:
    if not snap.regime.get("available"):
        return profile.max_exposure * 0.8
    return float(regime_exposure(snap.regime["probabilities"], profile))
