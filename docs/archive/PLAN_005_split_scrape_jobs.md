# Split Scrape Jobs & Scrape Log Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Split the single 4h scrape cycle into two separate scheduled jobs — a 30-min "update" job (Phase 1: new listings) and a 1h "regular" job (Phase 2+3: recheck + cleanup) — and add an in-memory ring-buffer log visible in the UI header.

**Architecture:** `scrape_runner.py` gets two new async job functions (`run_update_job`, `run_recheck_job`) replacing the monolithic `run_scrape_job`. A module-level `deque(maxlen=50)` accumulates completed-run summaries. The scheduler in `main.py` registers two APScheduler jobs. A new `GET /api/scrape/log` endpoint exposes the ring buffer. The frontend replaces `ScrapeButton` with a compact `ScrapeLog` dropdown in the header.

**Tech Stack:** Python/FastAPI, APScheduler 3.x, collections.deque, React 18/TypeScript, Tailwind CSS

**Breaking Changes:** Yes — `run_scrape_job` and `start_background_job` are removed from `scrape_runner.py`. Tests that import them must be updated in the same PR. Rolling back requires reverting backend + frontend together.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-08 |
| Human | approved | 2026-04-08 |

---

## Reference Patterns

- Config: `backend/app/config.py`
- Orchestrator phases: `backend/app/scraper/orchestrator.py` — `_phase1_new_listings`, `_phase2_sold_recheck`, `_phase3_cleanup`
- Runner state machine: `backend/app/scrape_runner.py`
- API schemas: `backend/app/api/schemas.py`
- API routes: `backend/app/api/routes.py`
- Scheduler wiring: `backend/app/main.py`
- Existing runner tests: `backend/tests/test_scrape_runner.py`
- Existing scheduler test: `backend/tests/test_scheduler.py`
- Existing API tests: `backend/tests/test_api.py` (lines 461–486)
- Frontend types: `frontend/src/types/api.ts`
- Frontend client: `frontend/src/api/client.ts`
- App shell: `frontend/src/App.tsx`
- FavoritesModal (dropdown pattern): `frontend/src/components/FavoritesModal.tsx`

---

## Assumptions & Risks

- Only one job runs at a time — the existing `_state["status"] == "running"` guard remains. If the 1h recheck fires while a 30-min update is still running, the recheck is skipped (returns False). Acceptable for a single-user hobby project.
- `POST /api/scrape` now triggers `run_update_job` (Phase 1 only). A manual full-cycle is not provided; the recheck runs on its schedule.
- `RECHECK_DELAY = 2.0s` is a new config field. Existing `SCRAPE_DELAY = 1.0s` is unchanged and still used by Phase 1.
- The frontend removes the auto-refresh-on-scrape mechanism (`scrapeKey` state in App.tsx). Listings update on next page load.
- In-memory log is lost on process restart — intentional per spec.

---

## Task 1: Config + orchestrator defaults [ ]

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/scraper/orchestrator.py`

**Step 1: Add RECHECK_DELAY to config**

In `backend/app/config.py`, add after `SCRAPE_DELAY`:

```python
RECHECK_DELAY: float = 2.0
```

Full file after change:

```python
"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout"
    SCRAPE_DELAY: float = 1.0
    RECHECK_DELAY: float = 2.0


settings = Settings()
```

**Step 2: Delete the deprecated `run_scrape` shim in orchestrator.py**

Remove the dead-code shim (lines ~398–401) — it references `run_scrape_job` which is being deleted:

```python
# DELETE this entire function:
async def run_scrape(session: AsyncSession, max_pages: int = 10, fresh_threshold_days: int = 7) -> dict:
    """Deprecated shim — superseded by scrape_runner.run_scrape_job. Removed in Task 7."""
    logger.warning("run_scrape shim called — consider using run_scrape_job directly")
    return {"pages_crawled": 0, "listings_found": 0, "new": 0, "updated": 0, "skipped": 0}
```

**Step 3: Change _phase2_sold_recheck default batch_size from 50 to 100**

In `backend/app/scraper/orchestrator.py`, line ~413:

```python
# Before:
async def _phase2_sold_recheck(
    session: AsyncSession,
    update_progress: Callable[[str], None],
    delay: float,
    batch_size: int = 50,
) -> dict:

