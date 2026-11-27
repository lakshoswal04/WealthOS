"""Forward-test leaderboard for the swing models.

Every model's scores for each new session are recorded once
(``ForwardScore``) and replayed into the same top-10, weekly, cost-paying
book the backtests use. The test starts the first time it runs and only ever
grows. A model retrained later does not rewrite what its predecessor said.

There is no scheduler: ``catch_up`` runs at API start-up and on each
leaderboard request, recording any sessions not yet stored. A session
recorded late (the server was off) is marked as such; its scores still use
only data up to that session, so it remains a fair test.
"""

from __future__ import annotations

import logging
import threading
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ml_runtime.registry import registry
from app.models.forward import ForwardScore
from app.services import signals_service as signals
from wealthos_core import swing_features as sf
from wealthos_core.backtest_xs import rank_portfolio_backtest
from wealthos_core.metrics import performance_summary

log = logging.getLogger("wealthos.forward")

DEEP = ("lstm", "gru", "tcn", "transformer")
LABELS = {
    "ensemble": "Swing ensemble (deployed)",
    "lgbm_ranker": "LightGBM LambdaRank",
    "lstm": "LSTM", "gru": "GRU", "tcn": "Temporal CNN", "transformer": "Transformer",
    "momentum_12_1": "12-1 momentum (baseline)",
}
TOP_N, REBALANCE_EVERY, BUFFER = 10, 5, 20

_lock = threading.Lock()


def _version(model_id: str) -> str:
    ranker = registry.swing_ranker() or {}
    if model_id in DEEP:
        deep = registry.swing_deep(model_id) or {}
        return str(deep.get("version", "?"))
    if model_id == "momentum_12_1":
        return sf.FEATURE_VERSION
    return str(ranker.get("version", "?"))


def _scores_for(snap: signals.Snapshot, dates: list[pd.Timestamp]) -> dict[str, dict[pd.Timestamp, dict]]:
    ranker = registry.swing_ranker()
    feats = snap.features
    rows = feats.loc[feats.index.get_level_values("date").isin(dates)]
    out: dict[str, dict[pd.Timestamp, dict]] = {}
    if rows.empty:
        return out

    def collect(series: pd.Series) -> dict[pd.Timestamp, dict]:
        res = {}
        for d, g in series.groupby(level="date"):
            res[pd.Timestamp(d)] = {sym: round(float(v), 6) for (_, sym), v in g.items() if np.isfinite(v)}
        return res

    if ranker is not None:
        scores = signals.model_scores(ranker, rows)
        out["ensemble"] = collect(scores["ensemble"])
        out["lgbm_ranker"] = collect(scores["lgbm_ranker"])
    out["momentum_12_1"] = collect(rows["f_mom_12_1"])
    from ml.pipelines.deep_models import score_dates

    for name in DEEP:
        bundle = registry.swing_deep(name)
        if bundle is None:
            continue
        try:
            s = score_dates(bundle["model"], feats, bundle["features"], len(sf.STOCK_FEATURES),
                            bundle["market_mean"], bundle["market_std"], bundle["seq_len"],
                            at=pd.DatetimeIndex(dates))
            out[name] = collect(s)
        except Exception as exc:  # noqa: BLE001 - one broken network must not stop the others
            log.warning("forward scores for %s failed: %s", name, exc)
    return out


def catch_up(db: Session) -> dict:
    """Record scores for every session since the test began that is not stored yet."""
    with _lock:
        snap = signals.snapshot()
        all_dates = pd.DatetimeIndex(sorted(snap.features.index.get_level_values("date").unique()))
        existing = db.execute(select(ForwardScore.model_id, ForwardScore.signal_date)).all()
        recorded: dict[str, set[date]] = {}
        for model_id, d in existing:
            recorded.setdefault(model_id, set()).add(d)
        started = min((d for ds in recorded.values() for d in ds), default=snap.as_of.date())
        pending = [d for d in all_dates if d.date() >= started]
        # Per model: a network loaded after the test began still joins it, scored
        # with data up to each date only.
        available = ["ensemble", "lgbm_ranker", "momentum_12_1"] + [n for n in DEEP if registry.swing_deep(n)]
        missing = sorted({d for d in pending if any(d.date() not in recorded.get(m, set()) for m in available)})
        if not missing:
            return {"started_on": str(started), "recorded": 0}
        scores = _scores_for(snap, missing)
        added = 0
        for model_id, by_date in scores.items():
            have = recorded.get(model_id, set())
            for d, payload in by_date.items():
                if d.date() in have or not payload:
                    continue
                db.add(ForwardScore(model_id=model_id, signal_date=d.date(), model_version=_version(model_id),
                                    scores=payload))
                added += 1
        try:
            db.commit()
        except IntegrityError:
            db.rollback()          # another request recorded the same sessions first
        return {"started_on": str(started), "recorded": added}


