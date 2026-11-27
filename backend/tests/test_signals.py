"""Swing-model signals, the swing plan, the forward test and the copilot tools.

The models here are tiny versions of the real ones, trained in the fixture by
the real pipeline functions on a synthetic 30-stock panel, so every code path
(features, scoring, ranges, volatility, regime, sizing) runs for real. The
synthetic prices are test inputs only; they are never served.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from wealthos_core import swing_features as sf

N_STOCKS = 30
LIQUID = 20


def _synthetic_panel(n_days: int = 700, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-24", periods=n_days)
    rows = []
    for i in range(N_STOCKS):
        r = rng.normal(0.0004, 0.017 + i * 0.0003, n_days)
        close = 200 * np.exp(np.cumsum(r))
        open_ = close * np.exp(rng.normal(0, 0.004, n_days))
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n_days))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n_days))
        volume = rng.integers(200_000, 2_000_000, n_days).astype(float) * (1 + i / 5)
        rows.append(pd.DataFrame({"date": dates, "symbol": f"STK{i:02d}", "open": open_, "high": high,
                                  "low": low, "close": close, "volume": volume}))
    idx = 24000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days)))
    vix = 14 + np.abs(np.cumsum(rng.normal(0, 0.3, n_days))) % 12
    for sym, s in (("NIFTY", idx), ("INDIAVIX", vix)):
        rows.append(pd.DataFrame({"date": dates, "symbol": sym, "open": s, "high": s, "low": s,
                                  "close": s, "volume": 0.0}))
    return pd.concat(rows, ignore_index=True)


UNIVERSE = pd.DataFrame({"symbol": [f"STK{i:02d}" for i in range(N_STOCKS)],
                         "name": [f"Stock {i}" for i in range(N_STOCKS)],
                         "sector": ["Alpha" if i % 3 else "Beta" for i in range(N_STOCKS)]})


@pytest.fixture(scope="module")
def trained():
    """Train small versions of every swing model with the pipeline's own functions."""
    from ml.pipelines import p15_train_ranker as p15
    from ml.pipelines import p16_train_volatility as p16
    from ml.pipelines import p17_train_regime as p17
    from wealthos_core.volatility import HAR

    panel = _synthetic_panel()
    w = sf.to_wide(panel)
    sectors = dict(zip(UNIVERSE["symbol"], UNIVERSE["sector"]))
    feats = sf.build_features(w, sectors, liquid_top=LIQUID)
    data = feats.join(sf.build_targets(w, liquid_top=LIQUID), how="inner").sort_index()
    params = {"n_estimators": 30, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 50,
              "subsample": 1.0, "subsample_freq": 1, "colsample_bytree": 1.0, "reg_lambda": 0.1}
    ranker = {
        "model": p15.fit_ranker(data, params), "regressor": p15.fit_regressor(data, params),
        "ridge": p15.fit_ridge(data), "deployed": "ensemble", "features": sf.FEATURES,
        "feature_version": sf.FEATURE_VERSION, "liquid_top": LIQUID, "horizon": sf.HORIZON,
        "version": "test", "trained_through": "2026-11-10", "recommended": True,
        "oos": {"first_test_year": 2013, "mean_ic": 0.033, "t_stat": 3.7, "hit_rate": {"relative": 0.511},
                "backtest": {"cagr": 0.25, "max_drawdown": -0.33, "sharpe": 1.27},
                "equal_weight": {"cagr": 0.18, "max_drawdown": -0.38}},
    }
    qmodels = p15.fit_quantiles(data, params)
    quantiles = {"models": qmodels, "features": sf.FEATURES, "quantiles": p15.QUANTILES,
                 "conformal_adjustment": 0.01, "version": "test"}
    vp = p16.build_panel(w)
    ok = vp["target"].notna()
    har = HAR().fit(vp.loc[ok], vp.loc[ok, "target"])
    vol = {"har_coef": har.coef_.tolist(), "har_resid_var": har.resid_var_, "serving_model": "har",
           "lgbm": None, "version": "test"}
    obs = p17.observations(w)
    mu, sd = obs.mean().to_numpy(), obs.std().to_numpy()
    hmm = p17.fit_hmm((obs.to_numpy() - mu) / sd)
    regime = {**{k: (v.tolist() if isinstance(v, np.ndarray) else v)
                 for k, v in p17.ordered_params(hmm, mu, sd).items()},
              "exposure": p17.EXPOSURE, "trained_through": "2026-11-24"}
    return {"panel": panel, "ranker": ranker, "quantiles": quantiles, "vol": vol, "regime": regime}


