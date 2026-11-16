"""The AI Wealth Copilot.

The Copilot is an explanation layer, not a calculator. It selects which
backend measurements to fetch, then narrates them. Every number it reports
is checked against the tool outputs before the answer is returned, so the
grounding claim is enforced rather than merely intended.

Two execution paths:

  LLM path       Anthropic tool-calling, used when an API key is configured.
  Fallback path  A deterministic template explainer over the same tools,
                 used when no key is present. The platform stays fully
                 usable without an external dependency, which is what the
                 PRD's reliability requirement asks for.
"""

from __future__ import annotations

import json
import logging
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
You are the WealthOS Wealth Copilot. You explain a specific investor's \
portfolio using measurements computed by the WealthOS backend.

How you must work:
- Call tools to obtain every figure. You have no other source of information \
about this portfolio.
- Never calculate, estimate, infer or recall a financial number yourself. If \
a figure you want is not in a tool result, say it is not available rather \
than producing one.
- Quote figures as the tools report them, rounding at most to one or two \
decimal places.
- If a tool reports available=false, tell the user that measurement could not \
be computed and why.
- Report the assumptions that come with a figure when they matter, especially \
the risk-free rate behind a Sharpe ratio and the fact that forecasts are \
projections rather than predictions.

What you must not do:
- Do not recommend buying, selling or holding any security. You are an \
analytics tool, not a regulated financial adviser. You may explain what a \
measurement means and which part of the dashboard shows more.
- Do not describe a forecast as what will happen. Forecasts are projections \
under stated assumptions and can be wrong.
- Do not invent history, news, prices or events.

Style: direct and plain. Lead with the answer. Two to four short paragraphs \
at most, and use a short list when comparing several figures. Write amounts \
in rupees as the tools give them."""

DISCLAIMER = (
    "WealthOS is an academic research prototype. It explains computed "
    "portfolio metrics and does not provide investment advice."
)


# --------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------

def _answer_with_llm(db: Session, user: User, question: str, history: list[dict]) -> dict:
    """Run the tool-calling loop against the Anthropic API."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    messages: list[dict[str, Any]] = []
    for turn in history[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_outputs: list[dict] = []
    tool_calls: list[dict] = []
    started = time.perf_counter()

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.beta.messages.create(
                model=settings.copilot_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=copilot_tools.TOOL_SCHEMAS,
                # Forced tool choice is rejected on current models; the system
                # prompt does the steering instead.
                tool_choice={"type": "auto"},
                # Narrating structured values needs little deliberation.
                output_config={"effort": "low"},
                messages=messages,
                # A safety decline should fall back rather than dead-end the
                # user's question.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            raise CopilotUnavailable(
                f"The language model returned an error ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise CopilotUnavailable("The language model could not be reached.") from exc

        if response.stop_reason == "refusal":
            raise CopilotUnavailable(
                "The language model declined to answer this question."
            )

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "answer": text.strip(),
                "tool_calls": tool_calls,
                "tool_outputs": tool_outputs,
                "model": response.model,
                "latency_ms": round(elapsed_ms, 1),
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }

        messages.append({"role": "assistant", "content": response.content})

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            # Tool inputs are parsed JSON from the SDK; never string-matched.
            arguments = dict(block.input or {})
            output = copilot_tools.run_tool(block.name, db, user, arguments)
            tool_calls.append({"tool": block.name, "arguments": arguments})
            tool_outputs.append(output)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(output, default=str),
            })
        messages.append({"role": "user", "content": results})

    raise CopilotUnavailable(
        f"The assistant did not finish within {MAX_TOOL_ROUNDS} tool rounds."
    )


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


def _answer_with_templates(db: Session, user: User, question: str) -> dict:
    """Answer from the same tools, without a language model."""
    started = time.perf_counter()
    selected = _select_tools(question)

    tool_calls, tool_outputs, sentences = [], [], []
    for tool in selected:
        output = copilot_tools.run_tool(tool, db, user, {})
        tool_calls.append({"tool": tool, "arguments": {}})
        tool_outputs.append(output)
        sentences.extend(s for s in _narrate(tool, output) if s)

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

def answer(db: Session, user: User, question: str, history: list[dict] | None = None) -> dict:
    """Answer a question about this user's portfolio."""
    history = history or []
    used_fallback = False
    fallback_reason = None

    if settings.copilot_enabled:
        try:
            result = _answer_with_llm(db, user, question, history)
        except CopilotUnavailable as exc:
            log.warning("copilot fell back to templates: %s", exc)
            used_fallback, fallback_reason = True, str(exc)
            result = _answer_with_templates(db, user, question)
        except Exception as exc:
            log.exception("copilot LLM path failed")
            used_fallback = True
            fallback_reason = f"Unexpected error: {type(exc).__name__}"
            result = _answer_with_templates(db, user, question)
    else:
        used_fallback = True
        fallback_reason = "No ANTHROPIC_API_KEY is configured."
        result = _answer_with_templates(db, user, question)

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
        "tool_outputs": result["tool_outputs"],
        "grounding": grounding,
        "latency_ms": result["latency_ms"],
        "usage": result["usage"],
        "disclaimer": DISCLAIMER,
    }
