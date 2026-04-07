"""Tests for scrape_runner state machine."""
import pytest
from unittest.mock import patch, AsyncMock
from app.scrape_runner import get_state, run_scrape_job, reset_state, start_background_job


@pytest.mark.asyncio
async def test_run_scrape_job_transitions_to_done():
    """run_scrape_job transitions: idle → running → done."""
    reset_state()
    assert get_state()["status"] == "idle"

    p1 = {"pages_crawled": 1, "new": 2, "updated": 0}
    p2 = {"rechecked": 10, "sold_found": 1}
    p3 = {"deleted_sold": 0, "deleted_stale": 1}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=p1), \
         patch("app.scrape_runner._phase2_sold_recheck", new_callable=AsyncMock, return_value=p2), \
         patch("app.scrape_runner._phase3_cleanup", new_callable=AsyncMock, return_value=p3), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=mock_session):

        await run_scrape_job()

    state = get_state()
    assert state["status"] == "done"
    assert state["summary"]["new"] == 2
    assert state["summary"]["sold_found"] == 1
    assert state["summary"]["deleted_stale"] == 1
    assert state["started_at"] is not None
    assert state["finished_at"] is not None


@pytest.mark.asyncio
async def test_run_scrape_job_sets_error_on_failure():
    """run_scrape_job sets status=error if a phase raises."""
    reset_state()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scrape_runner._phase1_new_listings",
               new_callable=AsyncMock, side_effect=RuntimeError("DB gone")), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=mock_session):

        await run_scrape_job()

    state = get_state()
    assert state["status"] == "error"
    assert "DB gone" in state["error"]


@pytest.mark.asyncio
async def test_run_scrape_job_noop_when_already_running():
    """run_scrape_job returns immediately if status is already running.

    Note: The check-then-set is synchronous (no await between them), so this
    is safe in a single event loop without a lock.
    """
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock) as mock_p1:
        await run_scrape_job()
        assert not mock_p1.called

    runner._state["status"] = "idle"  # restore


def test_start_background_job_rejects_when_running():
    """start_background_job returns False without creating a task if already running."""
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    result = runner.start_background_job()
    assert result is False

    runner._state["status"] = "idle"  # restore
