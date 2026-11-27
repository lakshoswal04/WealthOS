"""The AI Wealth Copilot.

The Copilot is an explanation layer, not a calculator. It selects which
backend measurements to fetch, then narrates them. Every number it reports
is checked against the tool outputs before the answer is returned, so the
grounding claim is enforced rather than merely intended.

Two execution paths:

  LLM path       Tool-calling on Gemini or Claude (app/services/llm), used
                 when GEMINI_API_KEY or ANTHROPIC_API_KEY is configured.
  Fallback path  A deterministic template explainer over the same tools,
                 used when no key is present. The platform stays fully
                 usable without an external dependency, which is what the
                 PRD's reliability requirement asks for.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from app.services import copilot_tools
from app.services.copilot_grounding import check_groundedness

log = logging.getLogger("wealthos.copilot")

MAX_TOOL_ROUNDS = 6
MAX_TOKENS = 8192

SYSTEM_PROMPT = """\
You are the WealthOS trading assistant. You help an investor understand Indian \
markets, their paper-trading account and their long-term portfolio, using \
measurements computed by the WealthOS backend.

How you must work:
- Call tools to obtain every figure: prices, option-chain statistics, screen \
results, backtests, portfolio values. You have no other source of numbers.
- Never calculate, estimate, infer or recall a financial number yourself. If \
a figure you want is not in a tool result, say it is not available rather \
than producing one.
- Quote figures as the tools report them, rounding at most to one or two \
decimal places.
- If a tool reports available=false, tell the user that and why.
- Prices are live from Upstox when the user has connected it, otherwise \
delayed about fifteen minutes (each quote's `source` says which). Option \
chains, OI and futures exist only with an Upstox session; if a tool says it is \
unavailable, tell the user to connect Upstox under Settings → Broker APIs.
- Trade ideas from get_ideas are rule-based setups, not advice. Present them \
with their rationale and stop-loss, and say they are educational.
- get_model_signals, get_market_regime and propose_swing_plan come from \
trained models. Give a stock's 10-session view as its range (low to high), \
never a single expected price; say what drove the score; quote the model's \
out-of-sample record (IC, hit rate, return against equal-weight) when it \
matters; and call it a research signal for paper trading. Hit rates near \
51 to 54% are normal for market models: do not describe them as accuracy \
that guarantees anything.

Orders:
- This is paper trading only; no real money and no broker are involved.
- When the user asks to buy or sell, call propose_paper_order (or \
propose_autopilot, or propose_swing_plan for a model-built swing basket).
- For "how should I invest X" or "invest X across sectors", call \
plan_allocation; for questions about their own holdings, review_my_portfolio; \
for Autopilot, get_autopilot_status. Real holdings are only ever advised on; \
Autopilot trades its paper sleeve alone. It places nothing: the user sees a card and presses \
Confirm. Tell them to review and confirm it. Never claim an order was placed.
- Never propose an order the user did not ask for.

What you must not do:
- Do not present any view as a recommendation to trade real money, or \
promise returns. Do not describe a forecast or backtest as what will happen.
- Do not invent history, news, prices or events.

Style: direct and plain. Lead with the answer. Two to four short paragraphs \
at most; use a short list when comparing several figures. Write amounts in \
rupees as the tools give them."""

DISCLAIMER = (
    "WealthOS is an academic research prototype. It explains computed "
    "portfolio metrics and does not provide investment advice. Trading is "
    "simulated (paper) only."
)


# --------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------

def _with_context(question: str, context: dict | None) -> str:
    if context and context.get("symbol"):
        return f"[The user is looking at the {context['symbol']} chart.]\n{question}"
    return question


def _answer_with_llm(db: Session, user: User, question: str, history: list[dict],
                     context: dict | None = None, memory: str | None = None) -> dict:
    """Run the tool-calling loop on the configured provider (Gemini or Claude)."""
    from app.services import llm

    turns = [{"role": t["role"], "content": t["content"]} for t in history[-6:]
             if t.get("role") in ("user", "assistant") and t.get("content")]
    try:
        return llm.run(
            system=SYSTEM_PROMPT + (f"\n\n{memory}" if memory else ""),
            history=turns,
            question=_with_context(question, context),
            tools=copilot_tools.TOOL_SCHEMAS,
            dispatch=lambda name, arguments: copilot_tools.run_tool(name, db, user, arguments),
            max_rounds=MAX_TOOL_ROUNDS,
            max_tokens=MAX_TOKENS,
        )
    except llm.ProviderUnavailable as exc:
        raise CopilotUnavailable(str(exc)) from exc


class CopilotUnavailable(Exception):
    """The LLM path could not produce an answer."""


# --------------------------------------------------------------------------
# Deterministic fallback
# --------------------------------------------------------------------------

INTENTS = {
    "health": (["health", "score", "rating", "how good", "how healthy"], ["get_health_score"]),
    "risk": (["risk", "risky", "volatil", "drawdown", "sharpe", "sortino", "safe", "loss"],
             ["get_risk_metrics"]),
    "concentration": (["concentrat", "diversif", "exposure", "overweight", "spread", "sector"],
                      ["get_concentration"]),
    "goals": (["goal", "on track", "retirement", "target", "shortfall", "save"],
              ["get_goal_status"]),
    "forecast": (["forecast", "project", "future", "worth", "will i have", "grow"],
                 ["get_forecast"]),
    "profile": (["what kind of investor", "profile", "behaviour", "behavior", "cluster", "type of investor"],
                ["get_investor_profile"]),
    "anomaly": (["unusual", "anomal", "strange", "odd", "alert", "change"],
                ["get_anomalies"]),
    "portfolio": (["portfolio", "own", "holding", "value", "worth", "allocation", "much"],
                  ["get_portfolio_summary"]),
}


def _select_tools(question: str) -> list[str]:
    """Pick tools by keyword, for the no-LLM path."""
    lowered = (question or "").lower()
    chosen: list[str] = []
    for _, (keywords, tools) in INTENTS.items():
        if any(k in lowered for k in keywords):
            for tool in tools:
                if tool not in chosen:
                    chosen.append(tool)
    if not chosen:
        chosen = ["get_portfolio_summary", "get_health_score"]
    # The summary gives any answer its anchor figures.
    if "get_portfolio_summary" not in chosen:
        chosen.insert(0, "get_portfolio_summary")
    return chosen[:4]


def _rupees(value: Any) -> str:
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return "an unavailable amount"


def _narrate(tool: str, data: dict) -> list[str]:
    """Turn one tool's output into sentences, without an LLM."""
    if data.get("available") is False:
        return [f"{tool.replace('get_', '').replace('_', ' ').capitalize()} "
                f"could not be computed: {data.get('reason', 'no reason given')}."]

    if tool == "get_portfolio_summary":
        lines = [
            f"Your portfolio is worth {_rupees(data['total_value'])} across "
            f"{data['n_holdings']} holdings in {data['n_sectors']} sectors, "
            f"valued as of {data['as_of']}.",
            f"Against a cost of {_rupees(data['total_cost'])} that is an "
            f"unrealised gain of {_rupees(data['unrealized_gain'])} "
            f"({data['unrealized_gain_pct']:+.2f}%).",
        ]
        if data.get("allocation_by_class"):
            parts = ", ".join(
                f"{a['label']} {a['weight_pct']:.1f}%" for a in data["allocation_by_class"]
            )
            lines.append(f"By asset class: {parts}.")
        return lines

    if tool == "get_risk_metrics":
        return [
            f"Annualised volatility is {data['annualized_volatility_pct']:.2f}% and the "
            f"annualised return {data['annualized_return_pct']:.2f}%, giving a Sharpe "
            f"ratio of {data['sharpe_ratio']:.3f} at a "
            f"{data['assumptions']['risk_free_rate']:.0%} risk-free rate.",
            f"The worst peak-to-trough fall was {abs(data['max_drawdown_pct']):.2f}%, from "
            f"{data['drawdown_peak_date']} to {data['drawdown_trough_date']}"
            + (" and it has since recovered." if data["recovered"] else " and it has not yet recovered."),
            f"Beta against the NIFTY 50 is {data['beta']:.3f}.",
        ]

    if tool == "get_concentration":
        lines = [
            f"The portfolio holds {data['n_holdings']} positions but behaves like about "
            f"{data['effective_holdings']:.1f} equally weighted ones. The largest, "
            f"{data['largest_holding']}, is {data['top_1_weight_pct']:.1f}% and the top "
            f"five are {data['top_5_weight_pct']:.1f}%.",
        ]
        if data.get("largest_sector"):
            lines.append(
                f"The heaviest sector is {data['largest_sector']} at "
                f"{data['max_sector_weight_pct']:.1f}%."
            )
        lines.extend(data.get("observations", []))
        return lines

    if tool == "get_health_score":
        lines = [f"The Portfolio Health Score is {data['total']} out of 100 ({data['grade']})."]
        for component in sorted(
            [c for c in data["components"] if c["score"] is not None],
            key=lambda c: c["score"],
        )[:3]:
            lines.append(
                f"{component['name'].replace('_', ' ').capitalize()} scores "
                f"{component['score']:.0f}. {component['reason']}"
            )
        if data.get("components_not_measured"):
            lines.append(
                "Not measured: "
                + ", ".join(m.replace("_", " ") for m in data["components_not_measured"])
                + "."
            )
        return lines

    if tool == "get_goal_status":
        if not data.get("has_goals"):
            return ["No goals have been set, so there is nothing to track progress against."]
        lines = [f"{data['n_on_track']} of {data['n_goals']} goals are projected to be met."]
        for goal in data["goals"][:3]:
            lines.append(
                f"{goal['name']}: {_rupees(goal['projected_value'])} projected against a "
                f"{_rupees(goal['target_amount'])} target by {goal['target_date']}, "
                f"{goal['funding_pct']:.0f}% funded."
                + (
                    f" Reaching it needs {_rupees(goal['required_monthly_contribution'])} "
                    f"a month against the {_rupees(goal['monthly_contribution'])} currently set."
                    if not goal["on_track"] else ""
                )
            )
        return lines

    if tool == "get_forecast":
        band = data.get("projection_range", {})
        return [
            f"Over {data['horizon_months']} months the models project "
            f"{_rupees(data['projected_value'])}, against a baseline of "
            f"{_rupees(data['baseline_value'])} if markets returned nothing.",
            f"The individual models span {_rupees(band.get('low'))} to "
            f"{_rupees(band.get('high'))}; {band.get('agreement', '')}.",
            "This is a projection under stated assumptions, not a prediction. "
            "Actual returns vary and may be negative.",
        ]

    if tool == "get_investor_profile":
        return [
            f"This portfolio's behaviour most resembles the "
            f"'{data['cluster_name']}' group, which is {data['cluster_share'] * 100:.1f}% "
            f"of the reference cohort.",
            f"Stated risk tolerance on the profile is {data['stated_risk_tolerance']}.",
            data.get("caveat", ""),
        ]

    if tool == "get_anomalies":
        if data.get("anomalies_found", 0) == 0:
            return [
                f"No unusual months were detected across the "
                f"{data['months_examined']} examined."
            ]
        lines = [
            f"{data['anomalies_found']} unusual months were flagged out of "
            f"{data['months_examined']} examined."
        ]
        for anomaly in data["anomalies"][:3]:
            drivers = ", ".join(c["feature"] for c in anomaly["contributing_features"])
            lines.append(f"{anomaly['date']} ({anomaly['severity']}), driven by {drivers}.")
        return lines

    return []


# --------------------------------------------------------------------------
# Fallback planner for trading questions
# --------------------------------------------------------------------------

_UNDERLYING_KEYS = ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "NIFTY"]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9&]+", text.lower()))


