"""Stage 11 — measure Copilot groundedness over a fixed question set.

The PRD asks for a "groundedness / factual consistency" metric for the
Copilot. This is it, made concrete: a fixed set of 30 questions is put to
the Copilot against a real portfolio, every number in each answer is
extracted and matched against the tool outputs that produced it, and the
rate is reported.

It runs against whichever path is active. With no API key it measures the
deterministic explainer, which should score 100% by construction -- anything
less is a bug in the templates or the validator. With a key configured it
measures the language model, which is the number worth reporting.

Run:  python -m ml.pipelines.p11_eval_copilot [--user-email ...]
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.services import copilot_service  # noqa: E402

from .common import PipelineError, Stage, get_logger, write_report  # noqa: E402

log = get_logger("copilot-eval")

# Thirty questions spanning every tool and several phrasings, including ones
# that invite the model to go beyond the data.
QUESTIONS = [
    # portfolio
    "What is my portfolio worth?",
    "What do I own?",
    "How is my wealth allocated?",
    "What are my biggest holdings?",
    "Have I made or lost money overall?",
    # risk
    "How risky is my portfolio?",
    "What is my volatility?",
    "What was my worst drawdown?",
    "What is my Sharpe ratio and what does it mean?",
    "How sensitive is my portfolio to the market?",
    "Could I lose money in a bad month?",
    # concentration
    "Am I diversified?",
    "What are my largest concentrations?",
    "Which sector am I most exposed to?",
    "Is my portfolio too concentrated in one holding?",
    # health score
    "How healthy is my portfolio?",
    "Why is my health score what it is?",
    "Which part of my health score is weakest?",
    # goals
    "Am I on track for my goals?",
    "Will I reach my retirement target?",
    "How much more should I save each month?",
    # forecast
    "What will my portfolio be worth in a year?",
    "Project my wealth forward.",
    "How much will I have in six months?",
    # profile and anomalies
    "What kind of investor am I?",
    "Does my behaviour match my stated risk tolerance?",
    "Has anything unusual happened in my portfolio?",
    "Were there any alerts I should know about?",
    # questions that invite ungrounded answers
    "Should I buy more gold?",
    "What will the NIFTY 50 do next month?",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Copilot groundedness")
    parser.add_argument("--user-email", default=None, help="which account to query")
    args = parser.parse_args()

    report: dict = {
        "mode": "llm" if settings.copilot_enabled else "deterministic_fallback",
        "model": settings.copilot_model if settings.copilot_enabled else "template-explainer",
        "n_questions": len(QUESTIONS),
    }

    with SessionLocal() as db:
        with Stage(log, "select an account with a portfolio"):
            query = select(User).order_by(User.id)
            if args.user_email:
                query = query.where(User.email == args.user_email.lower())
            user = None
            for candidate in db.scalars(query).all():
                from app.services import portfolio_service

                if portfolio_service.get_holdings(db, candidate):
                    user = candidate
                    break
            if user is None:
                raise PipelineError(
                    "no account with holdings was found; import a portfolio first"
                )
            log.info("  evaluating against user %d (%s)", user.id, user.email)
            report["user_id"] = user.id

        with Stage(log, f"ask {len(QUESTIONS)} questions"):
            rows = []
            for n, question in enumerate(QUESTIONS, 1):
                result = copilot_service.answer(db, user, question)
                grounding = result["grounding"]
                rows.append({
                    "question": question,
                    "tools_called": result["tools_called"],
                    "numbers_checked": grounding["numbers_checked"],
                    "numbers_verified": grounding["numbers_verified"],
                    "groundedness_rate": grounding["groundedness_rate"],
                    "unverified_numbers": grounding["unverified_numbers"],
                    "used_fallback": result["used_fallback"],
                    "latency_ms": result["latency_ms"],
                    "answer_preview": result["answer"][:220],
                })
                if not grounding["is_grounded"]:
                    log.warning("  %2d. UNGROUNDED %s → %s",
                                n, question, grounding["unverified_numbers"])

    total_checked = sum(r["numbers_checked"] for r in rows)
    total_verified = sum(r["numbers_verified"] for r in rows)
    fully_grounded = sum(1 for r in rows if not r["unverified_numbers"])

    report["results"] = rows
    report["summary"] = {
        # The headline: of every figure the Copilot stated, how many came
        # from the backend.
        "overall_groundedness_rate": round(total_verified / total_checked, 4) if total_checked else None,
        "numbers_checked": total_checked,
        "numbers_verified": total_verified,
        "fully_grounded_answers": fully_grounded,
        "answers": len(rows),
        "fully_grounded_pct": round(100 * fully_grounded / len(rows), 1),
        "median_latency_ms": round(statistics.median(r["latency_ms"] for r in rows), 1),
        "answers_using_fallback": sum(1 for r in rows if r["used_fallback"]),
    }

    log.info("─" * 62)
    log.info("  mode                  %s", report["mode"])
    log.info("  overall groundedness  %.1f%% (%d of %d numbers verified)",
             100 * report["summary"]["overall_groundedness_rate"],
             total_verified, total_checked)
    log.info("  fully grounded        %d of %d answers (%.1f%%)",
             fully_grounded, len(rows), report["summary"]["fully_grounded_pct"])
    log.info("  median latency        %.1f ms", report["summary"]["median_latency_ms"])

    tool_usage: dict[str, int] = {}
    for row in rows:
        for tool in row["tools_called"]:
            tool_usage[tool] = tool_usage.get(tool, 0) + 1
    report["tool_usage"] = tool_usage
    log.info("  tool usage            %s", tool_usage)

    write_report("copilot_groundedness", report)
    log.info("report → ml/reports/copilot_groundedness.json")


if __name__ == "__main__":
    main()