def _write(panel: pd.DataFrame, path) -> None:
    panel.to_parquet(path, index=False)


@pytest.fixture
def swing(monkeypatch, tmp_path, trained):
    """Point the live store at the synthetic panel and the registry at the tiny models."""
    from app.ml_runtime.registry import registry
    from app.services import live_market_service as live
    from app.services import signals_service

    path = tmp_path / "universe_daily.parquet"
    _write(trained["panel"], path)
    frozen = datetime(2026, 11, 25, 11, 0, tzinfo=live.IST)
    monkeypatch.setattr(live, "now_ist", lambda: frozen)
    monkeypatch.setattr(live, "_daily_path", lambda: path)
    monkeypatch.setattr(live.daily_store, "_frame", None)
    monkeypatch.setattr(live.daily_store, "_mtime", None)
    monkeypatch.setattr(live, "universe", lambda: UNIVERSE)
    monkeypatch.setattr(registry, "swing_ranker", lambda: trained["ranker"])
    monkeypatch.setattr(registry, "swing_quantiles", lambda: trained["quantiles"])
    monkeypatch.setattr(registry, "swing_vol", lambda: trained["vol"])
    monkeypatch.setattr(registry, "swing_regime", lambda: trained["regime"])
    monkeypatch.setattr(registry, "swing_deep", lambda name: None)

    close = trained["panel"].pivot(index="date", columns="symbol", values="close")

    class Prices:
        """Delayed quotes at the synthetic panel's last close."""

        name = "delayed"

        def fetch_quotes(self, symbols):
            out = {}
            for s in symbols:
                if s in close:
                    c = close[s].dropna()
                    out[s] = live.make_quote(s, float(c.iloc[-1]), float(c.iloc[-2]), float(c.iloc[-2]),
                                             float(c.iloc[-1]), float(c.iloc[-1]), 1e5, "delayed", frozen)
            return out

        def fetch_candles(self, *args):
            return None

    monkeypatch.setattr(live, "provider", Prices())
    live.reset_caches()
    signals_service.clear_cache()
    yield {"path": path, **trained}
    signals_service.clear_cache()
    live.reset_caches()


# ---------------------------------------------------------------- signals

