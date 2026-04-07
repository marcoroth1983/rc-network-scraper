"""Integration tests for the scrape orchestration flow.

These tests require a running PostgreSQL database (run via Docker Compose).

Note: The old monolithic run_scrape was replaced by phase functions in Task 3 of
PLAN_004. The detailed insert/upsert/freshness tests now live in
test_orchestrator_phases.py. This file retains a shim-contract test to ensure
routes.py can still import and call run_scrape without errors.

Run with:
    docker compose exec backend pytest tests/test_orchestration.py -v
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.scraper.orchestrator import run_scrape


@pytest.mark.asyncio
@pytest.mark.integration
async def test_run_scrape_shim_returns_zero_summary(db_session: AsyncSession):
    """run_scrape shim returns a zero-filled summary dict without touching the DB."""
    summary = await run_scrape(db_session, max_pages=1)
    assert summary["pages_crawled"] == 0
    assert summary["listings_found"] == 0
    assert summary["new"] == 0
    assert summary["updated"] == 0
    assert summary["skipped"] == 0
