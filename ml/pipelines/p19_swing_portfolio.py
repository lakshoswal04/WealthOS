"""Stage 19 — from scores to a portfolio a risk profile can hold, and the model card.

Combines the three models out of sample, exactly as the live advisor does:

1. **Selection**: the swing ensemble's top names (stage 15).
2. **Sizing**: inverse forecast volatility (stage 16), or HRP for comparison,
   capped per stock, then scaled so the basket's forecast volatility meets
   the profile's target.
3. **Exposure**: the regime's filtered probabilities (stage 17) scale the
   whole basket, down to the profile's floor in stress.

Each profile (conservative, moderate, aggressive; ``wealthos_core.allocation``)
is backtested from 2013 with costs, against the equal-weight universe and
NIFTY. The stage then writes ``swing_model_card``: the headline numbers from
every swing report and a plain-language verdict generated from them.

Run:  python -m ml.pipelines.p19_swing_portfolio
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from wealthos_core import swing_features as sf
from wealthos_core.allocation import PROFILES, RiskProfile, regime_exposure, size_basket

from .common import REPORT_DIR, PipelineError, Stage, get_logger, silence_accelerate_matmul_warnings, write_report
from .swing_common import (OOS_PATH, REGIME_OOS_PATH, VOL_OOS_PATH, backtest_scores, benchmarks, clean_json,
                           curve_of, load_wide, series_summary)

log = get_logger("swing-portfolio")

CORR_WINDOW = 126


def profile_exposure(regime: pd.DataFrame, p: RiskProfile) -> pd.Series:
    return regime_exposure(regime, p)


def make_weight_fn(w: sf.Wide, vol_wide: pd.DataFrame, p: RiskProfile, method: str):
    """The live advisor's sizing (``allocation.size_basket``), applied on each rebalance."""
    returns = np.log(w.close.ffill(limit=5)).diff()

    def fn(date: pd.Timestamp, chosen: list[str]) -> pd.Series:
        window = returns.loc[:date].iloc[-CORR_WINDOW:][chosen]
        vols = vol_wide.loc[date].reindex(chosen) if date in vol_wide.index else pd.Series(np.nan, index=chosen)
        weights, _, _ = size_basket(vols, window, p, method)
        return weights

    return fn


