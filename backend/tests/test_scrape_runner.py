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