def _detect_symbols(question: str) -> list[str]:
    """Stocks or indices named in a question, by symbol or by company name.

    Symbols of three letters or fewer (LT, ITC, BEL) only count when written
    in capitals, so "let" and "bel air" do not summon a stock.
    """
    from app.services import live_market_service as live

    found: list[str] = []
    upper_tokens = set(re.findall(r"[A-Z][A-Z0-9&-]+", question))
    lowered = question.lower()
    words = _words(question)
    for key in _UNDERLYING_KEYS + ["INDIAVIX"]:
        if key.lower() in words or key in upper_tokens or (key == "BANKNIFTY" and "bank nifty" in lowered):
            found.append(key)
            if key == "BANKNIFTY":
                break
    if "BANKNIFTY" in found and "NIFTY" in found:
        found.remove("NIFTY")
    uni = live.universe()
    for symbol, name in zip(uni["symbol"], uni["name"]):
        if len(symbol) <= 3:
            hit = symbol in upper_tokens
        else:
            hit = symbol.lower() in words or symbol in upper_tokens
        short_name = name.lower().split(" (")[0]
        if hit or (len(short_name) > 4 and short_name in lowered):
            found.append(symbol)
    return list(dict.fromkeys(found))


def _has(words: set[str], text: str, *keys: str) -> bool:
    # Single plain words match whole words; anything with a space or
    # punctuation ("max pain", "52-week", "f&o") matches as a phrase.
    return any((k in words) if k.isalnum() else (k in text) for k in keys)


