"""Autopilot, the review of real holdings, amount planning, the price refresh
and the LLM provider layer.

Market data and models come from the synthetic fixture in test_signals (the
real pipeline functions trained on a synthetic 30-stock panel).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.test_signals import UNIVERSE, swing, trained  # noqa: F401 - fixtures


def _user(db, email="investor@example.com"):
    from app.models import User

    return db.query(User).filter(User.email == email).one()


def _hold(db, user, symbol: str, sector: str, quantity: float, panel: pd.DataFrame) -> None:
    """Register a synthetic stock as an asset with prices, and hold it."""
    from app.models import Asset, MarketPrice
    from app.services import portfolio_service
    from app.services.market_service import market_cache

    asset = db.query(Asset).filter(Asset.symbol == symbol).one_or_none()
    if asset is None:
        asset = Asset(symbol=symbol, name=f"Stock {symbol}", asset_class="equity", sector=sector,
                      status="active", price_source="test")
        db.add(asset)
        db.flush()
        closes = panel.loc[panel["symbol"] == symbol, ["date", "close"]].tail(300)
        for d, c in closes.itertuples(index=False):
            db.add(MarketPrice(asset_id=asset.id, date=pd.Timestamp(d).date(), close=float(c)))
    portfolio_service.upsert_holding(db, user, asset, quantity, 100.0, None)
    db.commit()
    market_cache.load(db, force=True)


# ---------------------------------------------------------------- planning an amount

def test_allocate_across_named_sectors(client, auth, swing):  # noqa: F811
    r = client.post("/api/v1/advisor/allocate", json={"amount": 50_000, "sectors": ["alpha", "Beta"]}, headers=auth)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["sectors_requested"] == ["Alpha", "Beta"]
    assert {p["sector"] for p in plan["picks"]} == {"Alpha", "Beta"}
    assert all(isinstance(p["quantity"], int) and p["quantity"] >= 0 for p in plan["picks"])
    assert plan["invested"] <= 50_000 + 1
    assert plan["invested"] + plan["cash_left"] == pytest.approx(50_000, abs=0.05)
    for p in plan["picks"]:
        assert p["cost"] == pytest.approx(p["quantity"] * p["price"], abs=0.05)
        assert p["why"]


def test_allocate_unknown_sector_is_reported(client, auth, swing):  # noqa: F811
    plan = client.post("/api/v1/advisor/allocate", json={"amount": 50_000, "sectors": ["spaceships"]},
                       headers=auth).json()
    assert any("Not recognised" in n for n in plan["notes"])


def test_allocate_long_term_has_a_core_of_real_etfs(client, auth, swing):  # noqa: F811
    plan = client.post("/api/v1/advisor/allocate", json={"amount": 200_000, "horizon": "long_term"},
                       headers=auth).json()
    assert plan["core"], plan
    assert sum(c["weight"] for c in plan["core"]) == pytest.approx(1.0, abs=1e-6)
    core_value = sum(c["value"] for c in plan["core"])
    assert core_value == pytest.approx(200_000 * 0.6, rel=1e-6)        # moderate profile: 60% core
    assert any("10 sessions" in n for n in plan["notes"])


# ---------------------------------------------------------------- starting, running, stopping

def test_autopilot_starts_from_a_confirmed_basket_and_tracks_its_sleeve(client, auth, swing):  # noqa: F811
    pv = client.post("/api/v1/paper/autopilot/preview", json={"amount": 300_000}, headers=auth)
    assert pv.status_code == 200, pv.text
    basket = pv.json()["basket"]
    assert basket and all(b["rank"] for b in basket)
    legs = [{"symbol": b["symbol"], "quantity": b["quantity"]} for b in basket]
    r = client.post("/api/v1/paper/autopilot", json={"basket": legs, "amount": 300_000}, headers=auth)
    assert r.status_code == 201, r.text
    assert all(o["tag"] == "autopilot" for o in r.json()["orders"])
    st = client.get("/api/v1/autopilot", headers=auth).json()
    assert st["settings"]["enabled"] is True
    assert st["settings"]["budget"] == 300_000
    assert {h["symbol"] for h in st["holdings"]} == {b["symbol"] for b in basket}
    assert st["sleeve_value"] == pytest.approx(300_000, rel=0.01)
    assert st["runs"] and st["runs"][0]["mode"] == "manual"
    # A second start is refused while the sleeve is live.
    again = client.post("/api/v1/paper/autopilot/preview", json={"amount": 50_000}, headers=auth)
    assert again.status_code == 422 and "already running" in again.json()["detail"]


def test_rebalance_runs_once_per_session_and_records_reasons(client, auth, swing, db):  # noqa: F811
    from app.services import autopilot_service as ap

    client.put("/api/v1/autopilot/settings", json={"budget": 250_000, "enabled": True}, headers=auth)
    user = _user(db)
    first = ap.rebalance(db, user, mode="auto", run_on=date(2026, 11, 24))
    assert first["status"] in {"done", "partial"}
    assert first["orders"] and all(o.get("reason") for o in first["orders"])
    assert all(o["side"] == "buy" for o in first["orders"])
    again = ap.rebalance(db, user, mode="auto", run_on=date(2026, 11, 24))
    assert again["status"] == "skipped"
    # The ledger only counts what Autopilot bought.
    row = ap.settings_for(db, user)
    assert sum(row.sleeve.values()) == sum(o["quantity"] for o in first["orders"] if "error" not in o)
    alerts = client.get("/api/v1/alerts", headers=auth).json()
    assert any("Autopilot" in a["title"] for a in alerts.get("alerts", alerts if isinstance(alerts, list) else []))


def test_stop_sells_only_the_sleeve(client, auth, swing, db):  # noqa: F811
    from app.services import autopilot_service as ap

    user = _user(db)
    client.put("/api/v1/autopilot/settings", json={"budget": 200_000, "enabled": True}, headers=auth)
    ap.rebalance(db, user, mode="manual", run_on=date(2026, 11, 24))
    held_sym = next(iter(ap.settings_for(db, user).sleeve))
    # The user also owns the same stock by hand.
    client.post("/api/v1/paper/orders", json={"instrument": "equity", "symbol": held_sym, "side": "buy",
                                              "quantity": 3, "order_type": "market", "product": "delivery"},
                headers=auth)
    out = client.post("/api/v1/autopilot/stop", headers=auth).json()
    assert out["settings"]["enabled"] is False and out["settings"]["sleeve"] == {}
    pf = client.get("/api/v1/paper/portfolio", headers=auth).json()
    mine = [h for h in pf["holdings"] if h["symbol"] == held_sym]
    assert mine and mine[0]["quantity"] == 3          # the hand-bought shares remain


def test_budget_guards(client, auth, swing):  # noqa: F811
    small = client.put("/api/v1/autopilot/settings", json={"budget": 5_000}, headers=auth)
    assert small.status_code == 422
    huge = client.put("/api/v1/autopilot/settings", json={"budget": 50_000_000, "enabled": True}, headers=auth)
    assert huge.status_code == 422 and "free" in huge.json()["detail"]


# ---------------------------------------------------------------- personalisation

def test_avoid_lists_and_memory_exclude_names(client, auth, swing, db):  # noqa: F811
    from app.services import account_service
    from app.services import autopilot_service as ap

    user = _user(db)
    base = ap.target(db, user)
    first = base["positions"][0]["symbol"]
    client.put("/api/v1/autopilot/settings", json={"avoid_symbols": [first]}, headers=auth)
    after = ap.target(db, user)
    assert first not in {p["symbol"] for p in after["positions"]}
    assert any(e["symbol"] == first for e in after["excluded"])
    account_service.add_memory(db, user, "avoid", "I never want beta sector stocks")
    later = ap.target(db, user)
    assert "Beta" not in {p["sector"] for p in later["positions"]}


def test_autopilot_leans_away_from_heavy_real_sectors(client, auth, swing, db):  # noqa: F811
    from app.services import autopilot_service as ap

    user = _user(db)
    _hold(db, user, "STK01", "Alpha", 1000, swing["panel"])
    tgt = ap.target(db, user)
    assert "Alpha" not in {p["sector"] for p in tgt["positions"]}
    assert any("Alpha" in n for n in tgt["notes"])


def test_review_of_real_holdings(client, auth, swing, db):  # noqa: F811
    empty = client.get("/api/v1/portfolio/review", headers=auth).json()
    assert empty["available"] is False and "Import" in empty["reason"]
    user = _user(db)
    _hold(db, user, "STK02", "Beta", 2000, swing["panel"])
    _hold(db, user, "STK05", "Alpha", 10, swing["panel"])
    review = client.get("/api/v1/portfolio/review", headers=auth).json()
    assert review["available"]
    by = {h["symbol"]: h for h in review["holdings"]}
    assert set(by) == {"STK02", "STK05"}
    assert sum(h["weight"] for h in by.values()) == pytest.approx(1.0, abs=1e-3)
    assert any(s["kind"] == "concentration" and s["symbol"] == "STK02" for s in review["suggestions"])
    assert "Nothing is traded" in review["note"]


def test_due_logic_counts_completed_sessions():
    from types import SimpleNamespace

    from app.services.autopilot_service import is_due, sessions_since

    cal = pd.bdate_range("2026-11-02", "2026-11-24")
    assert sessions_since(cal, None, date(2026, 11, 24)) > 100
    assert sessions_since(cal, date(2026, 11, 17), date(2026, 11, 24)) == 5
    row = SimpleNamespace(enabled=True, last_run_on=date(2026, 11, 17), cadence_sessions=5)
    assert is_due(row, cal, date(2026, 11, 24))
    row.last_run_on = date(2026, 11, 18)
    assert not is_due(row, cal, date(2026, 11, 24))
    row.enabled = False
    assert not is_due(row, cal, date(2026, 12, 24))


def test_run_due_runs_enabled_users_once(client, auth, swing, db):  # noqa: F811
    from app.services import autopilot_service as ap

    client.put("/api/v1/autopilot/settings", json={"budget": 150_000, "enabled": True}, headers=auth)
    ran = ap.run_due(db)
    assert len(ran) == 1 and ran[0]["status"] in {"done", "partial"}
    assert ap.run_due(db) == []                       # not due again until 5 more sessions


# ---------------------------------------------------------------- copilot

def test_copilot_tools_for_autopilot_review_and_allocation(client, auth, swing, db):  # noqa: F811
    from app.services import copilot_tools

    user = _user(db)
    plan = copilot_tools.run_tool("plan_allocation", db, user, {"amount": 50_000, "sectors": ["alpha"],
                                                                "horizon": "swing"})
    assert plan["picks"] and plan["picks"][0]["sector"] == "Alpha"
    status = copilot_tools.run_tool("get_autopilot_status", db, user, {})
    assert status["settings"]["enabled"] is False
    review = copilot_tools.run_tool("review_my_portfolio", db, user, {})
    assert review["available"] is False


def test_template_answer_for_an_allocation_question_is_grounded(client, auth, swing):  # noqa: F811
    thread = client.post("/api/v1/chat/threads", json={}, headers=auth).json()["id"]
    r = client.post(f"/api/v1/chat/threads/{thread}/messages",
                    json={"content": "How can I invest 50000 in banking and IT?"}, headers=auth)
    msg = r.json()["message"]
    assert "allocation" in [c["type"] for c in msg["cards"]]
    assert msg["meta"]["grounding"]["is_grounded"], msg["meta"]["grounding"]


# ---------------------------------------------------------------- price refresh

def test_price_refresh_chains_returns_and_is_idempotent(seeded_db, monkeypatch):
    from app.models import Asset, MarketPrice
    from app.services import price_refresh

    db = seeded_db
    reliance = db.query(Asset).filter(Asset.symbol == "RELIANCE").one()
    last_day = max(r.date for r in db.query(MarketPrice).filter(MarketPrice.asset_id == reliance.id))
    last_level = db.query(MarketPrice.close).filter(MarketPrice.asset_id == reliance.id,
                                                    MarketPrice.date == last_day).scalar()
    days = pd.bdate_range(last_day - timedelta(days=7), last_day + timedelta(days=5))

    def fake(tickers, start):
        # Every series rises 1% a session from 100.
        return pd.DataFrame({t: 100 * 1.01 ** np.arange(len(days)) for t in tickers}, index=days)

    until = days[-1].date()
    out = price_refresh.refresh(db, fetch=fake, until=until)
    assert out["added"] > 0
    rows = (db.query(MarketPrice.date, MarketPrice.close).filter(MarketPrice.asset_id == reliance.id,
                                                                  MarketPrice.date > last_day)
            .order_by(MarketPrice.date).all())
    assert rows[0][1] == pytest.approx(last_level * 1.01, rel=1e-6)   # chained, not Yahoo's level
    assert price_refresh.refresh(db, fetch=fake, until=until)["added"] == 0


# ---------------------------------------------------------------- LLM providers

def test_provider_selection(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert settings.llm_provider_active is None and not settings.copilot_enabled
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    assert settings.llm_provider_active == "anthropic"
    monkeypatch.setattr(settings, "gemini_api_key", "g-test")
    assert settings.llm_provider_active == "gemini"
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert settings.llm_provider_active == "anthropic"
    monkeypatch.setattr(settings, "llm_provider", "off")
    assert settings.llm_provider_active is None


def test_every_tool_converts_to_a_valid_gemini_declaration():
    from google.genai import types

    from app.services.copilot_tools import TOOL_SCHEMAS
    from app.services.llm.gemini_provider import declarations, to_gemini_schema

    tool = types.Tool(function_declarations=declarations(TOOL_SCHEMAS))
    assert len(tool.function_declarations) == len(TOOL_SCHEMAS)
    s = to_gemini_schema({"type": ["string", "null"], "enum": ["CE", "PE", None], "description": "x"})
    assert s == {"type": "STRING", "nullable": True, "description": "x", "enum": ["CE", "PE"]}
    arr = to_gemini_schema({"type": ["array", "null"], "items": {"type": "string"}})
    assert arr["type"] == "ARRAY" and arr["nullable"] and arr["items"]["type"] == "STRING"


def test_gemini_loop_calls_tools_and_returns_the_answer(monkeypatch):
    from google.genai import types

    from app.core.config import settings
    from app.services import llm
    from app.services.llm import gemini_provider

    monkeypatch.setattr(settings, "gemini_api_key", "g-test")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    seen = {}

    def reply(parts, finish="STOP"):
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish)],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10,
                                                                      candidates_token_count=5))

    class Models:
        calls = 0

        def generate_content(self, model, contents, config):
            Models.calls += 1
            seen.setdefault("contents", []).append(list(contents))
            seen["config"] = config
            if Models.calls == 1:
                return reply([types.Part(function_call=types.FunctionCall(id="c1", name="get_quote",
                                                                          args={"symbol": "TCS"}))])
            return reply([types.Part(text="TCS trades at ₹3,500.")])

    class FakeClient:
        def __init__(self, api_key):
            seen["key"] = api_key
            self.models = Models()

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    dispatched = []

    def dispatch(name, args):
        dispatched.append((name, args))
        return {"symbol": "TCS", "ltp": 3500.0}

    out = llm.run("system", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
                  "How is TCS?", [{"name": "get_quote", "description": "q", "input_schema": {
                      "type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"],
                      "additionalProperties": False}}], dispatch)
    assert seen["key"] == "g-test"
    assert dispatched == [("get_quote", {"symbol": "TCS"})]
    assert out["answer"] == "TCS trades at ₹3,500." and out["provider"] == "gemini"
    assert out["tool_outputs"] == [{"symbol": "TCS", "ltp": 3500.0}]
    assert out["usage"] == {"input_tokens": 20, "output_tokens": 10}
    # The model's function-call turn went back unchanged, then the function response with its id.
    second = seen["contents"][1]
    assert second[-2].parts[0].function_call.name == "get_quote"
    assert second[-1].parts[0].function_response.id == "c1"
    assert seen["config"].automatic_function_calling.disable is True
    assert gemini_provider  # imported for the monkeypatch target


def test_gemini_safety_block_falls_back_to_templates(client, auth, monkeypatch):
    from google.genai import types

    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "g-test")

    class Models:
        def generate_content(self, model, contents, config):
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=[]), finish_reason="SAFETY")])

    class FakeClient:
        def __init__(self, api_key):
            self.models = Models()

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    body = client.post("/api/v1/copilot/chat", json={"message": "What is my portfolio worth?"}, headers=auth).json()
    assert body.get("used_fallback") is True
    assert "declined" in (body.get("fallback_reason") or "")
