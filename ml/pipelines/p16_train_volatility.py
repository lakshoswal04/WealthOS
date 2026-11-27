"""Stage 16 — 10-session volatility forecasts per stock.

Volatility, unlike return, is genuinely forecastable: it clusters. A good
forecast sizes positions (equal *risk*, not equal rupees), sets stop
distances that respect how much a stock normally moves, and lets the
portfolio aim at a volatility target.

Models, walk-forward on the same yearly folds as the ranker:

* naive: trailing one-month realised volatility (what most retail tools show);
* HAR-RV: pooled log regression on day, week and month realised volatility;
* GARCH(1,1): fitted per stock on its training window (``arch``);
* LightGBM: HAR inputs plus range-based (Parkinson) volatility, downside
  volatility and the market's state (India VIX, NIFTY volatility).

Scored by QLIKE (the standard loss for variance forecasts, robust to noisy
proxies), out-of-sample R-squared of log volatility, and MAE.

Run:  python -m ml.pipelines.p16_train_volatility [--quick]
"""

from __future__ import annotations

import argparse
import warnings

import joblib
import numpy as np
import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.volatility import HAR, VOL_FEATURES, forward_realised_vol, vol_design

from .common import Stage, get_logger, silence_accelerate_matmul_warnings, write_report
from .swing_common import (MODEL_VERSION, RANDOM_STATE, VOL_OOS_PATH, clean_json, folds, load_wide, model_path)

log = get_logger("volatility")

