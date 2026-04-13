"""Tests for APScheduler wiring in main.py lifespan."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_lifespan_registers_three_jobs_and_does_not_fire_on_startup():
    """Lifespan startup registers auto_update, auto_recheck, auto_analysis but does NOT fire immediately."""
    from app.main import app

    start_calls = []

    async def fake_start_update_job():
        start_calls.append("update")
        return True

    async def fake_start_recheck_job():
        start_calls.append("recheck")
        return True

    async def fake_run_analysis_job():
        start_calls.append("analysis")

    with patch("app.main.start_update_job", fake_start_update_job), \
         patch("app.main.start_recheck_job", fake_start_recheck_job), \
         patch("app.main.run_analysis_job", fake_run_analysis_job), \
         patch("app.db.init_db", new_callable=AsyncMock):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

            assert start_calls == [], "Jobs must not fire on startup"

            scheduler = app.state.scheduler
            jobs = {j.id: j for j in scheduler.get_jobs()}
            assert set(jobs.keys()) == {"auto_update", "auto_recheck", "auto_analysis"}

            assert jobs["auto_update"].trigger.interval.total_seconds() == 30 * 60
            assert jobs["auto_recheck"].trigger.interval.total_seconds() == 3600
            assert jobs["auto_analysis"].trigger.interval.total_seconds() == 2 * 3600
