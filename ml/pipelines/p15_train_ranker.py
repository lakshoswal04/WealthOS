"""Stage 15 — the cross-sectional swing ranker (LightGBM), walk-forward tested.

Question the model answers: of today's eligible large, liquid stocks, which
will do best *relative to the others* over the next two trading weeks? That
is how quant equity funds frame stock selection: market direction is left to
the regime and sizing layers.

Design:

* Hyperparameters are searched with Optuna on 2011-2012 only (inner folds),
  then frozen. Every year from 2013 onward is scored by a model that was
  trained only on earlier data, purged and embargoed (``swing_common``).
* Models: LightGBM LambdaRank, LightGBM regression on the rank target, a
  ridge regression (so a mentor can see what the trees add over linear), and
  their **ensemble** (mean of the three daily ranks), which is the deployed
  signal. Smoothing scores over 5 or 10 days to cut turnover was tried and
  rejected (the signal decays within days); those variants are reported and
  charged to the deflated Sharpe ratio.
* Baselines: 12-1 month momentum, 1-week reversal, random.
* LightGBM quantile models (10/50/90%) give each pick a 10-day return range,
  conformally calibrated on the last training year of every fold.
* Every score is judged by IC, hit rate, decile spread and a top-10, weekly,
  cost-paying backtest against the equal-weight universe and NIFTY, then by
  the deflated Sharpe ratio, which charges for the number of variants tried.

Run:  python -m ml.pipelines.p15_train_ranker [--quick]
"""

from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.conformal import apply_adjustment, coverage, cqr_adjustment
from wealthos_core.metrics import deflated_sharpe_ratio
from wealthos_core.validation import daily_rank_ic, ic_summary, signal_report, yearly_folds

from .common import Stage, get_logger, silence_accelerate_matmul_warnings, write_report
from .swing_common import (EMBARGO, FIRST_TEST_YEAR, MODEL_VERSION, OOS_PATH, RANDOM_STATE, TUNING_YEARS,
                           backtest_scores, benchmarks, clean_json, date_level, folds, gate, load_panel,
                           load_wide, model_path)

log = get_logger("ranker")

FEATURES = sf.FEATURES
QUANTILES = (0.1, 0.5, 0.9)
BASE_MODELS = ("lgbm_ranker", "lgbm_regressor", "ridge")
MODELS = BASE_MODELS + ("ensemble",)
DEPLOYED = "ensemble"
SMOOTHING_WINDOWS = (5, 10)
BASELINES = ("momentum_12_1", "reversal_1w", "random")


# --------------------------------------------------------------------------- models

def _group_sizes(frame: pd.DataFrame) -> np.ndarray:
    return frame.groupby(level="date", sort=False).size().to_numpy()


def fit_ranker(train: pd.DataFrame, params: dict):
    import lightgbm as lgb

    model = lgb.LGBMRanker(objective="lambdarank", random_state=RANDOM_STATE, verbose=-1,
                           n_jobs=-1, **params)
    model.fit(train[FEATURES], train["bucket"].astype(int), group=_group_sizes(train))
    return model


def fit_regressor(train: pd.DataFrame, params: dict):
    import lightgbm as lgb

    model = lgb.LGBMRegressor(objective="regression", random_state=RANDOM_STATE, verbose=-1,
                              n_jobs=-1, **params)
    model.fit(train[FEATURES], train["rank"] - 0.5)
    return model


def fit_ridge(train: pd.DataFrame):
    from sklearn.linear_model import Ridge

    x = train[FEATURES]
    fill = x.median()
    mu, sd = x.fillna(fill).mean(), x.fillna(fill).std().replace(0, 1)
    model = Ridge(alpha=10.0).fit(((x.fillna(fill) - mu) / sd).to_numpy(), (train["rank"] - 0.5).to_numpy())
    return {"model": model, "fill": fill, "mu": mu, "sd": sd}


