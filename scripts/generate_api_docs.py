#!/usr/bin/env python
"""Regenerate docs/api.md from the live route table.

The previous file was written by hand from a route listing and had drifted:
several endpoints had no description, and the twelve added in Phases 5 and 6
were absent entirely. A reference that has to be remembered is a reference
that goes stale, so this reads the router.

Public paths come from the same declaration the route audit uses
(`backend/tests/test_route_isolation.PUBLIC_PATHS`), so the document and the
test cannot disagree about which endpoints need a token.

Run: python -m scripts.generate_api_docs
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from app.main import app  # noqa: E402
from test_route_isolation import PUBLIC_PATHS  # noqa: E402

OUT = ROOT / "docs" / "api.md"

SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
METHOD_ORDER = {"GET": 0, "POST": 1, "PATCH": 2, "PUT": 3, "DELETE": 4}


def _summary(route) -> str:
    """One line for the table: the endpoint's own first docstring line."""
    doc = (getattr(route, "description", None) or "").strip()
    if not doc:
        return ""
    first = doc.split("\n\n")[0].replace("\n", " ").strip()
    return " ".join(first.split())


def main() -> None:
    by_tag: dict[str, list] = defaultdict(list)
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path or path in SKIP_PATHS:
            continue
        tags = getattr(route, "tags", None) or ["general"]
        for method in methods - {"HEAD", "OPTIONS"}:
            by_tag[str(tags[0])].append((path, method, _summary(route)))

    total = sum(len(v) for v in by_tag.values())
    public = sorted(p for p in PUBLIC_PATHS if p not in SKIP_PATHS)

    lines = [
        "# API reference",
        "",
        "Generated from the live route table by "
        "`python -m scripts.generate_api_docs`. Do not edit by hand: the "
        "previous version was written from a route listing and had drifted, "
        "missing twelve endpoints and leaving several without a description.",
        "",
        "Base URL `http://localhost:8010`, prefix `/api/v1`. Interactive docs "
        "at `/docs`.",
        "",
        f"**{total} endpoints**, of which {len(public)} are public. Every "
        "other endpoint requires `Authorization: Bearer <token>` and is "
        "scoped to the signed-in user; "
        "`backend/tests/test_route_isolation.py` enumerates this same route "
        "table and asserts both properties, so this list cannot drift from "
        "what is enforced.",
        "",
        "## Public endpoints",
        "",
        "Each is public for a stated reason, because \"it was already public\" "
        "is how an endpoint quietly stops being protected.",
        "",
        "| Path | Why it needs no token |",
        "|---|---|",
    ]
    for path in public:
        lines.append(f"| `{path}` | {PUBLIC_PATHS[path]} |")

    for tag in sorted(by_tag):
        rows = sorted(
            set(by_tag[tag]),
            key=lambda r: (r[0], METHOD_ORDER.get(r[1], 9)),
        )
        lines += ["", f"## {tag}", "", "| Method | Path | Description |", "|---|---|---|"]
        for path, method, summary in rows:
            lines.append(f"| `{method}` | `{path}` | {summary} |")

    lines.append("")
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}: {total} endpoints across {len(by_tag)} tags")
    for tag in sorted(by_tag):
        print(f"  {tag:18} {len(set(by_tag[tag]))}")


if __name__ == "__main__":
    main()