def test_signals_rank_the_liquid_universe_with_ranges_and_reasons(client, auth, swing):
    r = client.get("/api/v1/signals?limit=5", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == "2026-11-24"
    assert body["universe_size"] == LIQUID
    assert [p["rank"] for p in body["picks"]] == [1, 2, 3, 4, 5]
    scores = [p["score"] for p in body["picks"]]
    assert scores == sorted(scores, reverse=True)
    top = body["picks"][0]
    assert top["range_10d"]["low"] < top["range_10d"]["mid"] < top["range_10d"]["high"]
    assert top["vol_annual"] > 0 and top["stop"] < top["last_close"] < top["target"]
    assert len(top["drivers"]) == 3 and all(d["label"] for d in top["drivers"])
    assert set(top["models"]) == {"lgbm_ranker", "lgbm_regressor", "ridge", "ensemble"}
    assert body["regime"]["state"] in {"calm", "normal", "stress"}
    assert "not investment advice" in body["disclaimer"].lower()
    assert body["model"]["oos"]["mean_ic"] == pytest.approx(0.033)


def test_signal_for_one_stock_and_ineligible_reasons(client, auth, swing):
    top = client.get("/api/v1/signals?limit=1", headers=auth).json()["picks"][0]["symbol"]
    one = client.get(f"/api/v1/signals/{top}", headers=auth).json()
    assert one["eligible"] and one["rank"] == 1
    unknown = client.get("/api/v1/signals/NOTREAL", headers=auth).json()
    assert unknown["eligible"] is False and "NIFTY 100" in unknown["reason"]


def test_signals_say_why_when_models_are_missing(client, auth, swing, monkeypatch):
    from app.ml_runtime.registry import registry

    monkeypatch.setattr(registry, "swing_ranker", lambda: None)
    r = client.get("/api/v1/signals", headers=auth)
    assert r.status_code == 503
    assert r.json()["code"] == "models_unavailable"
    assert "make swing" in r.json()["detail"]


def test_partial_bar_is_ignored_during_the_session(client, auth, swing):
    """A bar for 'today' (still forming at 11:00) must not be scored."""
    panel = swing["panel"]
    today = panel.loc[panel["date"] == panel["date"].max()].copy()
    today["date"] = pd.Timestamp("2026-11-25")
    _write(pd.concat([panel, today]), swing["path"])
    body = client.get("/api/v1/signals?limit=1", headers=auth).json()
    assert body["as_of"] == "2026-11-24"


def test_a_bar_saved_mid_session_is_not_scored(client, auth, swing):
    """A file downloaded during a session holds that day's bar as it was then: partial."""
    import os

    from app.services import live_market_service as live

    written = datetime(2026, 11, 24, 13, 0, tzinfo=live.IST).timestamp()   # before the 24th's close
    os.utime(swing["path"], (written, written))
    body = client.get("/api/v1/signals?limit=1", headers=auth).json()
    assert body["as_of"] == "2026-11-23"


def test_signals_require_auth(client, swing):
    assert client.get("/api/v1/signals").status_code == 401


# ---------------------------------------------------------------- swing plan

def _set_risk(db, email: str, level: str) -> None:
    from app.models.enums import RiskTolerance
    from app.models.user import User

    user = db.query(User).filter(User.email == email).one()
    user.risk_tolerance = RiskTolerance(level)
    db.commit()


@pytest.mark.parametrize("level", ["conservative", "moderate", "aggressive"])
def test_swing_plan_respects_the_risk_profile(client, auth, swing, db, level):
    from wealthos_core.allocation import PROFILES

    _set_risk(db, "investor@example.com", level)
    profile = PROFILES[level]
    r = client.post("/api/v1/advisor/swing-plan", json={"amount": 500_000}, headers=auth)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["profile"]["name"] == level
    assert len(plan["positions"]) <= profile.max_names
    assert plan["exposure"] <= profile.max_exposure + 1e-9
    assert all(p["weight"] <= profile.max_weight + 1e-6 for p in plan["positions"])
    assert plan["invested"] <= 500_000 * plan["exposure"] + 1
    assert plan["invested"] + plan["cash_reserve"] == pytest.approx(500_000, abs=0.05)
    for p in plan["positions"]:
        assert p["cost"] == pytest.approx(p["quantity"] * p["price"], abs=0.05)
        assert p["stop"] < p["price"] < p["target"]
    assert any("regime" in n for n in plan["notes"])


def test_swing_plan_rejects_small_or_unaffordable_amounts(client, auth, swing):
    small = client.post("/api/v1/advisor/swing-plan", json={"amount": 5_000}, headers=auth)
    assert small.status_code == 422 and "10,000" in small.json()["detail"]
    huge = client.post("/api/v1/advisor/swing-plan", json={"amount": 50_000_000}, headers=auth)
    assert huge.status_code == 422 and "available" in huge.json()["detail"]


def test_swing_plan_execute_places_tagged_paper_orders(client, auth, swing):
    plan = client.post("/api/v1/advisor/swing-plan", json={"amount": 300_000}, headers=auth).json()
    legs = [{"symbol": p["symbol"], "quantity": p["quantity"]} for p in plan["positions"] if p["quantity"]]
    assert legs
    r = client.post("/api/v1/advisor/swing-plan/execute", json={"positions": legs}, headers=auth)
    assert r.status_code == 201, r.text
    orders = r.json()["orders"]
    assert len(orders) == len(legs)
    assert all(o["tag"] == "model:swing" and o["status"] == "filled" for o in orders)


def test_model_ideas_use_the_idea_shape(client, auth, swing):
    r = client.get("/api/v1/ideas/recommendations?kind=model&limit=4", headers=auth)
    assert r.status_code == 200, r.text
    ideas = r.json()["ideas"]
    assert len(ideas) == 4
    i = ideas[0]
    assert i["kind"] == "model" and i["side"] == "buy"
    assert i["stop_loss"] < i["entry"] < i["target"]
    assert i["rationale"][0].startswith("Ranked 1 of")


# ---------------------------------------------------------------- forward test

def test_forward_test_freezes_scores_and_only_adds_new_sessions(swing, db):
    from app.models.forward import ForwardScore
    from app.services import forward_test_service, signals_service

    panel = swing["panel"]
    dates = sorted(panel["date"].unique())
    _write(panel.loc[panel["date"] <= dates[-6]], swing["path"])
    signals_service.clear_cache()
    first = forward_test_service.catch_up(db)
    assert first["started_on"] == str(pd.Timestamp(dates[-6]).date())
    rows = db.query(ForwardScore).all()
    assert {r.model_id for r in rows} == {"ensemble", "lgbm_ranker", "momentum_12_1"}
    frozen = {r.model_id: dict(r.scores) for r in rows}

    again = forward_test_service.catch_up(db)
    assert again["recorded"] == 0                       # idempotent

    _write(panel, swing["path"])                         # five more sessions arrive
    signals_service.clear_cache()
    later = forward_test_service.catch_up(db)
    assert later["recorded"] == 5 * 3
    for r in db.query(ForwardScore).filter(ForwardScore.signal_date == pd.Timestamp(dates[-6]).date()):
        assert dict(r.scores) == frozen[r.model_id]     # never recomputed

    board = forward_test_service.leaderboard(db)
    assert board["sessions"] == 5
    ids = {m["model_id"] for m in board["models"]}
    assert ids == {"ensemble", "lgbm_ranker", "momentum_12_1"}
    assert {b["model_id"] for b in board["benchmarks"]} == {"equal_weight", "nifty"}
    assert board["note"]                                 # too early to mean much


def test_leaderboard_endpoint(client, auth, swing):
    r = client.get("/api/v1/signals/leaderboard", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["started_on"] == "2026-11-24"


# ---------------------------------------------------------------- copilot

def test_copilot_model_tools(client, auth, swing, db):
    from app.models.user import User
    from app.services import copilot_tools

    user = db.query(User).filter(User.email == "investor@example.com").one()
    picks = copilot_tools.run_tool("get_model_signals", db, user, {"symbol": None})
    assert picks["picks"] and "weight" not in picks["picks"][0]["drivers"][0]
    one = copilot_tools.run_tool("get_model_signals", db, user, {"symbol": picks["picks"][0]["symbol"]})
    assert one["eligible"]
    regime = copilot_tools.run_tool("get_market_regime", db, user, {})
    assert regime["state"] in {"calm", "normal", "stress"} and regime["history"] is None
    plan = copilot_tools.run_tool("propose_swing_plan", db, user, {"amount": 200_000})
    assert plan["requires_confirmation"] is True and plan["positions"]


def test_copilot_reports_missing_models_instead_of_inventing(client, auth, swing, db, monkeypatch):
    from app.ml_runtime.registry import registry
    from app.models.user import User
    from app.services import copilot_tools

    monkeypatch.setattr(registry, "swing_ranker", lambda: None)
    user = db.query(User).filter(User.email == "investor@example.com").one()
    out = copilot_tools.run_tool("get_model_signals", db, user, {"symbol": None})
    assert out == {"available": False, "reason": out["reason"]} and "make swing" in out["reason"]


@pytest.mark.parametrize("question,tool", [
    ("Build me a swing plan with 2 lakh", "propose_swing_plan"),
    ("What do the models predict for this week?", "get_model_signals"),
    ("Is the market risky right now? What's the regime?", "get_market_regime"),
])
def test_planner_routes_model_questions(question, tool):
    from app.services.copilot_service import _plan_trading

    plan = _plan_trading(question, None)
    assert tool in [t for t, _ in plan]
    if tool == "propose_swing_plan":
        assert plan[0][1]["amount"] == 200_000


def test_template_answer_for_model_signals_is_grounded(client, auth, swing):
    r = client.post("/api/v1/chat/threads", json={}, headers=auth)
    thread = r.json()["id"]
    r = client.post(f"/api/v1/chat/threads/{thread}/messages",
                    json={"content": "What do the models predict right now?"}, headers=auth)
    assert r.status_code in (200, 201), r.text
    msg = r.json()["message"] if "message" in r.json() else r.json()
    assert "model_signals" in [c["type"] for c in msg["cards"]]
    assert msg["meta"]["grounding"]["is_grounded"], msg["meta"]["grounding"]