def predict_ridge(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    x = (frame[FEATURES].fillna(bundle["fill"]) - bundle["mu"]) / bundle["sd"]
    return bundle["model"].predict(x.to_numpy())


def fit_quantiles(train: pd.DataFrame, params: dict) -> dict:
    import lightgbm as lgb

    out = {}
    small = {**params, "n_estimators": min(int(params.get("n_estimators", 300)), 300)}
    for q in QUANTILES:
        m = lgb.LGBMRegressor(objective="quantile", alpha=q, random_state=RANDOM_STATE, verbose=-1,
                              n_jobs=-1, **small)
        m.fit(train[FEATURES], train["fwd_ret"])
        out[q] = m
    return out


def predict_quantiles(models: dict, frame: pd.DataFrame) -> pd.DataFrame:
    preds = pd.DataFrame({f"q{int(q * 100)}": models[q].predict(frame[FEATURES]) for q in QUANTILES},
                         index=frame.index)
    # Quantile models are fitted separately and can cross; sort each row.
    preds[:] = np.sort(preds.to_numpy(), axis=1)
    return preds


def baseline_scores(frame: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_STATE)
    return pd.DataFrame({
        "momentum_12_1": frame["f_mom_12_1"],
        "reversal_1w": 1.0 - frame["f_ret_5"],
        "random": rng.random(len(frame)),
    }, index=frame.index)


def ensemble(scores: pd.DataFrame) -> pd.Series:
    """Mean of the three models' percentile ranks within each date."""
    ranks = scores[list(BASE_MODELS)].groupby(level="date").rank(pct=True)
    return ranks.mean(axis=1)


def smoothing_study(oos: pd.DataFrame, w) -> list[dict]:
    """Average each stock's daily rank over n days: less turnover, staler signal."""
    start = date_level(oos).min()
    rows = []
    for m in MODELS:
        wide = oos[m].unstack("symbol").rank(axis=1, pct=True)
        for n in SMOOTHING_WINDOWS:
            sm = wide.rolling(n, min_periods=1).mean().where(wide.notna()).stack()
            ic = ic_summary(daily_rank_ic(oos[["excess"]].assign(score=sm.reindex(oos.index))), sf.HORIZON)["mean_ic"]
            b = backtest_scores(sm, w, start).summary()
            rows.append({"model": m, "window": n, "mean_ic": ic, "cagr": b["cagr"], "sharpe": b["sharpe"],
                         "max_drawdown": b["max_drawdown"], "turnover_annual": b["turnover_annual"]})
    return rows


# --------------------------------------------------------------------------- tuning

def tune(panel: pd.DataFrame, trials: int) -> tuple[dict, list[dict]]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    pre = panel.loc[date_level(panel) < pd.Timestamp(f"{TUNING_YEARS[-1] + 1}-01-01")]
    inner = yearly_folds(date_level(pre), first_test_year=TUNING_YEARS[0], last_test_year=TUNING_YEARS[-1],
                         horizon=sf.HORIZON, embargo=EMBARGO, min_train_years=2.0)
    history: list[dict] = []

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 7, 63),
            "min_child_samples": trial.suggest_int("min_child_samples", 100, 2000, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "subsample_freq": 1,
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        }
        ics = []
        for f in inner:
            d = date_level(pre)
            train = pre.loc[d <= f.train_end]
            test = pre.loc[(d >= f.test_start) & (d <= f.test_end)]
            model = fit_ranker(train, params)
            scored = test[["excess"]].assign(score=model.predict(test[FEATURES]))
            ics.append(ic_summary(daily_rank_ic(scored), sf.HORIZON)["mean_ic"] or 0.0)
        value = float(np.mean(ics))
        history.append({"trial": trial.number, "mean_ic": value, "params": params})
        return value

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE))
    study.optimize(objective, n_trials=trials)
    best = {**study.best_params, "subsample_freq": 1}
    return best, history


# --------------------------------------------------------------------------- walk-forward

def walk_forward(panel: pd.DataFrame, params: dict) -> tuple[pd.DataFrame, list[dict]]:
    d = date_level(panel)
    test_panel = panel
    all_folds = folds(d)
    outputs, fold_log = [], []
    gap = sf.HORIZON + EMBARGO
    sessions = pd.DatetimeIndex(sorted(d.unique()))
    for f in all_folds:
        with Stage(log, f"fold {f.test_year}"):
            train = panel.loc[d <= f.train_end]
            test = test_panel.loc[(d >= f.test_start) & (d <= f.test_end)]
            if test.empty:
                continue
            ranker = fit_ranker(train, params)
            regressor = fit_regressor(train, params)
            ridge = fit_ridge(train)

            # Conformal split inside the training window: fit on all but the last
            # year (gapped), calibrate on that last year, apply to the test year.
            calib_start = pd.Timestamp(f.train_end) - pd.DateOffset(years=1)
            fit_end = sessions[max(sessions.searchsorted(calib_start) - gap - 1, 0)]
            q_train = train.loc[date_level(train) <= fit_end]
            q_cal = train.loc[date_level(train) >= calib_start]
            qmodels = fit_quantiles(q_train, params)
            cal = predict_quantiles(qmodels, q_cal)
            adj = cqr_adjustment(q_cal["fwd_ret"].to_numpy(), cal["q10"].to_numpy(), cal["q90"].to_numpy(), alpha=0.2)
            qt = predict_quantiles(qmodels, test)
            lo, hi = apply_adjustment(qt["q10"].to_numpy(), qt["q90"].to_numpy(), adj)
            raw_cov = coverage(test["fwd_ret"].to_numpy(), qt["q10"].to_numpy(), qt["q90"].to_numpy())
            qt["q10"], qt["q90"] = lo, hi

            out = pd.DataFrame({
                "lgbm_ranker": ranker.predict(test[FEATURES]),
                "lgbm_regressor": regressor.predict(test[FEATURES]),
                "ridge": predict_ridge(ridge, test),
            }, index=test.index)
            out["ensemble"] = ensemble(out)
            out = out.join(baseline_scores(test)).join(qt)
            out[["excess", "fwd_ret", "rank"]] = test[["excess", "fwd_ret", "rank"]]
            outputs.append(out)
            fold_log.append({
                **f.as_dict(),
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "ic": {m: ic_summary(daily_rank_ic(out.assign(score=out[m])), sf.HORIZON)["mean_ic"]
                       for m in MODELS + BASELINES},
                "conformal_adjustment": adj,
                "interval_coverage_raw": raw_cov,
                "interval_coverage_calibrated": coverage(test["fwd_ret"].to_numpy(), lo, hi),
            })
    return pd.concat(outputs).sort_index(), fold_log