def leaderboard(db: Session) -> dict:
    try:
        catch_up(db)
    except signals.SignalsUnavailable:
        raise
    snap = signals.snapshot()
    rows = db.execute(select(ForwardScore)).scalars().all()
    if not rows:
        return {"started_on": None, "sessions": 0, "models": [], "note": "The forward test has not started yet."}
    started = min(r.signal_date for r in rows)
    w = snap.wide
    calendar = w.close.index
    by_model: dict[str, dict] = {}
    for r in rows:
        by_model.setdefault(r.model_id, {})[pd.Timestamp(r.signal_date)] = r.scores
    latest_versions = {r.model_id: r.model_version for r in sorted(rows, key=lambda x: x.signal_date)}

    start = pd.Timestamp(started)
    sessions_after = int((calendar > start).sum())
    out = []
    for model_id, per_date in by_model.items():
        wide = pd.DataFrame.from_dict(per_date, orient="index").reindex(index=calendar, columns=w.close.columns)
        book = rank_portfolio_backtest(wide, w.open, w.close, top_n=TOP_N, rebalance_every=REBALANCE_EVERY,
                                       buffer=BUFFER, start=start)
        summary = _forward_summary(book.returns)
        out.append({
            "model_id": model_id, "label": LABELS.get(model_id, model_id),
            "version": latest_versions.get(model_id), "signal_days": len(per_date),
            **summary, "curve": book.curve(1),
            "holdings": sorted(((s, round(v, 4)) for s, v in book.final_holdings.items()), key=lambda x: -x[1]),
        })
    eligible = sf.eligibility(w)
    ew = rank_portfolio_backtest(eligible.astype(float).where(eligible), w.open, w.close, top_n=None,
                                 rebalance_every=REBALANCE_EVERY, buffer=None, start=start)
    benchmarks = [{"model_id": "equal_weight", "label": "Equal-weight universe", **_forward_summary(ew.returns),
                   "curve": ew.curve(1)}]
    if w.index_close is not None:
        nifty = w.index_close.loc[start:].pct_change().dropna()
        eq = (1 + nifty).cumprod()
        benchmarks.append({"model_id": "nifty", "label": "NIFTY 50 (price)", **_forward_summary(nifty),
                           "curve": [{"date": str(d.date()), "value": round(float(v), 5)} for d, v in eq.items()]})
    out.sort(key=lambda m: -(m.get("total_return") or -1e9))
    return {
        "started_on": str(started),
        "sessions": sessions_after,
        "rules": "Top 10 by each model's score, equal weight, rebuilt every 5 sessions at the next open, "
                 "kept while in the top 20, Indian delivery costs.",
        "models": out,
        "benchmarks": benchmarks,
        "note": ("A forward test needs months before its numbers mean much. Early results are mostly noise."
                 if sessions_after < 60 else None),
        "disclaimer": signals.DISCLAIMER,
    }


def _forward_summary(r: pd.Series) -> dict:
    if r is None or len(r) == 0:
        return {"total_return": None, "sessions": 0, "max_drawdown": None, "volatility": None}
    s = performance_summary(r, risk_free_rate=0.0)
    return {
        "total_return": float(s["total_return"]),
        "sessions": int(len(r)),
        "max_drawdown": float(s["max_drawdown"]),
        "volatility": None if len(r) < 20 else float(s["annualized_volatility"]),
    }
