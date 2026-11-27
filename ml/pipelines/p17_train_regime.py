"""Stage 17 — market regime from a hidden Markov model, without look-ahead.

Three hidden states fitted on NIFTY's recent return, its realised volatility
and India VIX. States are ordered by volatility and named calm, normal and
stress. The live and backtest probabilities are **filtered** (forward pass
only, ``wealthos_core.regime``); smoothed or Viterbi paths would use the
future and make any regime strategy look prescient.

Evaluation is out of sample on the ranker's yearly folds:

* what each filtered state was followed by (NIFTY's next 10 sessions);
* the deployed swing ensemble's top-10 book with and without a regime
  exposure overlay, and the equal-weight universe with and without it.

The exposure map is fixed before evaluation (calm 100%, normal 80%, stress
30%), not tuned on the test years.

Run:  python -m ml.pipelines.p17_train_regime
"""

from __future__ import annotations

import argparse
import warnings

import joblib
import numpy as np
import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.backtest_xs import rank_portfolio_backtest
from wealthos_core.regime import filtered_probabilities

from .common import PipelineError, Stage, get_logger, silence_accelerate_matmul_warnings, write_report
from .swing_common import (MODEL_VERSION, OOS_PATH, RANDOM_STATE, REGIME_OOS_PATH, backtest_scores, clean_json,
                           curve_of, folds, load_wide, model_path, series_summary)

log = get_logger("regime")

STATE_NAMES = ("calm", "normal", "stress")
EXPOSURE = {"calm": 1.0, "normal": 0.8, "stress": 0.3}
OBS = ["ret_10", "log_rv_20", "log_vix"]


def observations(w: sf.Wide) -> pd.DataFrame:
    if w.index_close is None:
        raise PipelineError("NIFTY history is required for the regime model")
    idx = w.index_close
    lr = np.log(idx).diff()
    obs = pd.DataFrame({
        "ret_10": (np.log(idx) - np.log(idx.shift(10))) * 100.0,
        "log_rv_20": np.log(lr.rolling(20, min_periods=15).std() * np.sqrt(252)),
        "log_vix": np.log(w.vix_close) if w.vix_close is not None else np.nan,
    })
    return obs.dropna()


