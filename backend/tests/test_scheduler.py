"""Tests for APScheduler wiring in main.py lifespan."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_lifespan_registers_jobs_and_does_not_fire_on_startup():
    """Lifespan startup registers all scheduler jobs but does NOT fire immediately."""
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

    async def fake_recalculate_price_indicators():
        start_calls.append("price_indicator")

    with patch("app.main.start_update_job", fake_start_update_job), \
         patch("app.main.start_recheck_job", fake_start_recheck_job), \
         patch("app.main.run_analysis_job", fake_run_analysis_job), \
         patch("app.main.recalculate_price_indicators", fake_recalculate_price_indicators), \
         patch("app.db.init_db", new_callable=AsyncMock):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

            assert start_calls == [], "Jobs must not fire on startup"

            scheduler = app.state.scheduler
            jobs = {j.id: j for j in scheduler.get_jobs()}
            assert {"auto_update", "auto_recheck", "auto_analysis", "price_indicator_recalc"} <= set(jobs.keys())

            assert jobs["auto_update"].trigger.interval.total_seconds() == 30 * 60
            assert jobs["auto_recheck"].trigger.interval.total_seconds() == 3600
            assert jobs["auto_analysis"].trigger.interval.total_seconds() == 2 * 60
            assert jobs["price_indicator_recalc"].trigger.interval.total_seconds() == 15 * 60
