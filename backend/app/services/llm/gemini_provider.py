"""Gemini (Google GenAI SDK) tool-calling loop.

Uses ``client.models.generate_content`` with automatic function calling
switched off, so every tool call goes through the backend's own dispatcher
(and its grounding record) exactly as with Claude.

The model's turn is appended back to the conversation unchanged on every
round: Gemini 3 models attach thought signatures to function-call parts and
reject a follow-up request that drops them.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings

from . import Dispatch, ProviderUnavailable

_TYPES = {"string": "STRING", "number": "NUMBER", "integer": "INTEGER", "boolean": "BOOLEAN",
          "array": "ARRAY", "object": "OBJECT"}
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


def to_gemini_schema(schema: dict) -> dict:
    """JSON Schema (as written for Claude's strict tools) to Gemini's Schema dict.

    * ``"type": ["string", "null"]`` becomes ``"type": "STRING", "nullable": True``.
    * ``None`` is removed from ``enum`` (nullability already says it).
    * Keys Gemini's Schema does not take (``additionalProperties``, ``strict``)
      are dropped.
    """
    out: dict[str, Any] = {}
    t = schema.get("type")
    nullable = False
    if isinstance(t, list):
        nullable = "null" in t
        t = next((x for x in t if x != "null"), "string")
    if t:
        out["type"] = _TYPES.get(t, "STRING")
    if nullable:
        out["nullable"] = True
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        if len(values) < len(schema["enum"]):
            out["nullable"] = True
        # Gemini enums are strings.
        out["enum"] = [str(v) for v in values]
        out.setdefault("type", "STRING")
    if "properties" in schema:
        out["properties"] = {k: to_gemini_schema(v) for k, v in schema["properties"].items()}
        if schema.get("required"):
            out["required"] = list(schema["required"])
    if "items" in schema:
        out["items"] = to_gemini_schema(schema["items"])
    for key in ("minimum", "maximum"):
        if key in schema:
            out[key] = schema[key]
    return out


def declarations(tools: list[dict]) -> list[dict]:
    decls = []
    for tool in tools:
        params = tool.get("input_schema") or {"type": "object", "properties": {}}
        decl = {"name": tool["name"], "description": tool.get("description", "")}
        if params.get("properties"):
            decl["parameters"] = to_gemini_schema(params)
        decls.append(decl)
    return decls


def _coerce(arguments: dict, schema: dict) -> dict:
    """Restore nulls and numbers the way the tools expect them.

    Gemini may omit an optional (nullable) argument instead of sending null,
    and sends enum values as strings; the tool functions take None defaults.
    """
    out = dict(arguments)
    for name in (schema or {}).get("properties", {}):
        out.setdefault(name, None)
    return out


def run(system: str, history: list[dict[str, Any]], question: str, tools: list[dict],
        dispatch: Dispatch, max_rounds: int, max_tokens: int) -> dict:
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=settings.gemini_api_key)
    schemas = {t["name"]: t.get("input_schema") or {} for t in tools}
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(function_declarations=declarations(tools))],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
        max_output_tokens=max_tokens,
    )
    contents: list[Any] = []
    for turn in history:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=str(turn["content"]))]))
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    tool_outputs: list[dict] = []
    tool_calls: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    started = time.perf_counter()

    for _ in range(max_rounds):
        try:
            response = client.models.generate_content(model=settings.gemini_model, contents=contents, config=config)
        except errors.ClientError as exc:
            raise ProviderUnavailable(f"Gemini rejected the request ({exc.code}): {exc.message}") from exc
        except errors.APIError as exc:
            raise ProviderUnavailable(f"Gemini returned an error ({exc.code}).") from exc
        except Exception as exc:  # network and transport failures
            raise ProviderUnavailable(f"Gemini could not be reached ({type(exc).__name__}).") from exc

        meta = response.usage_metadata
        if meta is not None:
            usage["input_tokens"] += meta.prompt_token_count or 0
            usage["output_tokens"] += meta.candidates_token_count or 0

        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderUnavailable("Gemini declined to answer this question.")
        if not response.candidates:
            raise ProviderUnavailable("Gemini returned no answer.")
        candidate = response.candidates[0]
        reason = getattr(candidate.finish_reason, "name", str(candidate.finish_reason or ""))
        if reason in _BLOCKED:
            raise ProviderUnavailable("Gemini declined to answer this question.")

        calls = response.function_calls or []
        if not calls:
            text = "".join(p.text for p in (candidate.content.parts if candidate.content else []) or []
                           if getattr(p, "text", None) and not getattr(p, "thought", False))
            if not text.strip():
                raise ProviderUnavailable(f"Gemini returned an empty answer ({reason or 'no reason'}).")
            return {
                "answer": text.strip(),
                "tool_calls": tool_calls,
                "tool_outputs": tool_outputs,
                "model": getattr(response, "model_version", None) or settings.gemini_model,
                "provider": "gemini",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "usage": usage,
            }

        # The model's turn goes back unchanged (thought signatures included).
        contents.append(candidate.content)
        parts = []
        for call in calls:
            arguments = _coerce(dict(call.args or {}), schemas.get(call.name, {}))
            output = dispatch(call.name, arguments)
            tool_calls.append({"tool": call.name, "arguments": arguments})
            tool_outputs.append(output)
            payload = json.loads(json.dumps(output, default=str))
            # The call id pairs each result with its call when several run at once.
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=call.id, name=call.name,
                response=payload if isinstance(payload, dict) else {"result": payload})))
        contents.append(types.Content(role="user", parts=parts))

    raise ProviderUnavailable(f"The assistant did not finish within {max_rounds} tool rounds.")
