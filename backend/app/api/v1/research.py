"""Training evidence and data-quality reports.

Every pipeline stage writes what it found to ``ml/reports/``. Those files are
the project's evidence base — how each model was selected, how it scored, and
what the data pipeline had to repair — and until now they were visible only
to someone reading JSON on disk.

This endpoint serves them to the Model Lab and Data Quality pages. They carry
no user data: they describe the models and the market data, both of which are
identical for every account. It therefore needs no authentication, and
deliberately reads nothing from the database.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings

log = logging.getLogger("wealthos.research")

router = APIRouter(prefix="/research", tags=["research"])

# Reports grouped by the page that consumes them. Listing them explicitly
# rather than globbing the directory means a stray file cannot be served.
MODEL_REPORTS = ("clustering", "anomaly_detection", "copilot_groundedness",
                 "forecast_1m", "forecast_3m", "forecast_6m", "forecast_12m",
                 "features", "cluster_map")
DATA_REPORTS = ("ingest_quality", "price_build", "adjustment_impact",
                "external_fetch", "big_sharks_priors", "cohort", "database_seed")

ALL_REPORTS = MODEL_REPORTS + DATA_REPORTS

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def _reports_dir() -> Path:
    return settings.project_root / "ml" / "reports"


def _load(name: str) -> dict:
    """Read one report, or describe why it is unavailable.

    A missing report disables one panel rather than failing the page, which
    matches how the model endpoints already degrade.
    """
    if name in _cache:
        return _cache[name]

    path = _reports_dir() / f"{name}.json"
    if not path.exists():
        return {
            "available": False,
            "reason": (
                f"{name}.json has not been generated yet. Run the matching "
                "pipeline stage to produce it."
            ),
        }

    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("report %s could not be read: %s", name, exc)
        return {"available": False, "reason": f"{name}.json could not be read."}

    payload["available"] = True
    with _lock:
        _cache[name] = payload
    return payload


@router.get("/reports")
def all_reports() -> dict:
    """Every training and data-quality report, grouped by page."""
    return {
        "models": {name: _load(name) for name in MODEL_REPORTS},
        "data": {name: _load(name) for name in DATA_REPORTS},
    }


@router.get("/reports/{name}")
def one_report(name: str) -> dict:
    """A single report by name."""
    if name not in ALL_REPORTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown report. Available: {', '.join(sorted(ALL_REPORTS))}",
        )
    return _load(name)


@router.post("/reports/refresh", include_in_schema=False)
def refresh() -> dict:
    """Drop the cache, so a re-run of the pipelines is picked up."""
    with _lock:
        _cache.clear()
    return {"cleared": True}
