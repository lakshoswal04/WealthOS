"""Converting computed floats into values that survive JSON.

Every analytics function in this package returns ``NaN`` rather than raising
when an input is too thin to measure — that convention is deliberate and
documented. ``NaN`` is not, however, a JSON value, and the three consumers of
these results disagree about what to do with one:

* ``json.dumps`` writes a bare ``NaN`` token, which is valid JavaScript but
  invalid JSON. ``ml/pipelines/common.py`` writes every report this way.
* Starlette's ``JSONResponse`` sets ``allow_nan=False`` and raises, turning a
  thin portfolio into a 500.
* Pydantic quietly serialises it to ``null``.

So the same unmeasurable component is a crash, a corrupt file or a clean
``null`` depending only on which code path reaches it first. Converting at
the boundary — once, here — removes the disagreement.
"""

from __future__ import annotations

import math

__all__ = ["json_safe", "round_or_none"]


def json_safe(value: object) -> object:
    """Return ``value`` unchanged, or ``None`` if it is NaN or infinite.

    Non-numeric values pass straight through, so this is safe to apply to a
    mixed payload without inspecting each field's type first.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return None if not math.isfinite(float(value)) else value


def round_or_none(value: object, digits: int) -> object:
    """``round(value, digits)``, but ``None`` where the result cannot be JSON.

    ``round(float("nan"), 1)`` returns ``nan`` rather than raising, so a
    rounded field is exactly as unsafe as an unrounded one. This is the
    rounding call to reach for in an ``as_dict``.
    """
    safe = json_safe(value)
    if safe is None or isinstance(safe, bool) or not isinstance(safe, (int, float)):
        return safe
    return round(float(safe), digits)