# --------------------------------------------------------------------------- evaluation

def evaluate(oos: pd.DataFrame, w, n_trials: int) -> dict:
    start = date_level(oos).min()
    bench = benchmarks(w, start)
    ew = bench["equal_weight"]
    ew_summary = ew.summary()
    from .swing_common import curve_of, series_summary

    nifty_summary = series_summary(bench["nifty"]) if bench["nifty"] is not None else None
    results: dict = {}
    for name in MODELS + BASELINES:
        frame = oos.assign(score=oos[name])
        signal = signal_report(frame, sf.HORIZON)
        book = backtest_scores(oos[name], w, start)
        summary = book.summary()
        dsr = deflated_sharpe_ratio(book.returns, n_trials=n_trials)
        results[name] = {
            "signal": signal,
            "backtest": summary,
            "excess_cagr_vs_equal_weight": (summary["cagr"] or 0) - (ew_summary["cagr"] or 0),
            "deflated_sharpe": dsr,
            "curve": book.curve(5),
        }
    momentum_ic = results["momentum_12_1"]["signal"]["mean_ic"]
    for name in MODELS:
        results[name]["gate"] = gate(results[name]["signal"], momentum_ic, results[name]["backtest"], ew_summary)
    return {
        "models": results,
        "benchmarks": {
            "equal_weight": {"backtest": ew_summary, "curve": ew.curve(5)},
            "nifty": {"backtest": nifty_summary, "curve": curve_of(bench["nifty"]) if bench["nifty"] is not None else []},
        },
    }


def robustness(oos: pd.DataFrame, w, best: str) -> dict:
    """Does the edge survive the obvious objections?"""
    start = date_level(oos).min()
    out: dict = {}
    # Mature stocks only: ten years of history at the time, so a stock's
    # presence is least likely to reflect its later success.
    history = w.close.notna().cumsum().stack()
    history.index.names = ["date", "symbol"]
    mature = history.reindex(oos.index) >= 2520
    frame = oos.loc[mature.fillna(False).to_numpy()].assign(score=lambda x: x[best])
    out["mature_stocks_only"] = ic_summary(daily_rank_ic(frame), sf.HORIZON)
    # Cost sensitivity: double the slippage assumption.
    from wealthos_core.costs import CostModel
    for label, model in (("double_slippage", CostModel(slippage=0.001)),
                         ("triple_slippage", CostModel(slippage=0.0015))):
        out[label] = backtest_scores(oos[best], w, start, costs=model).summary()
    for n in (5, 20):
        out[f"top_{n}"] = backtest_scores(oos[best], w, start, top_n=n, buffer=n * 2).summary()
    out["rebalance_every_10"] = backtest_scores(oos[best], w, start, rebalance_every=10).summary()
    out["no_buffer"] = backtest_scores(oos[best], w, start, buffer=None).summary()
    return out


# --------------------------------------------------------------------------- final fit

