"""The daily jobs, without a cron: one background loop in the API process.

Every 15 minutes it:

1. appends any new closes to the analytics prices (``price_refresh``);
2. records the forward test's scores for new sessions;
3. runs every enabled Autopilot whose rebalance is due.

Each step is idempotent and only ever acts on completed sessions (bars
final after 16:00 IST), so running it often costs nothing and a restart
simply catches up. It starts only when live market data is on, so the test
suite never runs it.
"""

from __future__ import annotations

import logging
import threading

from app.db.session import SessionLocal

log = logging.getLogger("wealthos.scheduler")

INTERVAL_SECONDS = 900
_started = False
_stop = threading.Event()


def tick() -> dict:
    from app.services import autopilot_service, forward_test_service, price_refresh

    out: dict = {}
    steps = (("prices", price_refresh.refresh), ("forward_test", forward_test_service.catch_up),
             ("autopilot", autopilot_service.run_due))
    for name, step in steps:
        with SessionLocal() as db:
            try:
                out[name] = step(db)
            except Exception as exc:  # one failing job must not stop the others
                db.rollback()
                log.warning("scheduled %s failed: %s", name, exc)
                out[name] = {"error": str(exc)}
    return out


def start() -> None:
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        # On low-memory (free-plan) hosting, give the first page loads after a
        # cold start the CPU before the heavier daily jobs run.
        from app.core.config import settings

        if settings.low_memory and _stop.wait(120):
            return
        while not _stop.is_set():
            result = tick()
            ran = result.get("autopilot")
            if isinstance(ran, list) and ran:
                log.info("autopilot ran for %d user(s)", len(ran))
            _stop.wait(INTERVAL_SECONDS)

    threading.Thread(target=loop, name="wealthos-scheduler", daemon=True).start()
    log.info("scheduler: prices, forward test and Autopilot every %d minutes", INTERVAL_SECONDS // 60)