def headline(name: str) -> dict:
    path = REPORT_DIR / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def model_card(profiles: dict, bench: dict) -> dict:
    ranker = headline("swing_ranker")
    vol = headline("swing_volatility")
    regime = headline("swing_regime")
    deep = headline("swing_deep")
    feats = headline("swing_features")
    ens = (ranker.get("models") or {}).get("ensemble", {})
    sig = ens.get("signal", {})
    book = ens.get("backtest", {})
    ew = bench["equal_weight"]
    mom = (ranker.get("models") or {}).get("momentum_12_1", {})
    deep_verdict = deep.get("verdict", {})
    any_deep_beats = any(v.get("beats_lgbm_ensemble_ic") for k, v in deep_verdict.items() if k != "blend_lgbm_plus_best_deep")
    reg = (regime.get("overlay") or {}).get("ensemble_top10", {})

    lines = []
    if sig.get("mean_ic") is not None:
        lines.append(
            f"The deployed swing ensemble ranked stocks with a mean daily rank IC of {sig['mean_ic']:.3f} "
            f"(t = {sig.get('t_stat', 0):.1f} after correcting for overlapping labels) across "
            f"{len(sig.get('ic_by_year', {}))} out-of-sample years; plain 12-1 momentum managed "
            f"{(mom.get('signal') or {}).get('mean_ic', 0):.3f}.")
        neg = [y for y, v in (sig.get("ic_by_year") or {}).items() if v is not None and v < 0]
        if neg:
            lines.append(f"The edge was not steady: IC was negative in {', '.join(neg)}.")
    if book.get("cagr") is not None:
        lines.append(
            f"As a top-10 book rebuilt weekly with Indian delivery costs it returned {book['cagr'] * 100:.1f}% a year "
            f"against {ew['cagr'] * 100:.1f}% for an equal-weight portfolio of the same universe, with a worst "
            f"drawdown of {book['max_drawdown'] * 100:.0f}% against {ew['max_drawdown'] * 100:.0f}%. "
            f"Costs took about {book.get('costs_annual', 0) * 100:.1f}% a year.")
    study = feats.get("survivorship_study") or []
    if study:
        allrow, chosen = study[0], next((r for r in study if r.get("chosen")), study[0])
        lines.append(
            f"Absolute returns are flattered by survivorship: an equal-weight portfolio of today's NIFTY 100 "
            f"shows {allrow['equal_weight_cagr'] * 100:.0f}% a year; restricting each date to the stocks that were "
            f"most liquid at the time brings it to {chosen['equal_weight_cagr'] * 100:.0f}%, still above NIFTY's "
            f"{(feats.get('nifty_price_index_since_first_test_year') or {}).get('cagr', 0) * 100:.0f}% (a price index, "
            f"without dividends). Judge the models by their margin over equal-weight, not their absolute return.")
    if vol.get("improvement_vs_naive_qlike") is not None:
        lines.append(
            f"Volatility is far more forecastable than return: the best volatility model ({vol.get('best_by_qlike')}) "
            f"cut forecast loss by {vol['improvement_vs_naive_qlike'] * 100:.0f}% against trailing one-month volatility.")
    if reg.get("gated") and reg.get("ungated"):
        lines.append(
            f"The regime overlay changed the top-10 book's worst drawdown from "
            f"{reg['ungated']['max_drawdown'] * 100:.0f}% to {reg['gated']['max_drawdown'] * 100:.0f}% and its return "
            f"from {reg['ungated']['cagr'] * 100:.1f}% to {reg['gated']['cagr'] * 100:.1f}% a year.")
    if deep_verdict:
        best = deep.get("best_deep_model")
        bm = (deep.get("models") or {}).get(best, {})
        blend = (deep.get("models") or {}).get("blend_lgbm_plus_best_deep", {})
        if best and bm:
            verb = "beat" if any_deep_beats else "did not beat"
            lines.append(
                f"Of the deep networks (LSTM, GRU, temporal CNN, transformer), the best was {best.upper()} with an IC of "
                f"{bm['signal']['mean_ic']:.3f}, which {verb} the LightGBM ensemble's {sig.get('mean_ic', 0):.3f}; as a "
                f"top-10 book it returned {bm['backtest']['cagr'] * 100:.1f}% a year (Sharpe {bm['backtest']['sharpe']:.2f}) "
                f"against the ensemble's {book.get('cagr', 0) * 100:.1f}% (Sharpe {book.get('sharpe', 0):.2f}).")
            if blend:
                lines.append(
                    f"Blending the two lifted the IC to {blend['signal']['mean_ic']:.3f} but returned "
                    f"{blend['backtest']['cagr'] * 100:.1f}% a year, so the LightGBM ensemble stays the deployed signal: "
                    "a better ranking statistic did not become a better portfolio after costs.")
    lines.append("These are research signals for paper trading. They are not investment advice, and past "
                 "out-of-sample results do not promise future returns.")

    return {
        "deployed_signal": "swing ensemble (LightGBM LambdaRank + LightGBM regression + ridge)",
        "recommended": (ranker.get("deployment") or {}).get("recommended"),
        "gate_checks": (ranker.get("deployment") or {}).get("checks"),
        "signal": {k: sig.get(k) for k in ("mean_ic", "ic_ir", "t_stat", "pct_positive")},
        "hit_rate": sig.get("hit_rate"),
        "backtest": book,
        "equal_weight": ew,
        "nifty": bench.get("nifty"),
        "profiles": {k: v["backtest"] for k, v in profiles.items()},
        "volatility": {"best": vol.get("best_by_qlike"), "serving": vol.get("serving_model"),
                       "improvement_vs_naive_qlike": vol.get("improvement_vs_naive_qlike")},
        "regime_current": regime.get("current"),
        "deep_learning": deep_verdict,
        "verdict": " ".join(lines),
    }


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    silence_accelerate_matmul_warnings()
    for path in (OOS_PATH, VOL_OOS_PATH, REGIME_OOS_PATH):
        if not path.exists():
            raise PipelineError(f"{path.name} missing; run stages 15-17 first")
    w = load_wide()
    oos = pd.read_parquet(OOS_PATH)
    vol = pd.read_parquet(VOL_OOS_PATH)
    regime = pd.read_parquet(REGIME_OOS_PATH)
    # Size with the volatility model the live advisor serves.
    serving = headline("swing_volatility").get("serving_model", "har")
    vol_col = serving if serving in vol else "har"
    vol_wide = vol[vol_col].unstack("symbol")
    start = max(oos.index.get_level_values("date").min(), regime.index.min())

    bench_raw = benchmarks(w, start)
    ew = bench_raw["equal_weight"]
    bench = {"equal_weight": ew.summary(),
             "nifty": series_summary(bench_raw["nifty"]) if bench_raw["nifty"] is not None else None}
    plain = backtest_scores(oos["ensemble"], w, start)

    profiles: dict = {}
    for name, p in PROFILES.items():
        with Stage(log, f"profile {name}"):
            exposure = profile_exposure(regime, p)
            book = backtest_scores(oos["ensemble"], w, start, top_n=p.max_names, buffer=p.max_names * 2,
                                   max_weight=p.max_weight, exposure=exposure,
                                   weight_fn=make_weight_fn(w, vol_wide, p, "inverse_vol"))
            profiles[name] = {"profile": p.as_dict(), "backtest": book.summary(), "curve": book.curve(5)}
    with Stage(log, "HRP comparison (moderate)"):
        p = PROFILES["moderate"]
        hrp = backtest_scores(oos["ensemble"], w, start, top_n=p.max_names, buffer=p.max_names * 2,
                              max_weight=p.max_weight, exposure=profile_exposure(regime, p),
                              weight_fn=make_weight_fn(w, vol_wide, p, "hrp"))

    write_report("swing_portfolio", clean_json({
        "question": "What does each risk profile's swing basket look like over time, after costs?",
        "construction": {
            "selection": "swing ensemble top names, kept while inside twice the basket size",
            "sizing": "inverse 10-session forecast volatility, capped per stock, scaled to the profile's volatility target",
            "exposure": "regime filtered probabilities: calm 100%, normal 80%, stress at the profile's floor",
            "rebalance": "every 5 sessions at the next open, Indian delivery costs",
        },
        "start": str(pd.Timestamp(start).date()),
        "profiles": profiles,
        "hrp_moderate": {"backtest": hrp.summary(), "curve": hrp.curve(5)},
        "plain_top10_ensemble": {"backtest": plain.summary(), "curve": plain.curve(5)},
        "benchmarks": {**bench, "equal_weight_curve": ew.curve(5),
                       "nifty_curve": curve_of(bench_raw["nifty"]) if bench_raw["nifty"] is not None else []},
    }))
    write_report("swing_model_card", clean_json(model_card(profiles, bench)))
    log.info("profiles: %s", {k: (round(v["backtest"]["cagr"], 3), round(v["backtest"]["max_drawdown"], 3))
                              for k, v in profiles.items()})


if __name__ == "__main__":
    main()