# After:
async def _phase2_sold_recheck(
    session: AsyncSession,
    update_progress: Callable[[str], None],
    delay: float,
    batch_size: int = 100,
) -> dict:
```

**Step 4: Verify config loads**

```bash
docker compose exec backend python -c "from app.config import settings; print(settings.RECHECK_DELAY)"
```

Expected output: `2.0`

**Step 5: Commit**

```bash
git add backend/app/config.py backend/app/scraper/orchestrator.py
git commit -m "feat: add RECHECK_DELAY config, increase phase2 batch_size to 100, remove run_scrape shim"
```

---

## Task 2: scrape_runner — split jobs + ring buffer log [ ]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/scrape_runner.py`
- Modify: `backend/tests/test_scrape_runner.py`

**Step 1: Rewrite scrape_runner.py**

Replace the full file content:

```python
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
```

**Step 2: Add autouse reset fixture to conftest.py**

The `_log` and `_state` are module-level — without reset between tests, log entries from one test pollute the next. Add an autouse fixture to `backend/tests/conftest.py` at the end of the file:

```python
@pytest.fixture(autouse=True)
def reset_scrape_runner():
    """Reset scrape_runner module state before each test."""
    from app.scrape_runner import reset_state
    reset_state()
    yield
    reset_state()
```

**Step 3: Rewrite test_scrape_runner.py**

```python
"""Tests for scrape_runner job functions and log ring buffer."""
import pytest
from unittest.mock import patch, AsyncMock
from app.scrape_runner import (
    get_state,
    get_log,
    run_update_job,
    run_recheck_job,
    reset_state,
    start_update_job,
    start_recheck_job,
)


def _mock_session():
    s = AsyncMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    return s


# ---------------------------------------------------------------------------
# run_update_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_update_job_transitions_to_done():
    """run_update_job: idle → running → done, appends to log."""
    reset_state()
    p1 = {"pages_crawled": 2, "new": 3, "updated": 0}

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=p1), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_update_job()

    state = get_state()
    assert state["status"] == "done"
    assert state["summary"]["new"] == 3

    log = get_log()
    assert len(log) == 1
    assert log[0]["job_type"] == "update"
    assert log[0]["summary"]["new"] == 3
    assert log[0]["error"] is None


@pytest.mark.asyncio
async def test_run_update_job_sets_error_on_failure():
    """run_update_job sets status=error and logs the error."""
    reset_state()

    with patch("app.scrape_runner._phase1_new_listings",
               new_callable=AsyncMock, side_effect=RuntimeError("timeout")), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_update_job()

    state = get_state()
    assert state["status"] == "error"
    assert "timeout" in state["error"]

    log = get_log()
    assert log[0]["error"] == "timeout"


@pytest.mark.asyncio
async def test_run_update_job_noop_when_running():
    """run_update_job returns immediately if already running."""
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock) as mock_p1:
        await run_update_job()
        assert not mock_p1.called

    runner._state["status"] = "idle"


# ---------------------------------------------------------------------------
# run_recheck_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_recheck_job_transitions_to_done():
    """run_recheck_job: idle → running → done, appends to log."""
    reset_state()
    p2 = {"rechecked": 10, "sold_found": 2}
    p3 = {"deleted_sold": 1, "deleted_stale": 0}

    with patch("app.scrape_runner._phase2_sold_recheck", new_callable=AsyncMock, return_value=p2), \
         patch("app.scrape_runner._phase3_cleanup", new_callable=AsyncMock, return_value=p3), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_recheck_job()

    state = get_state()
    assert state["status"] == "done"
    assert state["summary"]["rechecked"] == 10
    assert state["summary"]["sold_found"] == 2
    assert state["summary"]["deleted_sold"] == 1

    log = get_log()
    assert log[0]["job_type"] == "regular"
    assert log[0]["summary"]["sold_found"] == 2


@pytest.mark.asyncio
async def test_run_recheck_job_sets_error_on_failure():
    """run_recheck_job sets status=error and logs the error."""
    reset_state()

    with patch("app.scrape_runner._phase2_sold_recheck",
               new_callable=AsyncMock, side_effect=RuntimeError("DB gone")), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_recheck_job()

    state = get_state()
    assert state["status"] == "error"
    assert "DB gone" in state["error"]


# ---------------------------------------------------------------------------
# Log ring buffer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_accumulates_multiple_runs():
    """Multiple job runs accumulate in log, newest first."""
    reset_state()
    p1 = {"pages_crawled": 1, "new": 1, "updated": 0}
    p2 = {"rechecked": 5, "sold_found": 0}
    p3 = {"deleted_sold": 0, "deleted_stale": 0}

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=p1), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_update_job()

    with patch("app.scrape_runner._phase2_sold_recheck", new_callable=AsyncMock, return_value=p2), \
         patch("app.scrape_runner._phase3_cleanup", new_callable=AsyncMock, return_value=p3), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_recheck_job()

    log = get_log()
    assert len(log) == 2
    assert log[0]["job_type"] == "regular"  # newest first
    assert log[1]["job_type"] == "update"


# ---------------------------------------------------------------------------
# start_* guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_update_job_rejects_when_running():
    """start_update_job returns False if already running."""
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    result = await start_update_job()
    assert result is False

    runner._state["status"] = "idle"


@pytest.mark.asyncio
async def test_start_recheck_job_rejects_when_running():
    """start_recheck_job returns False if already running."""
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    result = await start_recheck_job()
    assert result is False

    runner._state["status"] = "idle"
```