def _amount(text: str) -> float | None:
    """An amount of money in the question: 50000, 50,000, 50k, 2 lakh, ₹1.5 lakh, 1 crore."""
    m = re.search(r"(?:rs\.?|₹|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs|lac|l|crore|cr)?\b", text)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = m.group(2) or ""
    value *= (1_000 if unit in {"k", "thousand"} else 100_000 if unit in {"lakh", "lakhs", "lac", "l"}
              else 10_000_000 if unit in {"crore", "cr"} else 1)
    return value if value >= 1_000 else None


def _plan_trading(question: str, context: dict | None) -> list[tuple[str, dict]]:
    """Map a trading question to tool calls, or [] if it is not one."""
    from app.services import ideas_service, screener_service

    text = (question or "").lower()
    words = _words(question)
    symbols = _detect_symbols(question or "")
    ctx_symbol = (context or {}).get("symbol")
    if not symbols and ctx_symbol:
        symbols = [ctx_symbol.upper()]
    underlying = next((s for s in symbols if s in _UNDERLYING_KEYS), None) or "NIFTY"
    stock = next((s for s in symbols if s not in _UNDERLYING_KEYS and s != "INDIAVIX"), None)
    plan: list[tuple[str, dict]] = []

    if "swing" in words and _has(words, text, "plan", "portfolio", "basket", "invest", "allocate", "build"):
        amt = re.search(r"(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lakhs|l)?\b", text)
        amount = 100_000.0
        if amt and amt.group(1).replace(",", "").replace(".", "").isdigit():
            amount = float(amt.group(1).replace(",", ""))
            unit = amt.group(2)
            amount *= 1_000 if unit == "k" else 100_000 if unit in {"lakh", "lakhs", "l"} else 1
        return [("propose_swing_plan", {"amount": amount})]

    amount = _amount(text)
    if "autopilot" in words and _has(words, text, "doing", "status", "performing", "perform", "did", "done",
                                     "running", "how is", "how's", "history", "runs"):
        return [("get_autopilot_status", {})]
    if "autopilot" in words:
        return [("propose_autopilot", {"amount": amount or 50_000.0})]

    if _has(words, text, "review", "holdings", "my stocks", "my portfolio look", "what should i do with") and \
            _has(words, text, "my", "holdings"):
        return [("review_my_portfolio", {})]

    if amount and _has(words, text, "invest", "allocate", "put", "deploy", "split", "spread", "diversify",
                       "sector", "sectors"):
        from app.services.autopilot_service import SECTOR_ALIASES, known_sectors

        found = [s for s in known_sectors() if s.lower() in text]
        found += [v for k, v in SECTOR_ALIASES.items()
                  if (k in words if k.isalnum() else k in text)
                  # "it" is the sector only when written as IT.
                  and (k != "it" or re.search(r"\bIT\b", question or ""))]
        horizon = "long_term" if _has(words, text, "long term", "long-term", "years", "retirement", "wealth",
                                      "sip", "invest for") else "swing"
        return [("plan_allocation", {"amount": amount, "sectors": list(dict.fromkeys(found)) or None,
                                     "horizon": horizon})]

    order = re.search(
        r"\b(buy|sell)\s+(\d+)\s*(lots?|shares?|units?)?\s*(?:of\s+)?([a-z&-]+)?"
        r"(?:\s+(\d{4,6}))?\s*(ce|pe|call|put)?", text)
    if order:
        side, qty, unit = order.group(1), int(order.group(2)), order.group(3) or ""
        strike_txt, opt = order.group(5), order.group(6)
        if opt and strike_txt:
            args = {"instrument": "option", "symbol": underlying, "side": side,
                    "option_type": "CE" if opt in {"ce", "call"} else "PE",
                    "strike": float(strike_txt), "expiry": None, "order_type": "market",
                    "limit_price": None, "quantity": None, "lots": None}
            if unit.startswith("lot"):
                args["lots"] = qty
            else:
                args["quantity"] = qty
            return [("propose_paper_order", args)]
        if stock:
            return [("propose_paper_order", {
                "instrument": "equity", "symbol": stock, "side": side, "quantity": qty,
                "lots": None, "option_type": None, "strike": None, "expiry": None,
                "order_type": "market", "limit_price": None})]

    if "backtest" in words or "back-test" in text or "back test" in text:
        strategy = "ema-crossover"
        for st in ideas_service.STRATEGIES:
            if st.name.lower().split(" ")[0] in text or st.id.split("-")[0] in words:
                strategy = st.id
                break
        return [("run_backtest", {"strategy_id": strategy, "symbol": stock or (symbols[0] if symbols else None)})]

    if _has(words, text, "support", "resistance", "oi", "pcr", "strike", "strikes", "option",
            "options", "premium", "premiums", "hedge", "expiry", "max pain", "open interest",
            "call", "calls", "put", "puts"):
        plan.append(("get_option_chain_summary", {"underlying": underlying, "expiry": None}))

    # "Risky" and "cautious" name the market's regime only when the question is
    # about the market; "how risky is my portfolio" belongs to the risk metrics.
    about_market = _has(words, text, "market", "markets", "nifty") and not _has(words, text, "my", "portfolio")
    if _has(words, text, "regime", "risk-on", "risk-off", "risk on", "risk off", "market risk") or (
            about_market and _has(words, text, "risky", "cautious", "volatile", "dangerous")):
        plan.append(("get_market_regime", {}))

    if _has(words, text, "model", "models", "ml", "predict", "prediction", "predictions", "signal", "signals",
            "ranker", "ai pick", "ai picks", "model pick", "model picks"):
        plan.append(("get_model_signals", {"symbol": stock}))

    if _has(words, text, "position", "positions", "p&l", "pnl", "paper", "orders", "mock"):
        plan.append(("get_paper_portfolio", {}))

    if _has(words, text, "idea", "ideas", "recommend", "recommendation", "recommendations",
            "suggest", "pick", "picks", "best stocks", "should i buy", "what to buy"):
        kind = ("model" if _has(words, text, "model", "models", "ml") else
                "intraday" if _has(words, text, "intraday", "today") else
                "fno" if _has(words, text, "f&o", "fno", "option", "options") else "delivery")
        plan.append(("get_ideas", {"kind": kind}))

    for sc in screener_service.SCREENS:
        if sc.name.lower() in text or sc.id.replace("-", " ") in text:
            plan.append(("run_screener", {"screen_id": sc.id}))
            break
    else:
        if _has(words, text, "breakout", "breakouts", "52-week", "52 week"):
            plan.append(("run_screener", {"screen_id": "near-52w-high"}))
        elif _has(words, text, "oversold"):
            plan.append(("run_screener", {"screen_id": "oversold"}))
        elif _has(words, text, "overbought"):
            plan.append(("run_screener", {"screen_id": "overbought"}))

    if _has(words, text, "moving", "movers", "gainers", "gainer", "losers", "loser", "market today",
            "the market", "markets"):
        kind = "losers" if _has(words, text, "losers", "loser", "falling", "down") else "gainers"
        plan.append(("get_market_movers", {"kind": kind}))

    if symbols and not any(t in {"get_option_chain_summary", "run_backtest"} for t, _ in plan):
        for sym in symbols[:2]:
            plan.append(("get_quote", {"symbol": sym}))
    elif symbols and stock:
        plan.append(("get_quote", {"symbol": stock}))

    return plan[:4]


