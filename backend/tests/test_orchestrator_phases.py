"""Tests for orchestrator phase functions.

Uses integration-style tests with db_session where possible to avoid
brittle mock chains. Unit tests use targeted mocks only for network calls.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.scraper.orchestrator import _phase1_new_listings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_stops_when_page_fully_known(db_session: AsyncSession):
    """Phase 1 stops after page 1 when all IDs on that page already exist in DB."""
    from app.models import Listing
    from datetime import datetime, timezone

    # Pre-insert two listings so they're "known"
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('111', 'https://rc-network.de/t/111', 'Test 1', '', '[]', '[]', 'user', NOW(), FALSE),
               ('222', 'https://rc-network.de/t/222', 'Test 2', '', '[]', '[]', 'user', NOW(), FALSE)
    """))
    await db_session.commit()

    page1_listings = [
        {"external_id": "111", "url": "https://rc-network.de/threads/t.111/"},
        {"external_id": "222", "url": "https://rc-network.de/threads/t.222/"},
    ]
    fetch_calls = []

    async def mock_fetch_page(url, client):
        fetch_calls.append(url)
        return page1_listings  # always returns same page (would loop without stop-early)

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page):
        result = await _phase1_new_listings(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    # Must have stopped after exactly 1 page (all IDs known)
    assert len(fetch_calls) == 1
    assert result["new"] == 0
    assert result["updated"] == 0
    assert result["pages_crawled"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_respects_max_pages_cap(db_session: AsyncSession):
    """Phase 1 stops at MAX_PAGES even if new listings keep appearing."""
    from app.scraper.orchestrator import MAX_PAGES
    fetch_calls = []

    async def mock_fetch_page(url, client):
        fetch_calls.append(url)
        # Always return a "new" listing — would loop forever without cap
        page_num = len(fetch_calls)
        return [{"external_id": str(page_num * 100), "url": f"https://rc-network.de/t/{page_num * 100}/"}]

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator.parse_detail") as mock_parse:

        mock_parse.return_value = {
            "title": "X", "price": None, "condition": None, "shipping": None,
            "plz": None, "city": None, "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": False,
        }
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html></html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        result = await _phase1_new_listings(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    assert len(fetch_calls) == MAX_PAGES
    assert result["pages_crawled"] == MAX_PAGES
