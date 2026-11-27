#!/usr/bin/env python
"""Generate the Health Score v1-vs-v2 evidence report.

Writes ``ml/reports/health_score_v1_vs_v2.json``. Every figure in the report
comes from running both implementations over ``wealthos_core.scenarios``, so
the final write-up quotes a file rather than a memory.

Run: python -m scripts.health_score_comparison
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from wealthos_core.health import (
    COMPONENT_WEIGHTS,
    DRAWDOWN_TOLERANCE,
    compute_health_score as v1,
    sensitivity_analysis,
)
from wealthos_core.health_v2 import (
    COMPONENT_WEIGHTS_V2,
    DRAWDOWN_BREACH_MULTIPLE,
    HOLDINGS_CURVE,
    CASH_BUFFER_TARGET,
    compute_health_score_v2 as v2,
)
from wealthos_core.scenarios import QUALITY_TIERS, SCENARIOS, UNSCORABLE, scenario

REPORT = Path(__file__).resolve().parents[1] / "ml" / "reports" / "health_score_v1_vs_v2.json"
SCORABLE = [s for s in SCENARIOS if s.name not in UNSCORABLE]


def _n(value: float) -> float | None:
    return None if value is None or not math.isfinite(float(value)) else round(float(value), 4)


def _component(result, name):
    return next(c for c in result.components if c.name == name)


def _per_scenario() -> list[dict]:
    rows = []
    for item in SCENARIOS:
        a, b = v1(item.inputs), v2(item.inputs)
        rows.append({
            "scenario": item.name,
            "description": item.description,
            "expectation": item.expectation,
            "tier": next((t for t, m in QUALITY_TIERS if item.name in m), "unscorable"),
            "v1_total": _n(a.total),
            "v2_total": _n(b.total),
            "difference": (
                None if math.isnan(a.total) or math.isnan(b.total)
                else round(b.total - a.total, 2)
            ),
            "missing_inputs": a.missing_inputs,
            "v1_components": {c.name: _n(c.score) for c in a.components},
            "v2_components": {c.name: _n(c.score) for c in b.components},
            "v1_contribution_sum": _n(
                sum(c.contribution for c in a.components if math.isfinite(c.contribution))
            ),
            "v2_contribution_sum": _n(
                sum(c.contribution for c in b.components if math.isfinite(c.contribution))
            ),
        })
    return rows


def _component_discrimination() -> dict:
    out: dict[str, dict] = {}
    for label, compute in (("v1", v1), ("v2", v2)):
        acc: dict[str, list[float]] = {}
        for item in SCORABLE:
            for component in compute(item.inputs).components:
                if not math.isnan(component.score):
                    acc.setdefault(component.name, []).append(component.score)
        out[label] = {
            name: {
                "range": _n(max(values) - min(values)),
                "std_dev": _n(float(np.std(values))),
                "min": _n(min(values)),
                "max": _n(max(values)),
                "cannot_discriminate": bool(max(values) - min(values) < 10.0),
            }
            for name, values in acc.items()
        }
    return out


def _double_count_probe() -> dict:
    """Same breadth, different weight dispersion. Diversification must not move."""
    base = scenario("textbook_balanced").inputs
    even = replace(base, hhi_normalized=0.04, top_1_weight=0.08, top_5_weight=0.34)
    uneven = replace(base, hhi_normalized=0.45, top_1_weight=0.44, top_5_weight=0.88)

    out = {
        "method": (
            "Two portfolios with identical holdings, sectors, asset classes and "
            "pairwise correlation, differing only in weight dispersion. Any "
            "movement in diversification is work concentration already does."
        )
    }
    for label, compute in (("v1", v1), ("v2", v2)):
        d = abs(_component(compute(uneven), "diversification").score
                - _component(compute(even), "diversification").score)
        c = abs(_component(compute(uneven), "concentration").score
                - _component(compute(even), "concentration").score)
        out[label] = {
            "diversification_moved": _n(d),
            "concentration_moved": _n(c),
            "double_counted": bool(d > 0.01),
        }
    return out


def _liquidity_probe() -> dict:
    buffered = scenario("textbook_balanced").inputs
    unbuffered = scenario("diversified_no_buffer").inputs
    return {
        "method": (
            "The same portfolio with and without an 18% cash-and-debt buffer. "
            "Having no buffer means meeting an unexpected need by selling "
            "growth assets, possibly after a fall."
        ),
        "v1_total_gap": _n(v1(buffered).total - v1(unbuffered).total),
        "v2_total_gap": _n(v2(buffered).total - v2(unbuffered).total),
        "buffer_target": CASH_BUFFER_TARGET,
    }


def _drawdown_probe() -> dict:
    at_tolerance = replace(
        scenario("textbook_balanced").inputs,
        risk_tolerance="conservative", annualized_volatility=0.07, max_drawdown=-0.12,
    )
    return {
        "method": (
            "A conservative investor whose portfolio fell exactly 12%, the "
            "drawdown that profile declares it tolerates."
        ),
        "tolerance": DRAWDOWN_TOLERANCE["conservative"],
        "v1_drawdown_subscore": _n(
            _component(v1(at_tolerance), "risk").inputs["subscores"]["drawdown"]
        ),
        "v2_drawdown_subscore": _n(
            _component(v2(at_tolerance), "risk").inputs["subscores"]["drawdown"]
        ),
        "breach_multiple": DRAWDOWN_BREACH_MULTIPLE,
        "finding": (
            "v1 scored the investor's own stated limit at half marks. A "
            "tolerance is a constraint, not a target: v2 awards full marks "
            "inside it and decays to zero at twice it."
        ),
    }


def _saturation() -> dict:
    out: dict[str, dict] = {}
    for label, compute in (("v1", v1), ("v2", v2)):
        total = saturated = 0
        by_input: dict[str, int] = {}
        for item in SCORABLE:
            for row in sensitivity_analysis(item.inputs, compute=compute):
                total += 1
                if row["saturated"]:
                    saturated += 1
                    by_input[row["input"]] = by_input.get(row["input"], 0) + 1
        out[label] = {
            "nudges": total,
            "saturated": saturated,
            "saturated_share": _n(saturated / total) if total else None,
            "by_input": dict(sorted(by_input.items(), key=lambda kv: -kv[1])),
        }
    out["interpretation"] = (
        "v2 shows MORE saturated input nudges than v1, and that is the "
        "intended behaviour, not a regression. Its drawdown score is flat "
        "inside the investor's tolerance (the constraint is met) and flat "
        "past twice it (the constraint is destroyed); only the band between "
        "carries information. The measure that matters is whether a component "
        "can discriminate at all -- see component_discrimination, where v1's "
        "liquidity is the only saturated component in either version."
    )
    return out


def build() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Evidence for the Health Score rework. Both methodologies use "
            "identical inputs and identical component weights, so every "
            "difference below is attributable to a measurement change rather "
            "than to re-weighting."
        ),
        "weights": {
            "v1": COMPONENT_WEIGHTS,
            "v2": COMPONENT_WEIGHTS_V2,
            "identical": COMPONENT_WEIGHTS == COMPONENT_WEIGHTS_V2,
            "rationale": (
                "Deliberately unchanged. Fixing a measure is a better answer "
                "than re-weighting around a broken one, and holding the "
                "weights fixed is what makes the comparison interpretable."
            ),
        },
        "v2_parameters": {
            "holdings_curve": [list(k) for k in HOLDINGS_CURVE],
            "cash_buffer_target": CASH_BUFFER_TARGET,
            "drawdown_breach_multiple": DRAWDOWN_BREACH_MULTIPLE,
        },
        "scenarios": _per_scenario(),
        "tiers": {name: list(members) for name, members in QUALITY_TIERS},
        "component_discrimination": _component_discrimination(),
        "probe_double_counting": _double_count_probe(),
        "probe_liquidity": _liquidity_probe(),
        "probe_drawdown_at_tolerance": _drawdown_probe(),
        "sensitivity": _saturation(),
    }


if __name__ == "__main__":
    report = build()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(f"wrote {REPORT}")
    print(f"  scenarios: {len(report['scenarios'])}")
    for label in ("v1", "v2"):
        liquidity = report["component_discrimination"][label]["liquidity"]
        print(f"  {label} liquidity range: {liquidity['range']}  "
              f"cannot_discriminate={liquidity['cannot_discriminate']}")
