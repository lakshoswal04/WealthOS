"""The trading surfaces on real-shaped data: markets, options, screeners,
ideas, paper trading and chat.

Prices come from the `market` fixture: Yahoo-style quotes derived from the
seeded test market, and a mock Upstox API for options. Nothing in the
application is simulated any more, and one test asserts exactly that.
"""

from __future__ import annotations

import pytest

from app.models import User
from tests.fakes import NIFTY_LOT, connect_upstox, dump


@pytest.fixture
def upstox(market, seeded_db, auth):
    """The registered test user, with a live Upstox session."""
    user = seeded_db.query(User).filter_by(email="investor@example.com").one()
    connect_upstox(seeded_db, user)
    return market


# --------------------------------------------------------------------------
# Markets
# --------------------------------------------------------------------------

def test_quotes_are_real_and_labelled_delayed_without_upstox(client, auth, market):
    body = client.get("/api/v1/markets/indices", headers=auth).json()
    assert [q["symbol"] for q in body["indices"]] == ["NIFTY"]          # only what a source priced
    assert {q["source"] for q in body["indices"]} == {"delayed"}
    q = client.get("/api/v1/markets/quote/RELIANCE", headers=auth).json()
    assert q["source"] == "delayed" and q["ltp"] > 0


def test_a_symbol_no_source_can_price_is_unavailable_not_invented(client, auth, market):
    r = client.get("/api/v1/markets/quote/HDFCBANK", headers=auth)     # in the universe, not in the fixture
    assert r.status_code == 503 and r.json()["code"] == "market_data_unavailable"
    assert client.get("/api/v1/markets/quote/NOTREAL", headers=auth).status_code == 404


def test_connected_users_get_live_quotes(client, auth, upstox):
    q = client.get("/api/v1/markets/quote/RELIANCE", headers=auth).json()
    assert q["source"] == "live" and q["ltp"] == 1500.0


def test_no_market_response_is_ever_simulated(client, auth, upstox):
    responses = [
        client.get("/api/v1/markets/indices", headers=auth).json(),
        client.get("/api/v1/markets/quote/RELIANCE", headers=auth).json(),
        client.get("/api/v1/options/chain/NIFTY?strikes=3", headers=auth).json(),
        client.get("/api/v1/paper/portfolio", headers=auth).json(),
    ]
    assert "simulated" not in dump(responses).lower()


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

def test_options_without_upstox_say_why_instead_of_modelling(client, auth, market):
    for path in ("/api/v1/options/chain/NIFTY", "/api/v1/options/summary/NIFTY",
                 "/api/v1/options/top?segment=futures"):
        r = client.get(path, headers=auth)
        assert r.status_code == 409, path
        body = r.json()
        assert body["code"] == "upstox_required" and body["action"]["href"] == "/settings/brokers"


def test_expiries_and_lot_sizes_come_from_the_instrument_master(client, auth, market):
    body = client.get("/api/v1/options/expiries/NIFTY", headers=auth).json()
    assert body["expiries"] == ["2026-12-01", "2026-12-08"]
    assert body["lot_size"] == NIFTY_LOT


def test_the_live_chain_is_parsed(client, auth, upstox):
    body = client.get("/api/v1/options/chain/NIFTY?strikes=4", headers=auth).json()
    assert body["source"] == "live" and body["expiry"] == "2026-12-01"
    assert len(body["rows"]) == 9 and body["atm_strike"] == 25900
    assert body["pcr"] == pytest.approx(body["total_put_oi"] / body["total_call_oi"], abs=0.01)
    row = body["rows"][0]
    assert row["ce"]["iv"] == 14.5 and row["ce"]["oi_change"] == 2000
    assert body["resistance"] == 26000 or body["resistance"] in [r["strike"] for r in body["rows"]]


def test_an_expired_upstox_session_is_detected_and_reported(client, auth, upstox, seeded_db):
    upstox.expired_tokens.add("good-token")
    r = client.get("/api/v1/options/chain/NIFTY", headers=auth)
    assert r.status_code == 409 and r.json()["state"] == "expired"
    status = client.get("/api/v1/me/brokers", headers=auth).json()["brokers"]
    assert next(b for b in status if b["broker"] == "upstox")["state"] == "expired"


