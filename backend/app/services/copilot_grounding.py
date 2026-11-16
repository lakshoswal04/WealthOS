"""Verifying that the Copilot's numbers came from the backend.

The platform's central claim is that the Copilot explains computed values
rather than inventing them. This module turns that claim into something
measurable: every number in a generated answer is extracted and checked
against the tool outputs that produced it.

Numbers that cannot be matched are reported. The PRD asks for a
"groundedness / factual consistency" metric for the Copilot, and this is it.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["extract_numbers", "collect_tool_numbers", "check_groundedness"]

# Matches 12, 12.5, 1,234.56, -3.2 and the like.
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")

# Small WHOLE numbers are nearly always prose ("the three components",
# "top 5", "over 12 months") rather than claims about the portfolio.
# Only integers are skipped: a ratio of 0.589 or a volatility of 11.08 is
# exactly the kind of figure that must be checked, and an earlier version
# that skipped everything below 13 waved through a fabricated Sharpe ratio.
IGNORE_SMALL_INTEGERS_UPTO = 12
IGNORE_EXACT = {0.0, 1.0, 100.0}

# Years appear constantly in dates and horizons.
YEAR_RANGE = (1990, 2100)

# A figure is grounded if it matches a tool value within this relative
# tolerance, which allows for reasonable rounding in prose.
RELATIVE_TOLERANCE = 0.02

# An absolute tolerance is only meaningful for figures large enough that
# rounding to the nearest whole unit is normal, such as a rupee amount.
# Applying it to every number lets a fabricated 2.85 match a real 2.5, which
# is how an earlier version passed an invented beta.
ABSOLUTE_TOLERANCE = 0.51
ABSOLUTE_TOLERANCE_APPLIES_ABOVE = 100.0


def _parse(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    """Every numeric claim in a block of prose worth checking."""
    found: list[float] = []
    for match in NUMBER_PATTERN.finditer(text or ""):
        value = _parse(match.group())
        if value is None:
            continue
        if value in IGNORE_EXACT:
            continue
        if value.is_integer():
            if abs(value) <= IGNORE_SMALL_INTEGERS_UPTO:
                continue
            if YEAR_RANGE[0] <= value <= YEAR_RANGE[1]:
                continue
        found.append(value)
    return found


def collect_tool_numbers(payload: Any, into: set[float] | None = None) -> set[float]:
    """Every number a tool returned, at any depth.

    Percentages are recorded in both forms. A tool reporting
    ``volatility_pct: 11.08`` may legitimately be narrated as "11.08%" or as
    "0.1108", and both should count as grounded.
    """
    values: set[float] = into if into is not None else set()

    if isinstance(payload, bool):
        return values
    if isinstance(payload, (int, float)):
        number = float(payload)
        values.add(number)
        values.add(round(number * 100, 6))
        values.add(round(number / 100, 6))
        # A negative figure is routinely narrated as a positive magnitude: a
        # max drawdown stored as -27.14 is written as "fell 27.14%". Without
        # the absolute value every drawdown and loss reads as unverified,
        # which buries real failures under false alarms.
        values.add(abs(number))
        values.add(round(abs(number) * 100, 6))
        values.add(round(abs(number) / 100, 6))
        return values
    if isinstance(payload, str):
        for match in NUMBER_PATTERN.finditer(payload):
            parsed = _parse(match.group())
            if parsed is not None:
                values.add(parsed)
        return values
    if isinstance(payload, dict):
        for item in payload.values():
            collect_tool_numbers(item, values)
        return values
    if isinstance(payload, (list, tuple)):
        for item in payload:
            collect_tool_numbers(item, values)
    return values


def _matches(claim: float, known: set[float]) -> bool:
    for value in known:
        scale = max(abs(claim), abs(value))
        if scale >= ABSOLUTE_TOLERANCE_APPLIES_ABOVE and abs(claim - value) <= ABSOLUTE_TOLERANCE:
            return True
        if scale > 0 and abs(claim - value) / scale <= RELATIVE_TOLERANCE:
            return True
    return False


def check_groundedness(answer: str, tool_outputs: list[dict]) -> dict:
    """Check every number in the answer against the tool outputs.

    Returns the rate, the unverified figures, and a verdict the API can act
    on. A low rate means the model stated figures the backend never
    produced, which is the failure mode the whole tool-calling design exists
    to prevent.
    """
    claims = extract_numbers(answer)
    known: set[float] = set()
    for output in tool_outputs:
        collect_tool_numbers(output, known)

    # Deliberately no derived values. An earlier version also accepted any
    # pairwise sum or difference of tool outputs, on the theory that a reader
    # might compute a total. With a few dozen tool values that generates
    # hundreds of accepted numbers and the check passes almost anything --
    # it waved through a fabricated 47.3% return. If the model needs a total,
    # it should take it from a tool that computes one.
    unverified = [c for c in claims if not _matches(c, known)]
    verified = len(claims) - len(unverified)
    rate = (verified / len(claims)) if claims else 1.0

    return {
        "numbers_checked": len(claims),
        "numbers_verified": verified,
        "groundedness_rate": round(rate, 4),
        "unverified_numbers": sorted(set(unverified))[:20],
        "is_grounded": not unverified,
        "tool_values_available": len(known),
    }