HORIZON = sf.HORIZON
MARKET_INPUTS = ["vix", "index_vol_20"]
LGBM_FEATURES = VOL_FEATURES + MARKET_INPUTS
MODELS = ("naive_rv22", "har", "garch", "lgbm")
LGBM_PARAMS = {"n_estimators": 400, "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 200,
               "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8}


def build_panel(w: sf.Wide) -> pd.DataFrame:
    design = vol_design(w.close, w.high, w.low)
    target = forward_realised_vol(w.close, HORIZON)
    eligible = sf.eligibility(w, liquid_top=None)
    keep = eligible.stack()
    keep = keep[keep].index
    out = pd.DataFrame(index=keep)
    for name, frame in design.items():
        out[name] = frame.stack(future_stack=True).reindex(keep)
    idx_vol = np.log(w.index_close).diff().rolling(20, min_periods=15).std() * np.sqrt(252) \
        if w.index_close is not None else pd.Series(np.nan, index=w.close.index)
    vix = w.vix_close / 100.0 if w.vix_close is not None else pd.Series(np.nan, index=w.close.index)
    dates = out.index.get_level_values(0)
    out["vix"] = vix.reindex(dates).to_numpy()
    out["index_vol_20"] = idx_vol.reindex(dates).to_numpy()
    out["target"] = target.stack(future_stack=True).reindex(keep)
    out.index.names = ["date", "symbol"]
    return out.dropna(subset=["rv_22"])


def qlike(actual_vol: np.ndarray, pred_vol: np.ndarray) -> float:
    a, p = actual_vol ** 2, pred_vol ** 2
    ok = (a > 0) & (p > 0) & np.isfinite(a) & np.isfinite(p)
    ratio = a[ok] / p[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def scores(actual: np.ndarray, pred: np.ndarray, train_mean_log: float) -> dict:
    ok = np.isfinite(actual) & np.isfinite(pred) & (actual > 0) & (pred > 0)
    a, p = actual[ok], pred[ok]
    la, lp = np.log(a), np.log(p)
    ss_res = float(np.sum((la - lp) ** 2))
    ss_tot = float(np.sum((la - train_mean_log) ** 2))
    return {
        "qlike": qlike(a, p),
        "r2_log_vs_train_mean": 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
        "mae_vol": float(np.mean(np.abs(a - p))),
        "bias_vol": float(np.mean(p - a)),
        "rows": int(ok.sum()),
    }


def fit_lgbm(train: pd.DataFrame):
    import lightgbm as lgb

    ok = train["target"].notna() & (train["target"] > 0)
    model = lgb.LGBMRegressor(objective="regression", random_state=RANDOM_STATE, verbose=-1, n_jobs=-1, **LGBM_PARAMS)
    y = np.log(train.loc[ok, "target"])
    model.fit(train.loc[ok, LGBM_FEATURES], y)
    resid_var = float(np.var(y - model.predict(train.loc[ok, LGBM_FEATURES])))
    return model, resid_var


def garch_forecasts(w: sf.Wide, train_end: pd.Timestamp, test_start: pd.Timestamp,
                    test_end: pd.Timestamp, symbols: list[str], lookback_years: int = 6) -> pd.Series:
    """Average 10-step-ahead GARCH(1,1) volatility per stock, per test day."""
    from arch import arch_model

    out = []
    for sym in symbols:
        r = np.log(w.close[sym].ffill(limit=5)).diff().dropna() * 100.0
        r = r.loc[r.index >= train_end - pd.DateOffset(years=lookback_years)]
        r = r.loc[r.index <= test_end]
        train_part = r.loc[r.index <= train_end]
        if len(train_part) < 500 or (r.index >= test_start).sum() == 0:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = arch_model(r, mean="Constant", vol="GARCH", p=1, q=1, dist="normal", rescale=False) \
                    .fit(disp="off", last_obs=train_part.index[-1] + pd.Timedelta(days=1), show_warning=False)
                fc = res.forecast(horizon=HORIZON, start=test_start, reindex=False)
        except Exception:  # noqa: BLE001 - a failed fit drops one stock-year, not the stage
            continue
        var = fc.variance.mean(axis=1)
        vol = np.sqrt(var * 252.0) / 100.0
        vol.index = pd.MultiIndex.from_arrays([vol.index, [sym] * len(vol)], names=["date", "symbol"])
        out.append(vol)
    return pd.concat(out) if out else pd.Series(dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip GARCH (smoke run)")
    args = parser.parse_args()
    silence_accelerate_matmul_warnings()

    w = load_wide()
    with Stage(log, "build volatility panel"):
        panel = build_panel(w)
    dates = pd.DatetimeIndex(panel.index.get_level_values("date"))
    labelled = panel["target"].notna()

    preds, fold_log = [], []
    for f in folds(dates[labelled]):
        with Stage(log, f"fold {f.test_year}"):
            train = panel.loc[(dates <= f.train_end) & labelled]
            mask = (dates >= f.test_start) & (dates <= f.test_end)
            test = panel.loc[mask]
            har = HAR().fit(train, train["target"])
            lgbm, resid = fit_lgbm(train)
            out = pd.DataFrame({
                "naive_rv22": test["rv_22"],
                "har": har.predict(test),
                "lgbm": np.exp(lgbm.predict(test[LGBM_FEATURES]) + resid / 2.0),
            }, index=test.index)
            if not args.quick:
                g = garch_forecasts(w, f.train_end, f.test_start, f.test_end,
                                    sorted(test.index.get_level_values("symbol").unique()))
                out["garch"] = g.reindex(out.index)
            out["target"] = test["target"]
            preds.append(out)
            train_mean_log = float(np.log(train["target"][train["target"] > 0]).mean())
            fold_log.append({**f.as_dict(), "scores": {
                m: scores(out["target"].to_numpy(), out[m].to_numpy(), train_mean_log)
                for m in MODELS if m in out}})

    oos = pd.concat(preds).sort_index()
    full_train_mean = float(np.log(panel.loc[labelled & (panel["target"] > 0), "target"]).mean())
    # GARCH covers fewer rows (it needs history per stock): compare all models
    # on the rows every model scored, and also report each on its own rows.
    present = [m for m in MODELS if m in oos]
    common = oos.dropna(subset=present + ["target"])
    overall = {m: scores(common["target"].to_numpy(), common[m].to_numpy(), full_train_mean) for m in present}
    best = min(present, key=lambda m: overall[m]["qlike"])
    by_year = {m: {int(y): qlike(g["target"].to_numpy(), g[m].to_numpy())
                   for y, g in common.groupby(common.index.get_level_values("date").year)} for m in present}

    oos_best = oos[["har", "lgbm", "naive_rv22"]].copy()
    oos_best.to_parquet(VOL_OOS_PATH)

    with Stage(log, "final fit"):
        all_train = panel.loc[labelled]
        har = HAR().fit(all_train, all_train["target"])
        lgbm, resid = fit_lgbm(all_train)
    serving = "lgbm" if overall["lgbm"]["qlike"] <= overall["har"]["qlike"] else "har"
    joblib.dump({
        "har_coef": har.coef_.tolist(), "har_resid_var": har.resid_var_,
        "lgbm": lgbm, "lgbm_resid_var": resid, "lgbm_features": LGBM_FEATURES,
        "serving_model": serving, "horizon": HORIZON, "version": MODEL_VERSION,
        "trained_through": str(dates[labelled].max().date()),
        "oos": overall,
    }, model_path("swing_vol.joblib"))

    write_report("swing_volatility", clean_json({
        "version": MODEL_VERSION,
        "question": "How volatile will each stock be over the next 10 sessions (annualised)?",
        "target": "Annualised realised volatility of daily log returns over sessions t+1..t+10",
        "models": list(present),
        "overall_common_rows": overall,
        "qlike_by_year": by_year,
        "folds": fold_log,
        "best_by_qlike": best,
        "serving_model": serving,
        "serving_note": ("GARCH needs per-stock state and refits, so serving uses the better of HAR and LightGBM; "
                         "GARCH is reported as the classical comparison."),
        "improvement_vs_naive_qlike": 1.0 - overall[best]["qlike"] / overall["naive_rv22"]["qlike"],
    }))
    log.info("QLIKE: %s; best=%s; serving=%s", {m: round(v["qlike"], 4) for m, v in overall.items()}, best, serving)


if __name__ == "__main__":
    main()
