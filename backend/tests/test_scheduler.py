"""Tests for APScheduler wiring in main.py lifespan."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_lifespan_registers_job_and_does_not_fire_on_startup():
    """Lifespan startup adds the auto_scrape job but does NOT invoke start_background_job immediately."""
    from app.main import app

    start_bg_called = []

    def fake_start_background_job():
        start_bg_called.append(True)
        return True

    with patch("app.main.start_background_job", fake_start_background_job), \
         patch("app.db.init_db", new_callable=AsyncMock):
        # Drive the lifespan context manually
        async with app.router.lifespan_context(app):
            # Give the event loop a tick — a startup-fired job would execute here.
            # For an interval trigger without next_run_time override APScheduler
            # schedules the first fire via call_later (future), not immediately.
            await asyncio.sleep(0)

            # Verify: job must NOT have run during startup
            assert start_bg_called == [], (
                "start_background_job was called on startup — interval job must not fire immediately"
            )

            # Verify: the job is registered in the running scheduler
            scheduler = app.state.scheduler
            jobs = scheduler.get_jobs()
            assert len(jobs) == 1, f"Expected 1 scheduled job, got {len(jobs)}"

            job = jobs[0]
            assert job.id == "auto_scrape"
            # Interval trigger stores the interval as a timedelta; check hours
            assert job.trigger.interval.total_seconds() == 4 * 3600, (
                f"Expected 4h interval, got {job.trigger.interval}"
            )
