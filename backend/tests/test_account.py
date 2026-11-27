"""The account menu: preferences, notifications, AI memory, broker credentials."""

from __future__ import annotations

from app.services.account_service import extract_memories


def test_settings_start_from_defaults_and_validate(client, auth):
    body = client.get("/api/v1/me/settings", headers=auth).json()
    assert body["preferences"]["default_symbol"] == "NIFTY"
    assert body["notifications"]["order_fills"] is True

    ok = client.patch("/api/v1/me/settings", headers=auth, json={
        "preferences": {"default_lots": 2, "default_product": "intraday", "default_symbol": "reliance"},
        "notifications": {"price_alerts": False}}).json()
    assert ok["preferences"]["default_lots"] == 2
    assert ok["preferences"]["default_symbol"] == "RELIANCE"
    assert ok["notifications"]["price_alerts"] is False
    assert "daily_summary" not in ok["notifications"]       # no email or push infrastructure

    for bad in [{"default_lots": 0}, {"default_product": "margin"}, {"default_symbol": "NOTREAL"},
                {"one_tap_default": "yes"}]:
        r = client.patch("/api/v1/me/settings", headers=auth, json={"preferences": bad})
        assert r.status_code == 422, bad


def test_ai_order_confirmation_cannot_be_switched_off(client, auth):
    body = client.patch("/api/v1/me/settings", headers=auth,
                        json={"preferences": {"confirm_ai_orders": False}}).json()
    assert body["preferences"]["confirm_ai_orders"] is True


def test_memories_are_added_listed_and_private(client, auth, second_user):
    r = client.post("/api/v1/me/memory", headers=auth, json={"section": "markets", "text": "Trades NIFTY weeklies"})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.post("/api/v1/me/memory", headers=auth,
                       json={"section": "markets", "text": "trades nifty weeklies"}).status_code == 422
    assert client.post("/api/v1/me/memory", headers=auth,
                       json={"section": "nonsense", "text": "x y"}).status_code == 422

    other = second_user["headers"]
    assert client.get("/api/v1/me/memory", headers=other).json()["memories"] == []
    assert client.delete(f"/api/v1/me/memory/{mid}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/me/memory/{mid}", headers=auth).status_code == 204


def test_chat_fills_memory_unless_paused(client, auth):
    tid = client.post("/api/v1/chat/threads", headers=auth, json={}).json()["id"]
    reply = client.post(f"/api/v1/chat/threads/{tid}/messages", headers=auth,
                        json={"content": "I am a swing trader. How is NIFTY doing?"}).json()
    assert reply["message"]["meta"]["remembered"][0]["text"] == "Is a swing trader"

    client.put("/api/v1/me/memory/state", headers=auth, json={"paused": True})
    client.post(f"/api/v1/chat/threads/{tid}/messages", headers=auth,
                json={"content": "I prefer large caps."})
    texts = [m["text"] for m in client.get("/api/v1/me/memory", headers=auth).json()["memories"]]
    assert texts == ["Is a swing trader"]


def test_only_durable_statements_are_remembered():
    assert extract_memories("I'm looking at NIFTY now") == []
    assert extract_memories("I never trade penny stocks.") == [("avoid", "Avoids penny stocks")]

# Broker credentials and the Upstox login are covered by test_upstox.py.


def test_every_prompt_book_example_routes_to_the_tool_it_teaches():
    from app.content.prompt_book import CHAPTERS
    from app.services.copilot_service import _plan_trading, _select_tools

    for chapter in CHAPTERS:
        for example in chapter["examples"]:
            plan = [tool for tool, _ in _plan_trading(example["prompt"], None)] or _select_tools(example["prompt"])
            assert example["tool"] in plan, (example["prompt"], plan)


def test_the_prompt_book_has_a_hindi_edition(client, auth):
    en = client.get("/api/v1/me/prompt-book", headers=auth).json()
    hi = client.get("/api/v1/me/prompt-book?lang=hi", headers=auth).json()
    assert len(en["chapters"]) == len(hi["chapters"]) == 6
    assert en["chapters"][0]["title"] != hi["chapters"][0]["title"]
    assert en["chapters"][0]["examples"] == hi["chapters"][0]["examples"]