def _inr(value: Any) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return "an unavailable amount"


def _narrate_trading(tool: str, data: dict) -> list[str]:
    if data.get("available") is False:
        return [f"That could not be done: {data.get('reason', 'no reason given')}"]

    if tool == "get_quote":
        direction = "up" if data["change"] >= 0 else "down"
        return [f"{data['name']} is at {_inr(data['ltp'])}, {direction} {abs(data['change_pct']):.2f}% "
                f"on the day (open {_inr(data['open'])}, high {_inr(data['high'])}, low {_inr(data['low'])}). "
                + ("Prices are delayed about fifteen minutes." if data["source"] == "delayed"
                   else "Live price from Upstox.")]

    if tool == "get_market_movers":
        lines = []
        idx = {q["symbol"]: q for q in data["indices"]}
        if "NIFTY" in idx:
            n = idx["NIFTY"]
            lines.append(f"{data['market']['label']}. NIFTY is at {n['ltp']:,.2f} ({n['change_pct']:+.2f}%)"
                         + (f", SENSEX {idx['SENSEX']['ltp']:,.2f} ({idx['SENSEX']['change_pct']:+.2f}%)" if "SENSEX" in idx else "")
                         + ".")
        label = {"gainers": "Top gainers", "losers": "Top losers", "movers": "Biggest movers"}[data["kind"]]
        parts = ", ".join(f"{s['symbol']} {s['change_pct']:+.2f}%" for s in data["stocks"][:5])
        lines.append(f"{label} in the NIFTY 100: {parts}.")
        return lines

    if tool == "get_option_chain_summary":
        top_call = data["biggest_call_oi_addition"][0]
        top_put = data["biggest_put_oi_addition"][0]
        return [
            f"{data['underlying']} spot is {data['spot']:,.2f}; for the {data['expiry']} expiry the "
            f"put-call ratio is {data['pcr']:.2f} and max pain is {data['max_pain']:,}.",
            f"Support (highest put OI) is at {data['support']:,} and resistance (highest call OI) at "
            f"{data['resistance']:,}. The biggest call OI build-up is at {top_call['strike']:,} and the "
            f"biggest put build-up at {top_put['strike']:,}.",
            f"The ATM {data['atm_strike']:,} call is {_inr(data['atm_call_premium'])} and the put "
            f"{_inr(data['atm_put_premium'])}"
            + (f", at {data['atm_iv']:.2f}% implied volatility." if data.get("atm_iv") else "."),
            "Option data is live from your Upstox session.",
        ]

    if tool == "run_screener":
        names = ", ".join(r["symbol"] for r in data["results"][:6]) or "none"
        return [f"'{data['screen']['name']}' ({data['screen']['description'].rstrip('.')}) matches "
                f"{data['matches']} of {data['universe_size']} stocks: {names}."]

    if tool == "get_ideas":
        if not data["ideas"]:
            return ["No setups meet the rules right now."]
        lines = []
        for i in data["ideas"][:3]:
            if i["kind"] == "fno":
                legs = "; ".join(f"{l['action']} {l['strike']:,} {l['option_type']} at {_inr(l['premium'])}"
                                 for l in i["legs"])
                lines.append(f"{i['name']} ({i['bias']}): {legs}. Max profit {_inr(i['max_profit'])}, "
                             f"max loss {_inr(i['max_loss'])} per lot.")
            else:
                lines.append(f"{i['symbol']}: {i['side']} near {_inr(i['entry'])}, stop {_inr(i['stop_loss'])}, "
                             f"target {_inr(i['target'])} ({i['horizon'].lower()}). {i['rationale'][0]}.")
        lines.append(data["disclaimer"])
        return lines

    if tool == "get_paper_portfolio":
        lines = [f"Your paper account is worth {_inr(data['total_value'])}, "
                 f"{'up' if data['total_return'] >= 0 else 'down'} {_inr(abs(data['total_return']))} "
                 f"({abs(data['total_return_pct']):.2f}%) since it started, with {_inr(data['cash'])} in cash."]
        if data["holdings"]:
            lines.append(f"Holdings are worth {_inr(data['holdings_value'])} against {_inr(data['holdings_invested'])} "
                         f"invested; today's change is {_inr(data['day_change'])}.")
        if data["positions"]:
            lines.append(f"{len(data['positions'])} open position(s) with unrealised P&L of {_inr(data['positions_pnl'])}.")
        if not data["holdings"] and not data["positions"]:
            lines.append("There are no open holdings or positions yet.")
        return lines

    if tool == "run_backtest":
        st = data["strategy"]
        return [
            f"{st['name']} on {data['symbol']} from {data['start']} to {data['end']} returned "
            f"{data['total_return_pct']:.2f}% against {data['buy_and_hold_return_pct']:.2f}% for buy and hold, "
            f"with a worst drawdown of {abs(data['max_drawdown_pct'] or 0):.2f}%.",
            f"It made {data['trades']} trade(s)"
            + (f", winning {data['win_rate_pct']:.2f}% of them" if data["win_rate_pct"] is not None else "")
            + ". Costs are included; past results do not predict future ones.",
        ]

    if tool == "propose_paper_order":
        o = data["order"]
        return [f"Here is a paper order to {o['side']} {o['quantity']} {o['display_symbol']} at market, "
                f"about {_inr(data['estimated_value'])} at {_inr(data['ltp'])}. "
                "Review it and press Confirm to place it; nothing has been placed yet."]

    if tool == "get_model_signals":
        card = data["model"]
        oos = card.get("oos") or {}
        record = (f"Out of sample since {oos.get('first_test_year')}, its daily rank IC averaged "
                  f"{oos.get('mean_ic'):.3f} and it put {oos.get('hit_rate', 0) * 100:.1f}% of stocks on the right "
                  "side of the median." if oos.get("mean_ic") is not None and oos.get("hit_rate") is not None else "")
        if "picks" in data:
            names = ", ".join(f"{p['symbol']} (#{p['rank']})" for p in data["picks"][:5])
            lines = [f"As of {data['as_of']}, the swing ensemble's top-ranked stocks for the next "
                     f"{data['horizon_sessions']} sessions are {names}."]
            top = data["picks"][0] if data["picks"] else None
            if top and top.get("range_10d"):
                r = top["range_10d"]
                lines.append(f"For {top['symbol']} the 80% range is {r['low'] * 100:.1f}% to {r['high'] * 100:.1f}% "
                             "over that period: a ranking, not a promise.")
        elif not data.get("eligible"):
            return [f"{data['symbol']}: {data['reason']}"]
        else:
            r = data.get("range_10d") or {}
            drivers = "; ".join(f"{d['label']} at the {d['percentile']}th percentile {d['effect']} it"
                                for d in data["drivers"] if d.get("percentile") is not None)
            lines = [f"{data['symbol']} ranks {data['rank']} of {data['of']} on the swing ensemble as of "
                     f"{data['as_of']}."]
            if r.get("low") is not None:
                lines.append(f"Its 80% range for the next 10 sessions is {r['low'] * 100:.1f}% to "
                             f"{r['high'] * 100:.1f}%, with forecast volatility of {data['vol_annual'] * 100:.1f}% a year.")
            if drivers:
                lines.append(f"What drove the score: {drivers}.")
        if record:
            lines.append(record)
        lines.append(data["disclaimer"])
        return lines

    if tool == "get_market_regime":
        if not data.get("available"):
            return [data.get("reason", "The regime model is not available.")]
        p = data["probabilities"]
        return [f"The regime model reads the market as {data['state']} as of {data['as_of']} "
                f"(calm {p['calm'] * 100:.1f}%, normal {p['normal'] * 100:.1f}%, stress {p['stress'] * 100:.1f}%).",
                "It is built from NIFTY's return and volatility and India VIX, using data up to that day only. "
                "Historically it identified volatile periods well; it is a risk dial, not a market-timing signal."]

    if tool == "propose_swing_plan":
        names = ", ".join(f"{p['symbol']} ×{p['quantity']}" for p in data["positions"] if p["quantity"])
        return [f"A {data['profile']['name']} swing plan for {_inr(data['amount'])}: {names}, investing "
                f"{_inr(data['invested'])} and keeping {_inr(data['cash_reserve'])} in cash.",
                *data["notes"],
                "Review it and press Confirm to place these paper orders; nothing has been placed yet.",
                data["disclaimer"]]

    if tool == "plan_allocation":
        if data.get("available") is False:
            return [data["reason"]]
        lines = []
        if data["core"]:
            core = ", ".join(f"{c['symbol']} {c['weight'] * 100:.1f}% ({_inr(c['value'])})" for c in data["core"])
            lines.append(f"For {_inr(data['amount'])} over the long term, the core goes into {core}.")
        if data["picks"]:
            picks = "; ".join(f"{p['sector']}: {p['symbol']} ×{p['quantity']} at {_inr(p['price'])} ({_inr(p['cost'])})"
                              for p in data["picks"])
            lines.append(f"{'The satellite' if data['core'] else 'Split across sectors'}: {picks}.")
        lines.append(f"That invests {_inr(data['invested'])}, leaving {_inr(data['cash_left'])}.")
        lines += data["notes"]
        lines.append(data["disclaimer"])
        return lines

    if tool == "review_my_portfolio":
        if not data.get("available"):
            return [data.get("reason", "No holdings to review.")]
        ranked = [h for h in data["holdings"] if h.get("model")]
        lines = [f"Your portfolio has {len(data['holdings'])} holding(s); the swing models rank {len(ranked)} of them as of "
                 f"{data['as_of']}."]
        for h in ranked[:5]:
            m = h["model"]
            lines.append(f"{h['symbol']} ({h['weight'] * 100:.1f}% of the portfolio) ranks {m['rank']} of {m['of']}.")
        lines += [x["text"] for x in data["suggestions"][:5]]
        lines.append(data["note"])
        return lines

    if tool == "get_autopilot_status":
        st = data["settings"]
        if not st["enabled"] and not st["sleeve"]:
            return ["Autopilot is off. Say 'invest 50,000 in autopilot' or open the Autopilot page to start it."]
        lines = [f"Autopilot is {'on' if st['enabled'] else 'paused'} with a budget of {_inr(st['budget'])}; its "
                 f"paper sleeve is worth {_inr(data['sleeve_value'])} ({data['pnl_pct']:+.2f}%)."]
        if data["holdings"]:
            lines.append("It holds " + ", ".join(f"{h['symbol']} ×{h['quantity']}" for h in data["holdings"]) + ".")
        if data["runs"]:
            r = data["runs"][0]
            lines.append(f"Its last run, on {r['run_on']}, placed {len(r['orders'] or [])} order(s).")
        if data["next_run_in_sessions"] is not None:
            lines.append(f"Next rebalance in {data['next_run_in_sessions']} session(s).")
        return lines

    if tool == "propose_autopilot":
        names = ", ".join(f"{b['symbol']} ×{b['quantity']}" for b in data["basket"])
        return [f"An autopilot basket for {_inr(data['amount'])}: {names}, investing "
                f"{_inr(data['invested'])}. Press Confirm to place these paper orders.",
                data["disclaimer"]]
    return []