def shap_importance(model, frame: pd.DataFrame) -> dict:
    contrib = model.predict(frame[FEATURES], pred_contrib=True)[:, :-1]
    imp = np.abs(contrib).mean(axis=0)
    order = np.argsort(-imp)
    return {FEATURES[i]: float(imp[i]) for i in order}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="5 tuning trials (smoke run)")
    args = parser.parse_args()
    trials = 5 if args.quick else 30
    silence_accelerate_matmul_warnings()

    panel = load_panel()
    w = load_wide()

    with Stage(log, f"tune on {TUNING_YEARS} ({trials} trials)"):
        params, history = tune(panel, trials)
    log.info("frozen params: %s", params)

    oos, fold_log = walk_forward(panel, params)
    oos.to_parquet(OOS_PATH)

    # Every configuration looked at counts as a trial: the tuning runs, each
    # candidate model, and each smoothing variant.
    n_trials = trials + len(MODELS) + len(MODELS) * len(SMOOTHING_WINDOWS)
    with Stage(log, "evaluate"):
        evaluation = evaluate(oos, w, n_trials)
    models = evaluation["models"]
    best = DEPLOYED
    with Stage(log, "smoothing study"):
        smoothing = smoothing_study(oos, w)
    with Stage(log, "robustness"):
        robust = robustness(oos, w, best)

    # Final models: everything labelled, frozen parameters.
    with Stage(log, "final fit"):
        final_ranker = fit_ranker(panel, params)
        final_regressor = fit_regressor(panel, params)
        final_ridge = fit_ridge(panel)
        d = date_level(panel)
        sessions = pd.DatetimeIndex(sorted(d.unique()))
        calib_start = sessions[-1] - pd.DateOffset(years=1)
        fit_end = sessions[max(sessions.searchsorted(calib_start) - sf.HORIZON - EMBARGO - 1, 0)]
        qmodels = fit_quantiles(panel.loc[d <= fit_end], params)
        cal_frame = panel.loc[d >= calib_start]
        cal = predict_quantiles(qmodels, cal_frame)
        adj = cqr_adjustment(cal_frame["fwd_ret"].to_numpy(), cal["q10"].to_numpy(), cal["q90"].to_numpy(), 0.2)
        recent = panel.loc[d >= sessions[-1] - pd.DateOffset(years=2)]
        importance = shap_importance(final_ranker, recent)

    gate_result = models[DEPLOYED]["gate"]
    oos_card = {k: models[DEPLOYED]["signal"][k] for k in ("mean_ic", "ic_ir", "t_stat", "pct_positive")}
    joblib.dump({
        "model": final_ranker,
        "regressor": final_regressor,
        "ridge": final_ridge,
        "deployed": DEPLOYED,
        "features": FEATURES,
        "feature_version": sf.FEATURE_VERSION,
        "liquid_top": sf.LIQUID_TOP,
        "horizon": sf.HORIZON,
        "params": params,
        "version": MODEL_VERSION,
        "trained_through": str(d.max().date()),
        "recommended": bool(gate_result["recommended"]),
        "oos": {**oos_card, "hit_rate": models[DEPLOYED]["signal"]["hit_rate"],
                "backtest": models[DEPLOYED]["backtest"],
                "equal_weight": evaluation["benchmarks"]["equal_weight"]["backtest"],
                "first_test_year": FIRST_TEST_YEAR},
        "feature_importance": importance,
    }, model_path("swing_ranker.joblib"))
    joblib.dump({
        "models": qmodels,
        "features": FEATURES,
        "quantiles": QUANTILES,
        "conformal_adjustment": adj,
        "nominal_coverage": 0.8,
        "version": MODEL_VERSION,
        "trained_through": str(fit_end.date()),
    }, model_path("swing_quantiles.joblib"))

    coverage_all = coverage(oos["fwd_ret"].to_numpy(), oos["q10"].to_numpy(), oos["q90"].to_numpy())
    write_report("swing_ranker", clean_json({
        "version": MODEL_VERSION,
        "question": "Which eligible stocks will beat the others over the next 10 sessions?",
        "design": {
            "universe": f"Top {sf.LIQUID_TOP} of today's NIFTY 100 by traded value at each date",
            "horizon_sessions": sf.HORIZON,
            "entry": "next session's open", "exit": "close 10 sessions later",
            "tuning": f"Optuna, {trials} trials, inner folds {TUNING_YEARS}; frozen before {FIRST_TEST_YEAR}",
            "walk_forward": f"expanding window, one test year per fold from {FIRST_TEST_YEAR}, "
                            f"purged {sf.HORIZON} sessions plus a {EMBARGO}-session embargo",
            "portfolio": "top 10, equal weight, rebuilt every 5 sessions, held while inside the top 20, "
                         "Indian delivery costs on every trade",
        },
        "params": params,
        "tuning_trials": history,
        "folds": fold_log,
        **evaluation,
        "deployed_model": DEPLOYED,
        "smoothing_study": smoothing,
        "robustness": robust,
        "intervals": {
            "nominal": 0.8,
            "oos_coverage_calibrated": coverage_all,
            "per_fold": [{"year": f["test_year"], "raw": f["interval_coverage_raw"],
                          "calibrated": f["interval_coverage_calibrated"]} for f in fold_log],
            "final_conformal_adjustment": adj,
        },
        "feature_importance_shap": importance,
        "n_trials_charged": n_trials,
        "deployment": gate_result,
    }))
    log.info("ensemble IC %.4f (momentum %.4f); recommended=%s",
             models[DEPLOYED]["signal"]["mean_ic"], models["momentum_12_1"]["signal"]["mean_ic"],
             gate_result["recommended"])


if __name__ == "__main__":
    main()