def fit_hmm(x: np.ndarray):
    from hmmlearn.hmm import GaussianHMM

    best, best_score = None, -np.inf
    # A few restarts: EM finds local optima.
    for seed in range(4):
        m = GaussianHMM(n_components=3, covariance_type="full", n_iter=300, tol=1e-4,
                        random_state=RANDOM_STATE + seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(x)
        score = m.score(x)
        if score > best_score:
            best, best_score = m, score
    return best


def ordered_params(model, scaler_mean: np.ndarray, scaler_std: np.ndarray) -> dict:
    """Parameters with states sorted by volatility (column 1 = log realised vol)."""
    order = np.argsort(model.means_[:, 1])
    return {
        "startprob": model.startprob_[order],
        "transmat": model.transmat_[np.ix_(order, order)],
        "means": model.means_[order],
        "covars": model.covars_[order],
        "scaler_mean": scaler_mean,
        "scaler_std": scaler_std,
        "state_names": list(STATE_NAMES),
        "observations": OBS,
    }


def filtered(params: dict, obs: pd.DataFrame) -> pd.DataFrame:
    x = (obs[OBS].to_numpy() - params["scaler_mean"]) / params["scaler_std"]
    p = filtered_probabilities(x, params["startprob"], params["transmat"], params["means"], params["covars"])
    return pd.DataFrame(p, index=obs.index, columns=list(STATE_NAMES))


def exposure_from(probs: pd.DataFrame, mapping: dict = EXPOSURE) -> pd.Series:
    return sum(probs[name] * mapping[name] for name in STATE_NAMES)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    silence_accelerate_matmul_warnings()
    w = load_wide()
    obs = observations(w)

    oos_parts, fold_log = [], []
    for f in folds(obs.index):
        with Stage(log, f"fold {f.test_year}"):
            train = obs.loc[obs.index <= f.train_end]
            mu, sd = train.mean().to_numpy(), train.std().to_numpy()
            model = fit_hmm((train.to_numpy() - mu) / sd)
            params = ordered_params(model, mu, sd)
            probs = filtered(params, obs.loc[obs.index <= f.test_end])
            part = probs.loc[(probs.index >= f.test_start) & (probs.index <= f.test_end)]
            oos_parts.append(part)
            fold_log.append({**f.as_dict(), "state_vol": np.exp(params["means"][:, 1] * sd[1] + mu[1]).tolist()})
    probs = pd.concat(oos_parts)
    probs = probs[~probs.index.duplicated(keep="last")]
    state = probs.idxmax(axis=1)
    exposure = exposure_from(probs)
    pd.DataFrame({**{c: probs[c] for c in probs}, "state": state, "exposure": exposure}).to_parquet(REGIME_OOS_PATH)

    # What followed each filtered state? NIFTY over the next 10 sessions.
    idx = w.index_close
    fwd = (idx.shift(-sf.HORIZON) / idx - 1.0).reindex(probs.index)
    fwd_vol = np.log(idx).diff().rolling(sf.HORIZON).std().shift(-sf.HORIZON).reindex(probs.index) * np.sqrt(252)
    following = {}
    for name in STATE_NAMES:
        m = state == name
        following[name] = {
            "share_of_days": float(m.mean()),
            "nifty_next_10d_mean_return": float(fwd[m].mean()),
            "nifty_next_10d_negative_share": float((fwd[m] < 0).mean()),
            "nifty_next_10d_realised_vol": float(fwd_vol[m].mean()),
        }
    # Average spell length in each state.
    spells = (state != state.shift()).cumsum()
    lengths = state.groupby(spells).agg(["first", "size"])
    for name in STATE_NAMES:
        following[name]["avg_spell_sessions"] = float(lengths.loc[lengths["first"] == name, "size"].mean())

    # Overlay tests.
    start = probs.index.min()
    overlay: dict = {}
    if OOS_PATH.exists():
        oos = pd.read_parquet(OOS_PATH)
        plain = backtest_scores(oos["ensemble"], w, start)
        gated = backtest_scores(oos["ensemble"], w, start, exposure=exposure)
        overlay["ensemble_top10"] = {"ungated": plain.summary(), "gated": gated.summary(),
                                     "curves": {"ungated": plain.curve(5), "gated": gated.curve(5)}}
    elig = sf.eligibility(w)
    ew_scores = elig.astype(float).where(elig)
    ew_plain = rank_portfolio_backtest(ew_scores, w.open, w.close, top_n=None, buffer=None, start=start)
    ew_gated = rank_portfolio_backtest(ew_scores, w.open, w.close, top_n=None, buffer=None, start=start,
                                       exposure=exposure)
    overlay["equal_weight"] = {"ungated": ew_plain.summary(), "gated": ew_gated.summary()}
    nifty_r = idx.pct_change().reindex(probs.index).fillna(0.0)
    # NIFTY with the overlay: yesterday's exposure times today's return.
    gated_nifty = nifty_r * exposure.shift(1).fillna(1.0)
    overlay["nifty"] = {"ungated": series_summary(nifty_r), "gated": series_summary(gated_nifty)}

    with Stage(log, "final fit"):
        mu, sd = obs.mean().to_numpy(), obs.std().to_numpy()
        model = fit_hmm((obs.to_numpy() - mu) / sd)
        params = ordered_params(model, mu, sd)
        live = filtered(params, obs)
    joblib.dump({**{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in params.items()},
                 "exposure": EXPOSURE, "version": MODEL_VERSION,
                 "trained_through": str(obs.index.max().date())}, model_path("swing_regime.joblib"))

    weekly = probs.iloc[::5]
    write_report("swing_regime", clean_json({
        "version": MODEL_VERSION,
        "question": "Is the market calm, normal or stressed right now, using only data up to today?",
        "observations": {"ret_10": "NIFTY 10-session log return (%)", "log_rv_20": "log of NIFTY 20-day realised vol",
                         "log_vix": "log of India VIX"},
        "inference": "filtered (forward pass only); refitted each year on data before the test year",
        "exposure_map": EXPOSURE,
        "what_followed_each_state": following,
        "overlay": overlay,
        "timeline": [{"date": str(d.date()), **{k: round(float(r[k]), 4) for k in STATE_NAMES},
                      "nifty": round(float(idx.loc[d]), 2)} for d, r in weekly.iterrows()],
        "current": {"date": str(live.index[-1].date()), **{k: float(live.iloc[-1][k]) for k in STATE_NAMES},
                    "state": str(live.iloc[-1].idxmax()), "exposure": float(exposure_from(live.iloc[[-1]]).iloc[0])},
        "folds": fold_log,
        "nifty_curve": {"ungated": curve_of(nifty_r), "gated": curve_of(gated_nifty)},
    }))
    log.info("regime overlay: %s", {k: (v["ungated"].get("max_drawdown"), v["gated"].get("max_drawdown"))
                                     for k, v in overlay.items() if "ungated" in v})


if __name__ == "__main__":
    main()
