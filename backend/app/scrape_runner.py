"""Scrape job state machine and background job runner.

Single module-level dict tracks job status — safe for single-process uvicorn.
The check-and-set in run_scrape_job is synchronous (no await between the guard
and the state mutation), making it safe without a lock in asyncio's cooperative
multitasking model.

Task reference tracking: callers must store the asyncio.Task in _background_tasks
to prevent GC collection mid-execution (Python docs warning).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import AsyncSessionLocal
from app.scraper.orchestrator import (
    _phase1_new_listings,
    _phase2_sold_recheck,
    _phase3_cleanup,
)

logger = logging.getLogger(__name__)

# Module-level state — single-process, single-user
_state: dict[str, Any] = {
    "status": "idle",    # "idle" | "running" | "done" | "error"
    "started_at": None,  # ISO 8601 string
    "finished_at": None,
    "phase": None,       # "phase1" | "phase2" | "phase3"
    "progress": None,    # human-readable current step
    "summary": None,     # final result dict
    "error": None,
}

# Strong references to background tasks prevent GC cancellation
# (see https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)
_background_tasks: set[asyncio.Task] = set()


def get_state() -> dict[str, Any]:
    """Return a shallow copy of the current scrape state."""
    return dict(_state)


def reset_state() -> None:
    """Reset state to idle. Used in tests only."""
    _state.update({
        "status": "idle",
        "started_at": None,
        "finished_at": None,
        "phase": None,
        "progress": None,
        "summary": None,
        "error": None,
    })


def _update(**kwargs: Any) -> None:
    _state.update(kwargs)


def start_background_job() -> bool:
    """Create an asyncio.Task for run_scrape_job, keeping a strong reference.

    Returns True if the job was started, False if already running.
    """
    if _state["status"] == "running":
        return False
    task = asyncio.create_task(run_scrape_job())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


async def run_scrape_job() -> None:
    """Full scrape cycle: phase1 + phase2 + phase3.

    No-op if already running. Updates _state throughout so callers can poll.
    Creates its own DB sessions — not request-scoped.
    """
    # Guard: synchronous check-and-set (no await between them — safe in asyncio)
    if _state["status"] == "running":
        logger.info("Scrape already running — ignoring trigger")
        return

    _update(
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        phase="phase1",
        progress="Starte…",
        summary=None,
        error=None,
    )
    logger.info("Scrape job started")

    try:
        summary: dict[str, Any] = {}
        delay = settings.SCRAPE_DELAY

        _update(phase="phase1", progress="Übersichtsseiten scannen…")
        async with AsyncSessionLocal() as session:
            result = await _phase1_new_listings(
                session,
                update_progress=lambda p: _update(phase="phase1", progress=p),
                delay=delay,
            )
        summary.update(result)
        logger.info("Phase 1 done: %s", result)

        _update(phase="phase2", progress="Sold-Check…")
        async with AsyncSessionLocal() as session:
            result = await _phase2_sold_recheck(
                session,
                update_progress=lambda p: _update(phase="phase2", progress=p),
                delay=delay,
            )
        summary.update(result)
        logger.info("Phase 2 done: %s", result)

        _update(phase="phase3", progress="Aufräumen…")
        async with AsyncSessionLocal() as session:
            result = await _phase3_cleanup(session)
        summary.update(result)
        logger.info("Phase 3 done: %s", result)

        _update(
            status="done",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            summary=summary,
            error=None,  # clear any error from a previous failed run
        )
        logger.info("Scrape job complete: %s", summary)

    except Exception as exc:
        logger.exception("Scrape job failed: %s", exc)
        _update(
            status="error",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            error=str(exc),
        )
