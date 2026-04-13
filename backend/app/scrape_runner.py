"""Scrape job state machine and background job runners.

Two job types:
- update  (Phase 1 only): crawl overview, upsert new listings
- regular (Phase 2+3):    sold-recheck + cleanup rotation

Single module-level _state tracks the currently-running job — safe for
single-process uvicorn. The check-and-set is synchronous (no await between
the guard and the state mutation) — safe in asyncio's cooperative model.

Completed runs are appended to _log (deque, maxlen=50) for the UI log view.
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import AsyncSessionLocal
from app.scraper.orchestrator import (
    _phase1_new_listings,
    _phase2_sold_recheck,
    _phase3_cleanup,
)
from app.services.search_matcher import check_new_matches

logger = logging.getLogger(__name__)

# Current job state — one job runs at a time
_state: dict[str, Any] = {
    "status": "idle",    # "idle" | "running" | "done" | "error"
    "job_type": None,    # "update" | "regular" | None
    "started_at": None,
    "finished_at": None,
    "phase": None,       # "phase1" | "phase2" | "phase3" | None
    "progress": None,
    "summary": None,
    "error": None,
}

# Completed run history — survives until process restart
_log: deque[dict[str, Any]] = deque(maxlen=50)

# Strong references to background tasks prevent GC cancellation
_background_tasks: set[asyncio.Task] = set()


def get_state() -> dict[str, Any]:
    """Return a shallow copy of the current scrape state."""
    return dict(_state)


def get_log() -> list[dict[str, Any]]:
    """Return log entries newest-first."""
    return list(reversed(_log))


def reset_state() -> None:
    """Reset state to idle and clear log. Used in tests only."""
    _state.update({
        "status": "idle",
        "job_type": None,
        "started_at": None,
        "finished_at": None,
        "phase": None,
        "progress": None,
        "summary": None,
        "error": None,
    })
    _log.clear()


def _update(**kwargs: Any) -> None:
    _state.update(kwargs)


def _append_log(job_type: str, summary: dict | None, error: str | None) -> None:
    _log.append({
        "job_type": job_type,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "error": error,
    })


async def start_update_job() -> bool:
    """Schedule run_update_job as a background task.

    Returns True if started, False if already running.
    """
    if _state["status"] == "running":
        return False
    task = asyncio.create_task(run_update_job())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


async def start_recheck_job() -> bool:
    """Schedule run_recheck_job as a background task.

    Returns True if started, False if already running.
    """
    if _state["status"] == "running":
        return False
    task = asyncio.create_task(run_recheck_job())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


async def run_update_job() -> None:
    """Phase 1 only: crawl overview pages and upsert new listings."""
    if _state["status"] == "running":
        logger.info("Scrape already running — skipping update job")
        return

    _update(
        status="running",
        job_type="update",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        phase="phase1",
        progress="Starte…",
        summary=None,
        error=None,
    )
    logger.info("Update job started")

    try:
        async with AsyncSessionLocal() as session:
            result = await _phase1_new_listings(
                session,
                update_progress=lambda p: _update(phase="phase1", progress=p),
                delay=settings.SCRAPE_DELAY,
            )
            new_ids = result.get("new_ids", [])
            if new_ids:
                matches = await check_new_matches(session, new_ids)
                logger.info("Matcher found %d new matches", matches)

        _update(
            status="done",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            summary=result,
            error=None,
        )
        _append_log("update", result, None)
        logger.info("Update job complete: %s", result)

    except Exception as exc:
        logger.exception("Update job failed: %s", exc)
        _update(
            status="error",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            summary=None,  # clear any stale summary from a previous successful run
            error=str(exc),
        )
        _append_log("update", None, str(exc))


async def run_recheck_job() -> None:
    """Phase 2+3: sold-recheck rotation and cleanup."""
    if _state["status"] == "running":
        logger.info("Scrape already running — skipping recheck job")
        return

    _update(
        status="running",
        job_type="regular",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        phase="phase2",
        progress="Sold-Check…",
        summary=None,
        error=None,
    )
    logger.info("Recheck job started")

    try:
        summary: dict[str, Any] = {}

        async with AsyncSessionLocal() as session:
            result = await _phase2_sold_recheck(
                session,
                update_progress=lambda p: _update(phase="phase2", progress=p),
                delay=settings.RECHECK_DELAY,
                batch_size=settings.RECHECK_BATCH_SIZE,
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
            error=None,
        )
        _append_log("regular", summary, None)
        logger.info("Recheck job complete: %s", summary)

    except Exception as exc:
        logger.exception("Recheck job failed: %s", exc)
        _update(
            status="error",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            summary=None,  # clear any stale summary from a previous successful run
            error=str(exc),
        )
        _append_log("regular", None, str(exc))
