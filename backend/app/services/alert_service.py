"""Decision support: what was found, why it matters, and the evidence.

The `alerts` table was already designed for this and never written to. Its
columns are `title`, `message`, `metric_value`, `threshold`, a `details`
JSONB for evidence, a `severity`, and an `alert_type` enum whose six members
-- concentration, anomaly, drawdown, goal_off_track, allocation_drift,
health_score_drop -- are exactly the six categories the requirement asks for.
Its docstring already states the constraint that governs everything here:

    Alerts describe what was measured and why it was flagged. They never
    recommend a trade: the platform is an analytics tool, not a regulated
    advisory service.

So this module implements a write path rather than inventing a design. Each
rule is a pure function over measurements the existing services already
produce, returning a candidate or nothing. Nothing is phrased as advice: an
alert says "your largest position is 38% of the portfolio, and a single
company's results therefore move more than a third of your wealth", never
"reduce it". The distinction is not cosmetic -- the second sentence is
investment advice and this platform is not licensed to give it.

Every generated message is passed through `check_groundedness`, the same
machinery that verifies Copilot answers, against the measurements that
produced it. A rule that states a number the services did not compute is a
rule that fabricates, and it is refused rather than shown.

`model_outputs` was a second dead table. It is now written with each health
score, which is what makes `health_score_drop` measurable at all: comparing
today's score to the last one requires having stored the last one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, AlertSeverity, AlertType, ModelOutput, User
from app.services import goal_service, health_service, insight_service, risk_service
from app.services.copilot_grounding import check_groundedness

__all__ = [
    "CONCENTRATION_THRESHOLDS",
    "DRAWDOWN_TOLERANCE_MULTIPLE",
    "HEALTH_DROP_POINTS",
    "ALLOCATION_DRIFT_THRESHOLD",
    "REGENERATION_COOLDOWN_HOURS",
    "generate_alerts",
    "list_alerts",
    "mark_read",
    "dismiss",
]

# A single position above this share of the portfolio is worth stating. 25%
# is the point at which one company's results move more of the portfolio than
# the entire rest of a ten-stock holding would, and it is the same threshold
# `risk_service._interpret_concentration` already uses, so the alert and the
# Risk page cannot disagree about what counts as concentrated.
CONCENTRATION_THRESHOLDS = {
    AlertSeverity.INFO: 0.25,
    AlertSeverity.WARNING: 0.35,
    AlertSeverity.CRITICAL: 0.50,
}

# A current drawdown is flagged once it passes the drawdown the investor's
# own stated risk tolerance accommodates. The multiple is 1.0 deliberately:
# the tolerance is the line the investor drew, and reaching it is the event.
DRAWDOWN_TOLERANCE_MULTIPLE = 1.0

# Points of health score lost since the last recorded measurement.
HEALTH_DROP_POINTS = {
    AlertSeverity.INFO: 5.0,
    AlertSeverity.WARNING: 10.0,
    AlertSeverity.CRITICAL: 20.0,
}

# Annualised share of the portfolio reallocated, from Phase 2's measure.
ALLOCATION_DRIFT_THRESHOLD = {
    AlertSeverity.INFO: 0.20,
    AlertSeverity.WARNING: 0.40,
    AlertSeverity.CRITICAL: 0.60,
}

# A goal projected to reach less than this share of its target is off track.
GOAL_FUNDING_THRESHOLD = {
    AlertSeverity.INFO: 0.95,
    AlertSeverity.WARNING: 0.80,
    AlertSeverity.CRITICAL: 0.60,
}

# An alert of the same type is not recreated within this window. Without it,
# every page load would append another copy of the same finding, and a list
# of forty identical alerts communicates less than one.
REGENERATION_COOLDOWN_HOURS = 24

HEALTH_SCORE_MODEL_NAME = "health_score"


@dataclass
class Candidate:
    """A finding, before it is checked and persisted."""

    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metric_value: float | None
    threshold: float | None
    details: dict = field(default_factory=dict)


@dataclass
class Evidence:
    """Everything the rules measure, gathered once.

    Held as plain dicts from the existing services rather than recomputed, so
    an alert cannot disagree with the page a user would check it against.
    """

    health: dict = field(default_factory=dict)
    concentration: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    goals: list[dict] = field(default_factory=list)
    anomalies: dict = field(default_factory=dict)
    previous_health: float | None = None
    risk_tolerance: str = "moderate"
    failures: dict = field(default_factory=dict)

    def tool_outputs(self) -> list[dict]:
        """The measurements a generated message is allowed to cite."""
        return [
            self.health, self.concentration, self.risk, self.anomalies,
            {"goals": self.goals},
            {"previous_health_score": self.previous_health},
        ]


def _severity_for(value: float, thresholds: dict, higher_is_worse: bool = True):
    """The worst severity whose threshold ``value`` has passed, or None."""
    order = [AlertSeverity.CRITICAL, AlertSeverity.WARNING, AlertSeverity.INFO]
    for severity in order:
        limit = thresholds[severity]
        if (value >= limit) if higher_is_worse else (value <= limit):
            return severity
    return None


# --------------------------------------------------------------------------
# Gathering
# --------------------------------------------------------------------------

def gather_evidence(db: Session, user: User) -> Evidence:
    """Measure everything, tolerating the parts that cannot be measured.

    A portfolio with no price history still has concentration; a user with no
    goals still has a drawdown. Each source is attempted separately so one
    unavailable measurement does not silence every rule, and what failed is
    recorded rather than swallowed.
    """
    evidence = Evidence(risk_tolerance=str(user.risk_tolerance or "moderate"))

    try:
        evidence.health = health_service.health_score(db, user, methodology="v2")
    except Exception as exc:  # noqa: BLE001 - recorded, not hidden
        evidence.failures["health"] = str(exc)

    try:
        evidence.concentration = risk_service.concentration(db, user)
    except risk_service.InsufficientHistory as exc:
        evidence.failures["concentration"] = str(exc)

    try:
        evidence.risk = risk_service.risk(db, user)
    except risk_service.InsufficientHistory as exc:
        evidence.failures["risk"] = str(exc)

    try:
        evidence.goals = [
            goal_service.forecast_goal(db, user, goal)
            for goal in goal_service.list_goals(db, user)
        ]
    except Exception as exc:  # noqa: BLE001
        evidence.failures["goals"] = str(exc)

    try:
        evidence.anomalies = insight_service.detect_anomalies(db, user)
    except Exception as exc:  # noqa: BLE001
        evidence.failures["anomalies"] = str(exc)

    evidence.previous_health = _last_recorded_health_score(db, user)
    return evidence


def _last_recorded_health_score(db: Session, user: User) -> float | None:
    row = db.scalars(
        select(ModelOutput)
        .where(
            ModelOutput.user_id == user.id,
            ModelOutput.model_name == HEALTH_SCORE_MODEL_NAME,
        )
        .order_by(ModelOutput.created_at.desc())
        .limit(1)
    ).first()
    return float(row.score) if row and row.score is not None else None


def _record_health_score(db: Session, user: User, evidence: Evidence) -> None:
    """Store today's score so tomorrow's comparison is possible.

    `model_outputs` existed, was migrated and was never written to. Without
    this, health_score_drop can never fire: there is nothing to drop from.
    """
    total = evidence.health.get("total")
    if total is None:
        return
    db.add(ModelOutput(
        user_id=user.id,
        model_name=HEALTH_SCORE_MODEL_NAME,
        model_version=str(evidence.health.get("methodology_version", "v2")),
        as_of_date=date.today(),
        score=float(total),
        prediction=str(evidence.health.get("grade")),
        payload={
            "components": {
                c["name"]: c["score"] for c in evidence.health.get("components", [])
            },
            "missing_inputs": evidence.health.get("missing_inputs", []),
        },
    ))


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def rule_concentration(evidence: Evidence) -> Candidate | None:
    report = evidence.concentration
    top = report.get("top_1_weight")
    if top is None:
        return None

    severity = _severity_for(float(top), CONCENTRATION_THRESHOLDS)
    if severity is None:
        return None

    name = report.get("largest_holding") or "the largest holding"
    effective = report.get("effective_holdings")
    count = report.get("n_holdings")

    message = (
        f"{name} is {top:.1%} of the portfolio. A single company's results "
        f"therefore move that share of your wealth directly."
    )
    if effective and count:
        message += (
            f" The portfolio holds {count} positions but, because the weights "
            f"are uneven, it behaves like roughly {effective:.1f} equally "
            "weighted ones."
        )

    return Candidate(
        alert_type=AlertType.CONCENTRATION,
        severity=severity,
        title=f"{name} is {top:.0%} of the portfolio",
        message=message,
        metric_value=float(top),
        threshold=CONCENTRATION_THRESHOLDS[severity],
        details={
            "largest_holding": name,
            "top_1_weight": top,
            "top_5_weight": report.get("top_5_weight"),
            "n_holdings": count,
            "effective_holdings": effective,
            "measured_by": "risk_service.concentration",
        },
    )


def rule_drawdown(evidence: Evidence) -> Candidate | None:
    from wealthos_core.health import DRAWDOWN_TOLERANCE

    drawdown = (evidence.risk.get("drawdown") or {}).get("current_drawdown")
    if drawdown is None:
        return None

    magnitude = abs(float(drawdown))
    tolerance = DRAWDOWN_TOLERANCE.get(evidence.risk_tolerance, 0.25)
    limit = tolerance * DRAWDOWN_TOLERANCE_MULTIPLE
    if magnitude < limit:
        return None

    ratio = magnitude / tolerance if tolerance else float("inf")
    severity = (
        AlertSeverity.CRITICAL if ratio >= 1.5
        else AlertSeverity.WARNING if ratio >= 1.2
        else AlertSeverity.INFO
    )
    detail = evidence.risk.get("drawdown", {})

    message = (
        f"The portfolio is {magnitude:.1%} below its peak. A "
        f"{evidence.risk_tolerance} risk tolerance corresponds to a "
        f"{tolerance:.0%} drawdown band in this platform's scoring, so the "
        "current fall is outside the range that profile describes."
    )
    if detail.get("peak_date"):
        message += f" The peak was on {detail['peak_date']}."

    return Candidate(
        alert_type=AlertType.DRAWDOWN,
        severity=severity,
        title=f"Portfolio is {magnitude:.0%} below its peak",
        message=message,
        metric_value=magnitude,
        threshold=limit,
        details={
            "current_drawdown": drawdown,
            "max_drawdown": detail.get("max_drawdown"),
            "peak_date": detail.get("peak_date"),
            "trough_date": detail.get("trough_date"),
            "stated_risk_tolerance": evidence.risk_tolerance,
            "tolerance_band": tolerance,
            "measured_by": "risk_service.risk",
        },
    )


def rule_goal_off_track(evidence: Evidence) -> Candidate | None:
    off_track = [
        g for g in evidence.goals
        if g.get("funding_ratio") is not None
        and float(g["funding_ratio"]) < GOAL_FUNDING_THRESHOLD[AlertSeverity.INFO]
    ]
    if not off_track:
        return None

    worst = min(off_track, key=lambda g: float(g["funding_ratio"]))
    ratio = float(worst["funding_ratio"])
    severity = _severity_for(ratio, GOAL_FUNDING_THRESHOLD, higher_is_worse=False)
    if severity is None:
        return None

    name = worst.get("name") or "A goal"
    shortfall = worst.get("shortfall")
    required = worst.get("required_monthly_contribution")

    message = (
        f"On the stated assumptions, {name} is projected to reach {ratio:.0%} "
        f"of its target by its target date."
    )
    if shortfall is not None:
        message += f" That leaves a shortfall of {shortfall:,.0f}."
    if required is not None:
        message += (
            f" Reaching the target on the same assumptions would require "
            f"{required:,.0f} a month, against the "
            f"{worst.get('monthly_contribution', 0):,.0f} currently recorded."
        )
    message += (
        " The projection depends on the expected return, the target date and "
        "the contribution, all of which are stated with the goal."
    )

    return Candidate(
        alert_type=AlertType.GOAL_OFF_TRACK,
        severity=severity,
        title=f"{name} is projected to reach {ratio:.0%} of its target",
        message=message,
        metric_value=ratio,
        threshold=GOAL_FUNDING_THRESHOLD[severity],
        details={
            "goal_id": worst.get("goal_id"),
            "goal_name": name,
            "funding_ratio": ratio,
            "shortfall": shortfall,
            "required_monthly_contribution": required,
            "monthly_contribution": worst.get("monthly_contribution"),
            "goals_off_track": len(off_track),
            "assumptions": worst.get("assumptions"),
            "measured_by": "goal_service.forecast_goal",
        },
    )


def rule_allocation_drift(evidence: Evidence) -> Candidate | None:
    behaviour = (evidence.health.get("context") or {}).get("behaviour") or {}
    drift = behaviour.get("allocation_drift")
    source = behaviour.get("allocation_drift_source")
    if drift is None or source in (None, "unavailable"):
        return None

    drift = float(drift)
    severity = _severity_for(drift, ALLOCATION_DRIFT_THRESHOLD)
    if severity is None:
        return None

    measured = (
        "from your recorded transactions" if source == "transactions"
        else "from the reconstructed price path, which shows drift caused by "
             "prices moving rather than by trading"
    )
    message = (
        f"The asset allocation moved by {drift:.0%} over a year, measured "
        f"{measured}. A portfolio whose mix has shifted that far is carrying "
        "a different risk profile from the one it started with."
    )

    return Candidate(
        alert_type=AlertType.ALLOCATION_DRIFT,
        severity=severity,
        title=f"Allocation has drifted {drift:.0%} over a year",
        message=message,
        metric_value=drift,
        threshold=ALLOCATION_DRIFT_THRESHOLD[severity],
        details={
            "allocation_drift": drift,
            "source": source,
            "definition": (
                "Annualised mean month-to-month L1 change in the asset-class "
                "weight vector, halved so that moving a tenth of the "
                "portfolio reads as 0.10."
            ),
            "measured_by": "health_service._allocation_drift",
        },
    )


def rule_health_score_drop(evidence: Evidence) -> Candidate | None:
    current = evidence.health.get("total")
    previous = evidence.previous_health
    if current is None or previous is None:
        return None

    drop = float(previous) - float(current)
    severity = _severity_for(drop, HEALTH_DROP_POINTS)
    if severity is None:
        return None

    components = evidence.health.get("components", [])
    weakest = min(
        (c for c in components if c.get("score") is not None),
        key=lambda c: c["score"], default=None,
    )

    message = (
        f"The portfolio health score fell from {previous:.1f} to "
        f"{current:.1f}, a drop of {drop:.1f} points."
    )
    if weakest:
        message += (
            f" The weakest component is now {weakest['name'].replace('_', ' ')} "
            f"at {weakest['score']:.0f} out of 100."
        )

    return Candidate(
        alert_type=AlertType.HEALTH_SCORE_DROP,
        severity=severity,
        title=f"Health score fell {drop:.0f} points",
        message=message,
        metric_value=float(current),
        threshold=float(previous) - HEALTH_DROP_POINTS[severity],
        details={
            "previous_score": previous,
            "current_score": current,
            "drop": drop,
            "weakest_component": weakest.get("name") if weakest else None,
            "methodology_version": evidence.health.get("methodology_version"),
            "measured_by": "health_service.health_score",
        },
    )


def rule_anomaly(evidence: Evidence) -> Candidate | None:
    report = evidence.anomalies
    if not report.get("available"):
        return None
    detected = report.get("anomalies") or []
    if not detected:
        return None

    latest = detected[-1]
    count = len(detected)
    severity = (
        AlertSeverity.CRITICAL if latest.get("severity") == "critical"
        else AlertSeverity.WARNING if latest.get("severity") == "warning"
        else AlertSeverity.INFO
    )

    drivers = latest.get("largest_contributors") or latest.get("drivers") or []
    driver_names = [
        d.get("feature", d) if isinstance(d, dict) else d for d in drivers[:3]
    ]

    message = (
        f"{count} unusual {'month' if count == 1 else 'months'} "
        f"{'was' if count == 1 else 'were'} flagged in the portfolio's "
        f"history, most recently {latest.get('date')}. The detector compares "
        "each month against the typical pattern it learned and reports the "
        "ones it reconstructs badly."
    )
    if driver_names:
        message += (
            " What stood out: "
            + ", ".join(str(n).replace("_", " ") for n in driver_names)
            + "."
        )
    message += (
        " It was trained on a synthetic cohort with injected anomalies, so a "
        "flag means 'unlike the training pattern', not 'a mistake'."
    )

    return Candidate(
        alert_type=AlertType.ANOMALY,
        severity=severity,
        title=f"{count} unusual {'month' if count == 1 else 'months'} detected",
        message=message,
        metric_value=float(latest.get("score") or 0.0),
        threshold=float(report.get("threshold") or 0.0) or None,
        details={
            "months_flagged": count,
            "most_recent": latest.get("date"),
            "drivers": driver_names,
            "model": "anomaly_autoencoder",
            "measured_by": "insight_service.detect_anomalies",
        },
    )


RULES = (
    rule_concentration,
    rule_drawdown,
    rule_goal_off_track,
    rule_allocation_drift,
    rule_health_score_drop,
    rule_anomaly,
)

# No rule may use any of these. They turn a measurement into a
# recommendation, which is the line this platform does not cross.
FORBIDDEN_PHRASES = (
    "you should", "we recommend", "recommend that", "buy ", "sell ",
    "reduce your", "increase your", "rebalance to", "switch to",
    "guaranteed", "will return", "risk-free profit", "advise you",
)


def _reads_as_advice(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered]


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def generate_alerts(db: Session, user: User) -> dict:
    """Run every rule, verify each message, and persist what survives.

    A candidate is rejected if it cites a number the services did not
    produce, or if its wording reads as advice. Both rejections are reported
    rather than silently dropped: a rule that keeps failing verification is a
    bug worth seeing.
    """
    evidence = gather_evidence(db, user)
    tool_outputs = evidence.tool_outputs()

    existing = _open_alert_types(db, user)
    created: list[Alert] = []
    rejected: list[dict] = []
    suppressed: list[str] = []

    for rule in RULES:
        candidate = rule(evidence)
        if candidate is None:
            continue

        if candidate.alert_type in existing:
            suppressed.append(str(candidate.alert_type))
            continue

        advice = _reads_as_advice(candidate.message + " " + candidate.title)
        if advice:
            rejected.append({
                "rule": rule.__name__,
                "reason": "reads as investment advice",
                "phrases": advice,
            })
            continue

        grounding = check_groundedness(
            candidate.message, tool_outputs + [candidate.details]
        )
        if not grounding["is_grounded"]:
            rejected.append({
                "rule": rule.__name__,
                "reason": "cites figures the measurements do not contain",
                "unverified_numbers": grounding["unverified_numbers"],
                "groundedness_rate": grounding["groundedness_rate"],
            })
            continue

        alert = Alert(
            user_id=user.id,
            alert_type=candidate.alert_type,
            severity=candidate.severity,
            title=candidate.title[:160],
            message=candidate.message[:1024],
            metric_value=candidate.metric_value,
            threshold=candidate.threshold,
            details={
                **candidate.details,
                "groundedness": grounding,
                "rule": rule.__name__,
            },
        )
        db.add(alert)
        created.append(alert)

    _record_health_score(db, user, evidence)
    db.commit()
    for alert in created:
        db.refresh(alert)

    return {
        "generated": [_serialise(a) for a in created],
        "generated_count": len(created),
        "suppressed_as_already_open": suppressed,
        "rejected": rejected,
        "rules_run": len(RULES),
        "measurement_failures": evidence.failures,
        "stance": (
            "Alerts state what was measured, the threshold it passed and the "
            "evidence behind it. They do not recommend trades: this is an "
            "analytics tool, not a regulated advisory service."
        ),
    }


def _open_alert_types(db: Session, user: User) -> set[AlertType]:
    """Types with an unread alert raised inside the cooldown window."""
    since = datetime.now(timezone.utc) - timedelta(hours=REGENERATION_COOLDOWN_HOURS)
    rows = db.scalars(
        select(Alert).where(
            Alert.user_id == user.id,
            Alert.created_at >= since,
        )
    ).all()
    return {row.alert_type for row in rows}


def _serialise(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "alert_type": str(alert.alert_type),
        "severity": str(alert.severity),
        "title": alert.title,
        "message": alert.message,
        "metric_value": alert.metric_value,
        "threshold": alert.threshold,
        "details": alert.details,
        "is_read": alert.is_read,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def list_alerts(
    db: Session, user: User, include_read: bool = True, limit: int = 50
) -> dict:
    query = select(Alert).where(Alert.user_id == user.id)
    if not include_read:
        query = query.where(Alert.is_read.is_(False))
    rows = db.scalars(
        query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)
    ).all()

    by_severity: dict[str, int] = {}
    for row in rows:
        key = str(row.severity)
        by_severity[key] = by_severity.get(key, 0) + 1

    return {
        "alerts": [_serialise(a) for a in rows],
        "total": len(rows),
        "unread": sum(1 for a in rows if not a.is_read),
        "by_severity": by_severity,
    }


def mark_read(db: Session, user: User, alert_id: int) -> dict | None:
    alert = db.scalars(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    ).first()
    if alert is None:
        return None
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return _serialise(alert)


def dismiss(db: Session, user: User, alert_id: int) -> bool:
    alert = db.scalars(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    ).first()
    if alert is None:
        return False
    db.delete(alert)
    db.commit()
    return True