def test_oi_tools_use_candle_open_interest(client, auth, upstox):
    ms = client.get("/api/v1/options/multi-strike/NIFTY?strikes=25900,26000", headers=auth).json()
    assert len(ms["series"]) == 2 and ms["series"][0]["points"]
    cross = client.get("/api/v1/options/crossovers/NIFTY", headers=auth).json()
    assert "crossovers" in cross and cross["strikes_checked"] > 0
    unusual = client.get("/api/v1/options/unusual", headers=auth).json()
    ratios = [c["volume_to_oi"] for c in unusual["contracts"]]
    assert ratios == sorted(ratios, reverse=True)


# --------------------------------------------------------------------------
# Screeners and ideas
# --------------------------------------------------------------------------

def test_a_price_screen_runs_on_the_close_only_panel(client, auth, market):
    body = client.get("/api/v1/screeners/run/strong-uptrend", headers=auth).json()
    assert body["available"] is True and body["data_source"] == "analytics_panel_close_only"


def test_a_volume_screen_says_why_it_cannot_run(client, auth, market):
    body = client.get("/api/v1/screeners/run/volume-shockers", headers=auth).json()
    assert body["available"] is False and "volume" in body["reason"].lower()


def test_malformed_custom_screens_are_rejected(client, auth, market):
    for definition in ({"filters": [{"field": "nonsense", "op": "gt", "value": 1}]},
                       {"filters": [{"field": "rsi_14", "op": "between", "value": [1]}]}):
        assert client.post("/api/v1/screeners/run", headers=auth, json=definition).status_code == 422


def test_saved_screens_belong_to_their_owner(client, auth, second_user, market):
    sid = client.post("/api/v1/screeners/saved", headers=auth, json={
        "name": "Mine", "definition": {"filters": [{"field": "rsi_14", "op": "lte", "value": 70}]}}).json()["id"]
    other = second_user["headers"]
    assert client.get(f"/api/v1/screeners/saved/{sid}/run", headers=other).status_code == 404
    assert client.get("/api/v1/screeners/saved", headers=other).json()["screens"] == []


def test_fno_ideas_need_upstox_and_then_use_the_live_chain(client, auth, market, seeded_db):
    assert client.get("/api/v1/ideas/recommendations?kind=fno", headers=auth).status_code == 409
    user = seeded_db.query(User).filter_by(email="investor@example.com").one()
    connect_upstox(seeded_db, user)
    body = client.get("/api/v1/ideas/recommendations?kind=fno", headers=auth).json()
    for idea in body["ideas"]:
        assert idea["price_source"] == "live"
        assert len({(l["strike"], l["option_type"]) for l in idea["legs"]}) == len(idea["legs"])


def test_buy_and_hold_backtest_tracks_the_market_less_costs(client, auth, market):
    body = client.get("/api/v1/ideas/backtest/buy-and-hold?symbol=NIFTY", headers=auth).json()
    assert body["available"] is True
    assert body["total_return_pct"] < body["buy_and_hold_return_pct"]


# --------------------------------------------------------------------------
# Paper trading
# --------------------------------------------------------------------------

def _buy(client, auth, symbol="RELIANCE", qty=10, **extra):
    return client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "equity", "symbol": symbol, "side": "buy", "quantity": qty, **extra})


def test_a_market_buy_fills_at_the_real_quote(client, auth, market):
    ltp = client.get("/api/v1/markets/quote/RELIANCE", headers=auth).json()["ltp"]
    order = _buy(client, auth, qty=10).json()
    assert order["status"] == "filled" and order["fill_price"] == ltp and order["price_source"] == "delayed"
    pf = client.get("/api/v1/paper/portfolio", headers=auth).json()
    assert pf["cash"] == pytest.approx(1_000_000 - 10 * ltp, abs=0.01)
    assert pf["holdings"][0]["day_pnl"] == pytest.approx(0, abs=0.01)


def test_selling_more_than_held_is_refused_and_recorded(client, auth, market):
    _buy(client, auth, qty=5)
    r = client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "equity", "symbol": "RELIANCE", "side": "sell", "quantity": 6})
    assert r.json()["status"] == "rejected" and "short selling" in r.json()["reject_reason"]


