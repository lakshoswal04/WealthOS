"""Claude (Anthropic Messages API) tool-calling loop."""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings

from . import Dispatch, ProviderUnavailable


def run(system: str, history: list[dict[str, Any]], question: str, tools: list[dict],
        dispatch: Dispatch, max_rounds: int, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict[str, Any]] = [dict(t) for t in history]
    messages.append({"role": "user", "content": question})
    tool_outputs: list[dict] = []
    tool_calls: list[dict] = []
    started = time.perf_counter()

    for _ in range(max_rounds):
        try:
            response = client.beta.messages.create(
                model=settings.copilot_model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
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
            raise ProviderUnavailable(f"The language model returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailable("The language model could not be reached.") from exc

        if response.stop_reason == "refusal":
            raise ProviderUnavailable("The language model declined to answer this question.")
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return {
                "answer": text.strip(),
                "tool_calls": tool_calls,
                "tool_outputs": tool_outputs,
                "model": response.model,
                "provider": "anthropic",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "usage": {"input_tokens": response.usage.input_tokens,
                          "output_tokens": response.usage.output_tokens},
            }

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            # Tool inputs are parsed JSON from the SDK; never string-matched.
            arguments = dict(block.input or {})
            output = dispatch(block.name, arguments)
            tool_calls.append({"tool": block.name, "arguments": arguments})
            tool_outputs.append(output)
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(output, default=str)})
        messages.append({"role": "user", "content": results})

    raise ProviderUnavailable(f"The assistant did not finish within {max_rounds} tool rounds.")
