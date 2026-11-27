"""Stage 18 — deep learning against the LightGBM ensemble, on identical folds.

LSTM, GRU, a temporal convolutional network and a PatchTST-style transformer
each read 60 sessions of a stock's ranked features and score it. They face
the same test years, the same purge and embargo, the same metrics and the
same cost-paying top-10 backtest as stage 15, so the comparison is fair.

To fit a laptop's compute budget each network is retrained every two test
years instead of every year. That only ever makes it *older* than the
LightGBM model it is compared with, never newer, so the comparison cannot
favour it. Early stopping uses the last year of each training window
(gapped), never the test year.

Finally the best network is blended with the LightGBM ensemble (mean of
daily ranks) to see whether it adds anything the trees miss.

Optional: Chronos-Bolt (a pre-trained time-series foundation model) as a
zero-shot baseline, if ``chronos-forecasting`` is installed.

Run:  python -m ml.pipelines.p18_train_deep [--quick] [--models lstm,gru,tcn,transformer]
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd
import torch

from wealthos_core import swing_features as sf
from wealthos_core.metrics import deflated_sharpe_ratio
from wealthos_core.validation import daily_rank_ic, ic_summary, signal_report

from .common import Stage, get_logger, silence_accelerate_matmul_warnings, write_report
from .deep_models import DEEP_MODELS, build, normalise, tensorise
from .deep_models import windows as _windows
from .swing_common import (EMBARGO, MODEL_VERSION, OOS_PATH, RANDOM_STATE, backtest_scores, benchmarks, clean_json,
                           folds, load_panel, load_wide, model_path)

log = get_logger("deep")

SEQ_LEN = 60
BATCH = 1024
LR = 1e-3
MAX_EPOCHS = 12
PATIENCE = 3
TRAIN_EVERY_NTH_DATE = 2


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class Tensorised:
    """Features as a (dates, symbols, features) tensor, plus sample indices and labels."""

    def __init__(self, panel: pd.DataFrame):
        self.raw, self.dates, self.symbols, self.t, self.s = tensorise(panel, sf.FEATURES)
        self.labels = panel["rank"].to_numpy(np.float32) - 0.5
        self.n_stock = len(sf.STOCK_FEATURES)

    def normalised(self, market_mean: np.ndarray, market_std: np.ndarray) -> np.ndarray:
        return normalise(self.raw, self.n_stock, market_mean, market_std)


def windows(x: torch.Tensor, t_idx: torch.Tensor, s_idx: torch.Tensor) -> torch.Tensor:
    return _windows(x, t_idx, s_idx, SEQ_LEN)


def batch_ic(scores: np.ndarray, labels: np.ndarray, dates: np.ndarray) -> float:
    frame = pd.DataFrame({"score": scores, "excess": labels, "date": dates}).set_index(["date"], append=False)
    frame.index.name = "date"
    return ic_summary(daily_rank_ic(frame), sf.HORIZON)["mean_ic"] or 0.0


def predict(model: torch.nn.Module, x: torch.Tensor, t_idx: np.ndarray, s_idx: np.ndarray) -> np.ndarray:
    model.eval()
    out = []
    dev = x.device
    with torch.no_grad():
        for i in range(0, len(t_idx), 4096):
            tb = torch.as_tensor(t_idx[i:i + 4096], device=dev)
            sb = torch.as_tensor(s_idx[i:i + 4096], device=dev)
            out.append(model(windows(x, tb, sb)).float().cpu().numpy())
    return np.concatenate(out) if out else np.empty(0)


def train_one(name: str, x: torch.Tensor, data: Tensorised, train_mask: np.ndarray, val_mask: np.ndarray,
              max_epochs: int) -> tuple[torch.nn.Module, dict]:
    torch.manual_seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)
    dev = x.device
    model = build(name, x.shape[-1], SEQ_LEN).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = torch.nn.MSELoss()
    tr = np.flatnonzero(train_mask)
    # Thin the training dates: neighbouring days share 9 of 10 label days.
    keep_dates = np.unique(data.t[tr])[::TRAIN_EVERY_NTH_DATE]
    tr = tr[np.isin(data.t[tr], keep_dates)]
    va = np.flatnonzero(val_mask)
    y = torch.as_tensor(data.labels, device=dev)
    best_ic, best_state, bad, history = -np.inf, None, 0, []
    rng = np.random.default_rng(RANDOM_STATE)
    for epoch in range(max_epochs):
        model.train()
        order = rng.permutation(tr)
        total = 0.0
        for i in range(0, len(order), BATCH):
            idx = order[i:i + BATCH]
            tb = torch.as_tensor(data.t[idx], device=dev)
            sb = torch.as_tensor(data.s[idx], device=dev)
            pred = model(windows(x, tb, sb))
            loss = loss_fn(pred, y[idx])
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * len(idx)
        val_scores = predict(model, x, data.t[va], data.s[va])
        ic = batch_ic(val_scores, data.labels[va], data.dates[data.t[va]].to_numpy())
        history.append({"epoch": epoch + 1, "train_loss": total / max(len(order), 1), "val_ic": ic})
        if ic > best_ic:
            best_ic, bad = ic, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {"epochs_run": len(history), "best_val_ic": best_ic, "history": history}


def chronos_baseline() -> dict:
    try:
        import chronos  # noqa: F401
    except ImportError:
        return {"status": "skipped", "reason": "chronos-forecasting is not installed (optional dependency)"}
    return {"status": "skipped", "reason": "installed but not run in this version of the stage"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="3 epochs, last two folds only")
    parser.add_argument("--models", default=",".join(DEEP_MODELS))
    args = parser.parse_args()
    silence_accelerate_matmul_warnings()
    names = [m for m in args.models.split(",") if m]
    max_epochs = 3 if args.quick else MAX_EPOCHS

    panel = load_panel()
    w = load_wide()
    data = Tensorised(panel)
    dates_all = data.dates[data.t]
    dev = device()
    log.info("device %s; tensor %s", dev, data.raw.shape)

    all_folds = folds(dates_all)
    if args.quick:
        all_folds = all_folds[-2:]
    sessions = data.dates
    gap = sf.HORIZON + EMBARGO

    preds = {n: np.full(len(data.t), np.nan, dtype=np.float32) for n in names}
    fold_log: list[dict] = []
    models: dict[str, torch.nn.Module] = {}
    x = None
    for f in all_folds:
        retrain = (f.index % 2 == 0) or not models
        if retrain:
            train_rows = (dates_all <= f.train_end)
            stock_n = data.n_stock
            mkt = data.raw[:, :, stock_n:-1]
            days = sessions <= f.train_end
            day_vals = np.nanmean(mkt[days], axis=1)
            m_mean, m_std = np.nanmean(day_vals, axis=0), np.nanstd(day_vals, axis=0) + 1e-6
            x = torch.as_tensor(data.normalised(m_mean, m_std), device=dev)
            val_start = pd.Timestamp(f.train_end) - pd.DateOffset(years=1)
            fit_end = sessions[max(sessions.searchsorted(val_start) - gap - 1, 0)]
            tr_mask = np.asarray(dates_all <= fit_end)
            va_mask = np.asarray((dates_all >= val_start) & train_rows)
            for n in names:
                with Stage(log, f"train {n} through {f.train_end.date()}"):
                    t0 = time.time()
                    model, info = train_one(n, x, data, tr_mask, va_mask, max_epochs)
                    models[n] = model
                    fold_log.append({"model": n, "trained_through": str(pd.Timestamp(fit_end).date()),
                                     "first_test_year": f.test_year, "seconds": round(time.time() - t0, 1), **info})
        test_mask = np.asarray((dates_all >= f.test_start) & (dates_all <= f.test_end))
        ti = np.flatnonzero(test_mask)
        for n in names:
            preds[n][ti] = predict(models[n], x, data.t[ti], data.s[ti])

    scored = np.isfinite(preds[names[0]])
    oos = panel.loc[scored, ["excess", "fwd_ret", "rank"]].copy()
    for n in names:
        oos[n] = preds[n][scored]
    lgbm_oos = pd.read_parquet(OOS_PATH)
    oos = oos.join(lgbm_oos[["ensemble", "lgbm_ranker"]], how="inner")

    start = oos.index.get_level_values("date").min()
    ew = benchmarks(w, start)["equal_weight"].summary()
    n_trials = len(names) + 1
    results: dict = {}
    for n in names + ["ensemble"]:
        sig = signal_report(oos.assign(score=oos[n]), sf.HORIZON)
        book = backtest_scores(oos[n], w, start)
        results[n] = {"signal": sig, "backtest": book.summary(),
                      "deflated_sharpe": deflated_sharpe_ratio(book.returns, n_trials=n_trials),
                      "curve": book.curve(5)}
    best_deep = max(names, key=lambda n: results[n]["signal"]["mean_ic"] or -1)
    ranks = oos[[best_deep, "ensemble"]].groupby(level="date").rank(pct=True)
    oos["blend"] = ranks.mean(axis=1)
    sig = signal_report(oos.assign(score=oos["blend"]), sf.HORIZON)
    book = backtest_scores(oos["blend"], w, start)
    results["blend_lgbm_plus_best_deep"] = {"signal": sig, "backtest": book.summary(), "curve": book.curve(5),
                                            "deflated_sharpe": deflated_sharpe_ratio(book.returns, n_trials=n_trials)}
    oos[names + ["blend"]].to_parquet(OOS_PATH.with_name("swing_oos_deep.parquet"))

    # Final networks, trained through the latest labels, for serving and the forward test.
    final_meta = {}
    if not args.quick:
        last = sessions[-1]
        mkt = data.raw[:, :, data.n_stock:-1]
        day_vals = np.nanmean(mkt, axis=1)
        m_mean, m_std = np.nanmean(day_vals, axis=0), np.nanstd(day_vals, axis=0) + 1e-6
        x = torch.as_tensor(data.normalised(m_mean, m_std), device=dev)
        val_start = last - pd.DateOffset(years=1)
        fit_end = sessions[max(sessions.searchsorted(val_start) - gap - 1, 0)]
        for n in names:
            with Stage(log, f"final {n}"):
                model, info = train_one(n, x, data, np.asarray(dates_all <= fit_end),
                                        np.asarray(dates_all >= val_start), max_epochs)
                torch.save({"state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
                            "name": n, "n_features": int(x.shape[-1]), "seq_len": SEQ_LEN,
                            "features": sf.FEATURES, "market_mean": m_mean.tolist(), "market_std": m_std.tolist(),
                            "version": MODEL_VERSION, "trained_through": str(pd.Timestamp(fit_end).date()),
                            "oos_mean_ic": results[n]["signal"]["mean_ic"]},
                           model_path(f"swing_{n}.pt"))
                final_meta[n] = {"trained_through": str(pd.Timestamp(fit_end).date()), **{k: info[k] for k in ("epochs_run", "best_val_ic")}}

    lgbm_ic = results["ensemble"]["signal"]["mean_ic"] or 0
    verdict = {n: {"mean_ic": results[n]["signal"]["mean_ic"],
                   "beats_lgbm_ensemble_ic": (results[n]["signal"]["mean_ic"] or -1) > lgbm_ic,
                   "cagr": results[n]["backtest"]["cagr"], "sharpe": results[n]["backtest"]["sharpe"]}
               for n in names + ["blend_lgbm_plus_best_deep"]}
    write_report("swing_deep", clean_json({
        "version": MODEL_VERSION,
        "quick": args.quick,
        "design": {
            "input": f"{SEQ_LEN} sessions of the {len(sf.FEATURES)} ranked features plus an eligibility flag",
            "target": "within-date rank of the 10-session excess return (centred), MSE loss",
            "retraining": "every two test years (never newer than the LightGBM comparison)",
            "early_stopping": "IC on the last year of the training window, gapped; patience 3",
            "training_dates": f"every {TRAIN_EVERY_NTH_DATE}nd date (labels overlap 9 of 10 days)",
            "device": str(dev),
        },
        "models": results,
        "equal_weight": ew,
        "best_deep_model": best_deep,
        "verdict": verdict,
        "training_log": fold_log,
        "final_models": final_meta,
        "chronos": chronos_baseline(),
    }))
    log.info("deep IC: %s; LightGBM ensemble %.4f", {n: round(results[n]["signal"]["mean_ic"] or 0, 4) for n in names}, lgbm_ic)


if __name__ == "__main__":
    main()
