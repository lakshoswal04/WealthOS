"""Language-model providers behind one tool-calling interface.

The Copilot needs exactly one thing from a model: given a system prompt, the
conversation, and the backend tools, decide which tools to call, read their
outputs, and write an answer. Both providers implement that as
``run(...)``; the rest of the app never imports a vendor SDK.

``settings.llm_provider_active`` picks the provider (Gemini when
``GEMINI_API_KEY`` is set, else Claude when ``ANTHROPIC_API_KEY`` is set).
With neither, callers use the deterministic template explainer instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import settings

__all__ = ["ProviderUnavailable", "Dispatch", "run", "active", "model"]

Dispatch = Callable[[str, dict], dict]


class ProviderUnavailable(Exception):
    """The model could not produce an answer (no key, an API error, a refusal)."""


def active() -> str | None:
    return settings.llm_provider_active


def model() -> str | None:
    return settings.llm_model


def run(system: str, history: list[dict[str, Any]], question: str, tools: list[dict],
        dispatch: Dispatch, max_rounds: int = 6, max_tokens: int = 8192) -> dict:
    """Answer ``question`` with tool calls; returns answer, tool_calls, tool_outputs, model, usage.

    ``history``: prior turns as ``{"role": "user" | "assistant", "content": str}``.
    ``tools``: Anthropic-style definitions (name, description, input_schema).
    ``dispatch(name, arguments)``: runs one tool and returns its JSON-able output.
    """
    provider = active()
    if provider == "gemini":
        from .gemini_provider import run as run_gemini

        return run_gemini(system, history, question, tools, dispatch, max_rounds, max_tokens)
    if provider == "anthropic":
        from .anthropic_provider import run as run_anthropic

        return run_anthropic(system, history, question, tools, dispatch, max_rounds, max_tokens)
    raise ProviderUnavailable("No language model is configured.")