**Step 4: Run tests**

```bash
docker compose exec backend pytest tests/test_scrape_runner.py -v
```

Expected: all 8 tests pass.

**Step 5: Commit**

```bash
git add backend/app/scrape_runner.py backend/tests/test_scrape_runner.py backend/tests/conftest.py
git commit -m "feat: split scrape_runner into update/recheck jobs with log ring buffer"
```

---

## Task 3: API schemas + routes + scheduler [ ]

**Depends on:** Task 2

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_api.py`

**Step 1: Add ScrapeLogEntry to schemas.py**

In `backend/app/api/schemas.py`, add after `ScrapeStatus`:

```python
class ScrapeLogEntry(BaseModel):
    job_type: Literal["update", "regular"]
    finished_at: str
    summary: ScrapeSummary | None = None
    error: str | None = None
```

Also add `job_type` field to `ScrapeStatus` (so the frontend can show which job is currently running):

```python
class ScrapeStatus(BaseModel):
    status: Literal["idle", "running", "done", "error"]
    job_type: Literal["update", "regular"] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    phase: Literal["phase1", "phase2", "phase3"] | None = None
    progress: str | None = None
    summary: ScrapeSummary | None = None
    error: str | None = None
```

**Step 2: Update routes.py**

Replace the scrape-related imports and endpoints:

```python
# Import changes at top of file:
from app.api.schemas import (
    ListingDetail, ListingSummary, PaginatedResponse, PlzResponse,
    ScrapeSummary, ScrapeStatus, ScrapeLogEntry,
)
from app.scrape_runner import get_state, get_log, start_update_job
```

Update `start_scrape` endpoint:

```python
@router.post("/scrape", status_code=202)
async def start_scrape() -> dict:
    """Trigger a background update job (Phase 1). Returns 409 if already running."""
    logger.info("POST /api/scrape — triggering update job")
    started = await start_update_job()
    if not started:
        raise HTTPException(status_code=409, detail="Scrape already running")
    return {"status": "started"}
```

Update `scrape_status` to include `job_type`:

```python
@router.get("/scrape/status", response_model=ScrapeStatus)
async def scrape_status() -> ScrapeStatus:
    """Return current scrape job status for frontend polling."""
    state = get_state()
    summary_data = state.get("summary")
    summary = ScrapeSummary(**summary_data) if summary_data else None
    return ScrapeStatus(
        status=state["status"],
        job_type=state.get("job_type"),
        started_at=state["started_at"],
        finished_at=state["finished_at"],
        phase=state["phase"],
        progress=state["progress"],
        summary=summary,
        error=state["error"],
    )