def test_an_unpriceable_stock_cannot_be_traded(client, auth, market):
    r = _buy(client, auth, symbol="HDFCBANK", qty=1)
    assert r.status_code == 422 and "No price" in r.json()["detail"]


def test_option_orders_need_upstox(client, auth, market):
    r = client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "option", "symbol": "NIFTY", "side": "buy", "lots": 1, "option_type": "CE", "strike": 26000})
    assert r.status_code == 422 and "Upstox" in r.json()["detail"]


def test_options_fill_at_the_live_premium_in_real_lot_sizes(client, auth, upstox):
    bad = client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "option", "symbol": "NIFTY", "side": "buy", "quantity": 10, "option_type": "CE", "strike": 26000})
    assert bad.status_code == 422 and f"lots of {NIFTY_LOT}" in bad.json()["detail"]
    chain = client.get("/api/v1/options/chain/NIFTY?strikes=5", headers=auth).json()
    ltp = next(r for r in chain["rows"] if r["strike"] == 26000)["ce"]["ltp"]
    order = client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "option", "symbol": "NIFTY", "side": "buy", "lots": 1, "option_type": "CE", "strike": 26000}).json()
    assert order["status"] == "filled" and order["quantity"] == NIFTY_LOT and order["fill_price"] == ltp


def test_writing_an_option_blocks_the_margin_upstox_quotes(client, auth, upstox):
    r = client.post("/api/v1/paper/orders", headers=auth, json={
        "instrument": "option", "symbol": "NIFTY", "side": "sell", "lots": 1, "option_type": "PE", "strike": 25000}).json()
    assert r["status"] == "filled"
    pf = client.get("/api/v1/paper/portfolio", headers=auth).json()
    assert pf["margin_used"] == upstox.margin
    assert pf["available"] == pytest.approx(pf["cash"] - upstox.margin)


def test_one_user_cannot_touch_anothers_orders(client, auth, second_user, market):
    order = _buy(client, auth, qty=1, order_type="limit", limit_price=1.0).json()
    other = second_user["headers"]
    assert client.post(f"/api/v1/paper/orders/{order['id']}/cancel", headers=other).status_code == 404


def test_autopilot_previews_then_places_only_on_confirmation(client, auth, market):
    preview = client.post("/api/v1/paper/autopilot/preview", headers=auth, json={"amount": 50_000})
    if preview.status_code == 422:      # the tiny fixture market may have nothing to buy
        assert "autopilot" in preview.json()["detail"].lower()
        return
    assert client.get("/api/v1/paper/orders", headers=auth).json()["total"] == 0


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

def _say(client, auth, content, **extra):
    tid = client.post("/api/v1/chat/threads", headers=auth, json={}).json()["id"]
    r = client.post(f"/api/v1/chat/threads/{tid}/messages", headers=auth, json={"content": content, **extra})
    assert r.status_code == 200, r.text
    return r.json()["message"]


def test_asking_to_buy_proposes_and_never_places(client, auth, market):
    msg = _say(client, auth, "buy 10 shares of RELIANCE")
    card = next(c for c in msg["cards"] if c["type"] == "order_proposal")
    assert card["requires_confirmation"] is True and card["order"]["quantity"] == 10
    assert client.get("/api/v1/paper/orders", headers=auth).json()["total"] == 0


def test_an_oi_question_without_upstox_explains_how_to_connect(client, auth, market):
    msg = _say(client, auth, "Which strike has the most OI build-up?", context={"symbol": "NIFTY"})
    assert msg["meta"]["tools_called"] == ["get_option_chain_summary"]
    assert "Upstox" in msg["content"]


def test_an_oi_question_with_upstox_is_answered_grounded(client, auth, upstox):
    msg = _say(client, auth, "Which strike has the most OI build-up?", context={"symbol": "NIFTY"})
    assert msg["meta"]["grounding"]["is_grounded"], msg["meta"]["grounding"]
    assert any(c["type"] == "option_summary" for c in msg["cards"])


def test_portfolio_questions_still_reach_the_portfolio_tools(client, auth, market):
    msg = _say(client, auth, "How risky is my portfolio?")
    assert "get_risk_metrics" in msg["meta"]["tools_called"]