def _answer_with_templates(db: Session, user: User, question: str,
                           context: dict | None = None) -> dict:
    """Answer from the same tools, without a language model."""
    started = time.perf_counter()
    plan = _plan_trading(question, context)
    if not plan:
        plan = [(tool, {}) for tool in _select_tools(question)]

    tool_calls, tool_outputs, sentences = [], [], []
    for tool, args in plan:
        output = copilot_tools.run_tool(tool, db, user, args)
        tool_calls.append({"tool": tool, "arguments": args})
        tool_outputs.append(output)
        narrate = _narrate if tool in copilot_tools.PORTFOLIO_TOOL_NAMES else _narrate_trading
        try:
            sentences.extend(s for s in narrate(tool, output) if s)
        except (KeyError, TypeError, IndexError):
            sentences.append(f"The {tool.replace('_', ' ')} result could not be summarised.")

    if not sentences:
        sentences = [
            "There is not enough portfolio data yet to answer that. Import "
            "holdings or add a goal and ask again."
        ]

    return {
        "answer": "\n\n".join(sentences),
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "model": "deterministic-template-explainer",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "usage": None,
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def answer(db: Session, user: User, question: str, history: list[dict] | None = None,
           context: dict | None = None, memory: str | None = None) -> dict:
    """Answer a question about this user's portfolio."""
    history = history or []
    used_fallback = False
    fallback_reason = None

    if settings.copilot_enabled:
        try:
            result = _answer_with_llm(db, user, question, history, context, memory)
        except CopilotUnavailable as exc:
            log.warning("copilot fell back to templates: %s", exc)
            used_fallback, fallback_reason = True, str(exc)
            result = _answer_with_templates(db, user, question, context)
        except Exception as exc:
            log.exception("copilot LLM path failed")
            used_fallback = True
            fallback_reason = f"Unexpected error: {type(exc).__name__}"
            result = _answer_with_templates(db, user, question, context)
    else:
        used_fallback = True
        fallback_reason = "No language model is configured (set GEMINI_API_KEY or ANTHROPIC_API_KEY)."
        result = _answer_with_templates(db, user, question, context)

    grounding = check_groundedness(result["answer"], result["tool_outputs"])

    # An answer carrying figures the backend never produced is the exact
    # failure this design exists to prevent, so it is flagged rather than
    # shipped silently.
    if not grounding["is_grounded"]:
        log.warning(
            "copilot answer contained %d unverified number(s): %s",
            len(grounding["unverified_numbers"]), grounding["unverified_numbers"],
        )

    return {
        "answer": result["answer"],
        "model": result["model"],
        "used_fallback": used_fallback,
        "fallback_reason": fallback_reason,
        "tools_called": [c["tool"] for c in result["tool_calls"]],
        "tool_calls": result["tool_calls"],
        "tool_outputs": result["tool_outputs"],
        "grounding": grounding,
        "latency_ms": result["latency_ms"],
        "usage": result["usage"],
        "disclaimer": DISCLAIMER,
    }