```

Add new log endpoint after `scrape_status`:

```python
@router.get("/scrape/log", response_model=list[ScrapeLogEntry])
async def scrape_log() -> list[ScrapeLogEntry]:
    """Return in-memory scrape run history, newest first (max 50 entries)."""
    entries = get_log()
    result = []
    for entry in entries:
        summary_data = entry.get("summary")
        summary = ScrapeSummary(**summary_data) if summary_data else None
        result.append(ScrapeLogEntry(
            job_type=entry["job_type"],
            finished_at=entry["finished_at"],
            summary=summary,
            error=entry.get("error"),
        ))
    return result
```

Also update the `ScrapeLogEntry` import in the `from app.api.schemas import ...` line.

**Step 3: Update main.py scheduler (two jobs)**

Replace the `scheduler.add_job` block:

```python
scheduler = AsyncIOScheduler(timezone="UTC")
scheduler.add_job(
    start_update_job,
    trigger="interval",
    minutes=30,
    id="auto_update",
    replace_existing=True,
)
scheduler.add_job(
    start_recheck_job,
    trigger="interval",
    hours=1,
    id="auto_recheck",
    replace_existing=True,
)
scheduler.start()
app.state.scheduler = scheduler
logger.info("Scheduler started — update every 30min, recheck every 1h")
```

Update the imports in main.py:

```python
from app.scrape_runner import start_update_job, start_recheck_job
```

**Step 4: Update test_scheduler.py**

```python
"""Tests for APScheduler wiring in main.py lifespan."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_lifespan_registers_two_jobs_and_does_not_fire_on_startup():
    """Lifespan startup registers auto_update + auto_recheck but does NOT fire immediately."""
    from app.main import app

    start_calls = []

    async def fake_start_update_job():
        start_calls.append("update")
        return True

    async def fake_start_recheck_job():
        start_calls.append("recheck")
        return True

    with patch("app.main.start_update_job", fake_start_update_job), \
         patch("app.main.start_recheck_job", fake_start_recheck_job), \
         patch("app.db.init_db", new_callable=AsyncMock):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

            assert start_calls == [], "Jobs must not fire on startup"

            scheduler = app.state.scheduler
            jobs = {j.id: j for j in scheduler.get_jobs()}
            assert set(jobs.keys()) == {"auto_update", "auto_recheck"}

            assert jobs["auto_update"].trigger.interval.total_seconds() == 30 * 60
            assert jobs["auto_recheck"].trigger.interval.total_seconds() == 3600
```

**Step 5: Update test_api.py — patch the new function name**

Find lines 461–486 in `backend/tests/test_api.py`. The mock target changes from `start_background_job` to `start_update_job`. Update all three scrape-related test methods:

```python
async def test_start_scrape_returns_202(self, api_client: AsyncClient) -> None:
    """POST /api/scrape starts background job and returns 202."""
    with patch("app.api.routes.start_update_job", new_callable=AsyncMock, return_value=True):
        resp = await api_client.post("/api/scrape")
    assert resp.status_code == 202

async def test_start_scrape_returns_409_when_running(
    self, api_client: AsyncClient
) -> None:
    """POST /api/scrape returns 409 if already running."""
    with patch("app.api.routes.start_update_job", new_callable=AsyncMock, return_value=False):
        resp = await api_client.post("/api/scrape")
    assert resp.status_code == 409

async def test_scrape_status_returns_idle(self, api_client: AsyncClient) -> None:
    """GET /api/scrape/status returns current state."""
    from app.scrape_runner import reset_state
    reset_state()
    resp = await api_client.get("/api/scrape/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "idle"
```

Also add a test for the new log endpoint in the same class:

```python
async def test_scrape_log_returns_empty_initially(self, api_client: AsyncClient) -> None:
    """GET /api/scrape/log returns empty list on fresh start."""
    from app.scrape_runner import reset_state
    reset_state()
    resp = await api_client.get("/api/scrape/log")
    assert resp.status_code == 200
    assert resp.json() == []
```

**Step 6: Run all backend tests**

```bash
docker compose exec backend pytest tests/ -v
```

Expected: all tests pass.

**Step 7: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/app/main.py \
        backend/tests/test_scheduler.py backend/tests/test_api.py
git commit -m "feat: add scrape log endpoint, split scheduler into 30min/1h jobs"
```

---

## Task 4: Frontend types + client [ ]

**Depends on:** Task 3

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`

**Step 1: Add ScrapeLogEntry type and update ScrapeStatus**

In `frontend/src/types/api.ts`, add after the `ScrapeStatus` interface:

```typescript
export interface ScrapeLogEntry {
  job_type: 'update' | 'regular';
  finished_at: string;  // ISO 8601
  summary: ScrapeSummary | null;
  error: string | null;
}
```

Also add `job_type` to `ScrapeStatus`:

```typescript
export interface ScrapeStatus {
  status: ScrapeJobStatus;
  job_type: 'update' | 'regular' | null;
  started_at: string | null;
  finished_at: string | null;
  phase: ScrapePhase;
  progress: string | null;
  summary: ScrapeSummary | null;
  error: string | null;
}
```

**Step 2: Add getScrapeLog to client.ts**

In `frontend/src/api/client.ts`, add after `getScrapeStatus`:

```typescript
export async function getScrapeLog(): Promise<ScrapeLogEntry[]> {
  const res = await fetch('/api/scrape/log');
  return handleResponse<ScrapeLogEntry[]>(res);
}
```

Update the import at the top of the file to include `ScrapeLogEntry`:

```typescript
import type {
  ListingsQueryParams,
  ListingDetail,
  ListingSummary,
  PaginatedResponse,
  PlzResponse,
  ScrapeLogEntry,
  ScrapeStatus,
} from '../types/api';
```

**Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat: add ScrapeLogEntry type and getScrapeLog client function"
```

---

## Task 5: Frontend ScrapeLog component + remove ScrapeButton [ ]

**Depends on:** Task 4

**Files:**
- Create: `frontend/src/components/ScrapeLog.tsx`
- Create: `frontend/src/components/__tests__/ScrapeLog.test.tsx`
- Delete: `frontend/src/components/ScrapeButton.tsx`
- Delete: `frontend/src/components/__tests__/ScrapeButton.test.tsx`

**Reuse check:** No existing log/history dropdown pattern found in codebase. FavoritesModal (`frontend/src/components/FavoritesModal.tsx`) uses a similar overlay pattern but a full modal — ScrapeLog uses a lighter inline dropdown.

**Step 1: Create ScrapeLog.tsx**

The component polls every 60s, shows a history icon button, and renders a dropdown with the last 10 entries.

Entry format:
- `[update] 3 new`
- `[regular] 10 checked · 2 sold · 1 deleted`
- Error entries: `[update] Fehler`

```tsx
import { useEffect, useRef, useState } from 'react';
import { getScrapeLog } from '../api/client';
import type { ScrapeLogEntry } from '../types/api';

const POLL_MS = 60_000;
const MAX_DISPLAY = 10;

function formatEntry(entry: ScrapeLogEntry): string {
  if (entry.error) return 'Fehler';
  const s = entry.summary;
  if (!s) return '—';
  if (entry.job_type === 'update') {
    return `${s.new} neu`;
  }
  const parts: string[] = [];
  if (s.rechecked > 0) parts.push(`${s.rechecked} geprüft`);
  if (s.sold_found > 0) parts.push(`${s.sold_found} verkauft`);
  const deleted = (s.deleted_sold ?? 0) + (s.deleted_stale ?? 0);
  if (deleted > 0) parts.push(`${deleted} gelöscht`);
  return parts.length > 0 ? parts.join(' · ') : 'keine Änderungen';
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

export default function ScrapeLog() {
  const [entries, setEntries] = useState<ScrapeLogEntry[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  async function fetchLog() {
    try {
      const data = await getScrapeLog();
      setEntries(data.slice(0, MAX_DISPLAY));
    } catch {
      // silently ignore — non-critical
    }
  }

  useEffect(() => {
    fetchLog();
    const id = setInterval(fetchLog, POLL_MS);
    return () => clearInterval(id);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Scrape-Verlauf"
        className="p-2 rounded-lg text-gray-500 hover:text-brand hover:bg-gray-100 transition-colors"
        aria-label="Scrape-Verlauf anzeigen"
      >
        {/* Clock icon */}
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 3" strokeLinecap="round" />
        </svg>
        {entries.length > 0 && (
          <span className="sr-only">{entries.length} Einträge</span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-72 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Scrape-Verlauf
          </div>
          {entries.length === 0 ? (
            <div className="px-3 py-4 text-sm text-gray-400 text-center">Noch keine Läufe</div>
          ) : (
            <ul className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
              {entries.map((entry, i) => (
                <li key={i} className="flex items-baseline justify-between px-3 py-2 text-sm">
                  <span>
                    <span
                      className={`font-mono text-xs px-1.5 py-0.5 rounded mr-2 ${
                        entry.job_type === 'update'
                          ? 'bg-blue-50 text-blue-700'
                          : 'bg-green-50 text-green-700'
                      }`}
                    >
                      {entry.job_type === 'update' ? 'update' : 'regular'}
                    </span>
                    <span className={entry.error ? 'text-red-500' : 'text-gray-700'}>
                      {formatEntry(entry)}
                    </span>
                  </span>
                  <span className="text-xs text-gray-400 ml-2 shrink-0">
                    {formatTime(entry.finished_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Create ScrapeLog.test.tsx**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import ScrapeLog from '../ScrapeLog';
import * as client from '../../api/client';

describe('ScrapeLog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders clock icon button', () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([]);
    render(<ScrapeLog />);
    expect(screen.getByRole('button', { name: /verlauf/i })).toBeInTheDocument();
  });

  it('shows "Noch keine Läufe" when log is empty', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText(/noch keine läufe/i)).toBeInTheDocument();
    });
  });

  it('renders update entry correctly', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([
      {
        job_type: 'update',
        finished_at: new Date('2026-04-08T14:30:00Z').toISOString(),
        summary: { pages_crawled: 2, new: 4, updated: 0, rechecked: 0, sold_found: 0, deleted_sold: 0, deleted_stale: 0 },
        error: null,
      },
    ]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('update')).toBeInTheDocument();
      expect(screen.getByText('4 neu')).toBeInTheDocument();
    });
  });

  it('renders regular entry correctly', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([
      {
        job_type: 'regular',
        finished_at: new Date('2026-04-08T15:00:00Z').toISOString(),
        summary: { pages_crawled: 0, new: 0, updated: 0, rechecked: 10, sold_found: 2, deleted_sold: 1, deleted_stale: 0 },
        error: null,
      },
    ]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('regular')).toBeInTheDocument();
      expect(screen.getByText(/10 geprüft/)).toBeInTheDocument();
      expect(screen.getByText(/2 verkauft/)).toBeInTheDocument();
      expect(screen.getByText(/1 gelöscht/)).toBeInTheDocument();
    });
  });
});
```

**Step 3: Delete ScrapeButton files**

```bash
rm frontend/src/components/ScrapeButton.tsx
rm frontend/src/components/__tests__/ScrapeButton.test.tsx
```

**Step 4: Run frontend tests**

```bash
cd frontend && npm test -- --run
```

Expected: ScrapeLog tests pass, ScrapeButton tests gone (no failures).

**Step 5: Commit**

```bash
git add frontend/src/components/ScrapeLog.tsx \
        frontend/src/components/__tests__/ScrapeLog.test.tsx
git rm frontend/src/components/ScrapeButton.tsx \
       frontend/src/components/__tests__/ScrapeButton.test.tsx
git commit -m "feat: add ScrapeLog component, remove ScrapeButton"
```

---

## Task 6: App.tsx wiring [ ]

**Depends on:** Task 5

**Files:**
- Modify: `frontend/src/App.tsx`

**Step 1: Replace ScrapeButton with ScrapeLog in App.tsx**

Full replacement of `App.tsx`:

```tsx
import { Routes, Route, Link } from 'react-router-dom';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import PlzBar from './components/PlzBar';
import { useState } from 'react';

function PlaneIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M5 3l14 9-14 9V3z" />
    </svg>
  );
}

function Header() {
  return (
    <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-sm border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
        <Link
          to="/"
          className="flex items-center gap-2 text-brand font-bold text-lg tracking-tight"
        >
          <PlaneIcon />
          RC-Network Scraper
        </Link>
        <ScrapeLog />
      </div>
    </header>
  );
}

export default function App() {
  const [favoritesOpen, setFavoritesOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface text-gray-900 antialiased">
      <Header />
      <PlzBar onOpenFavorites={() => setFavoritesOpen(true)} />
      <main className="max-w-6xl mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<ListingsPage />} />
          <Route path="/listings/:id" element={<DetailPage />} />
        </Routes>
      </main>
      <FavoritesModal open={favoritesOpen} onClose={() => setFavoritesOpen(false)} />
    </div>
  );
}
```

Note: `scrapeKey` prop is removed from `ListingsPage`. Check `ListingsPage.tsx` — if it accepts `scrapeKey` as a prop, remove that prop and its effect. The page no longer auto-refreshes after a manual scrape.

**Step 2: Remove scrapeKey from ListingsPage and useListings hook**

`ListingsPage` has `{ scrapeKey = 0 }: { scrapeKey?: number }` as its prop. `useListings` accepts `reloadKey = 0` and includes it in the `useEffect` dependency array.

In `frontend/src/pages/ListingsPage.tsx`:
```tsx
// Before:
export default function ListingsPage({ scrapeKey = 0 }: { scrapeKey?: number }) {
  const { data, loading, error, filter, setFilter } = useListings(scrapeKey);

// After:
export default function ListingsPage() {
  const { data, loading, error, filter, setFilter } = useListings();
```

In `frontend/src/hooks/useListings.ts`:
```ts
// Before:
export function useListings(reloadKey = 0): UseListingsResult {
// ... useEffect dependency array includes reloadKey at the end

// After:
export function useListings(): UseListingsResult {
// ... remove reloadKey from the useEffect dependency array (line ~107)
```

**Step 3: Type-check and build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Expected: no errors.

**Step 4: Run all frontend tests**

```bash
cd frontend && npm test -- --run
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/ListingsPage.tsx frontend/src/hooks/useListings.ts
git commit -m "feat: wire ScrapeLog into header, remove scrapeKey refresh mechanism"
```

---

## Verification

Run the full test suite:

```bash
docker compose exec backend pytest tests/ -v
cd frontend && npm test -- --run
```

Smoke test the scheduler wiring (backend logs):

```bash
docker compose logs backend --tail=20
```

Expected log line: `Scheduler started — update every 30min, recheck every 1h`

Smoke test the new endpoint:

```bash
curl -s http://localhost:8002/api/scrape/log
```

Expected: `[]` (empty on fresh start)

Manual trigger + verify `job_type` in status + log serialization:

```bash
# Trigger update job
curl -s -X POST http://localhost:8002/api/scrape
# → {"status":"started"}

# While running: verify job_type appears in status
curl -s http://localhost:8002/api/scrape/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['job_type'])"
# → "update"  (or "idle" / "done" if it finished quickly)

# After completion: verify log entry shape
sleep 10
curl -s http://localhost:8002/api/scrape/log | python3 -c "
import sys, json
entries = json.load(sys.stdin)
assert len(entries) >= 1, 'No log entries'
e = entries[0]
assert e['job_type'] == 'update', f'Expected update, got {e[\"job_type\"]}'
assert 'new' in (e.get('summary') or {}), 'summary.new missing'
assert e['error'] is None, f'Unexpected error: {e[\"error\"]}'
print('OK:', e)
"
```

Verify both scheduler jobs registered (test already asserts this, but confirm manually):

```bash
docker compose exec backend python3 -c "
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# Just check the test assertions hold for the production config values
print('30min =', 30*60, 's')
print('1h =', 3600, 's')
print('Confirm test_scheduler.py asserts these intervals — both must pass.')
"
```
