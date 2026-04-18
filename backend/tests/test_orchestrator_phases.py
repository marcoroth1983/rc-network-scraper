"""Tests for orchestrator phase functions.

Uses integration-style tests with db_session where possible to avoid
brittle mock chains. Unit tests use targeted mocks only for network calls.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.scraper.orchestrator import (
    _phase1_category,
    _phase1_new_listings,
    _phase2_sold_recheck,
    _phase3_cleanup,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_stops_when_page_fully_known(db_session: AsyncSession):
    """Phase 1 stops after page 1 when all IDs on that page already exist in DB."""
    from app.config import Category
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

    single_cat = [Category(key="flugmodelle", label="Flugmodelle", url="https://www.rc-network.de/forums/biete-flugmodelle.132/")]

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.CATEGORIES", single_cat):
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
    """Phase 1 stops at MAX_PAGES per category even if new listings keep appearing."""
    from app.config import Category
    from app.scraper.orchestrator import MAX_PAGES
    fetch_calls = []

    async def mock_fetch_page(url, client):
        fetch_calls.append(url)
        # Always return a "new" listing — would loop forever without cap
        page_num = len(fetch_calls)
        return [{"external_id": str(page_num * 100), "url": f"https://rc-network.de/t/{page_num * 100}/"}]

    single_cat = [Category(key="flugmodelle", label="Flugmodelle", url="https://www.rc-network.de/forums/biete-flugmodelle.132/")]

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.CATEGORIES", single_cat):

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_category_tags_listing_with_correct_category(db_session: AsyncSession):
    """_phase1_category tags each inserted listing with the category key of the crawled category."""
    from app.config import Category

    cat = Category(key="rc-cars", label="RC-Cars", url="https://www.rc-network.de/forums/biete-rc-cars-funktionsmodelle.146/")
    new_listing = {"external_id": "car-001", "url": "https://rc-network.de/threads/t.car-001/"}

    async def mock_fetch_page(url, client):
        return [new_listing]

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator.parse_detail") as mock_parse:

        mock_parse.return_value = {
            "title": "RC Buggy", "price": None, "condition": None, "shipping": None,
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

        result = await _phase1_category(
            db_session,
            cat,
            update_progress=lambda p: None,
            delay=0.0,
        )

    assert result["new"] == 1

    row = await db_session.execute(
        text("SELECT category FROM listings WHERE external_id = 'car-001'")
    )
    assert row.fetchone()[0] == "rc-cars"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_new_listings_loops_all_categories(db_session: AsyncSession):
    """_phase1_new_listings iterates over all CATEGORIES and tags each listing correctly."""
    from app.config import CATEGORIES, Category

    # Use a single-category patch to keep the test fast
    single_cat = [Category(key="verschenken", label="Zu verschenken", url="https://www.rc-network.de/forums/zu-verschenken.11779439/")]

    new_listing = {"external_id": "gift-001", "url": "https://rc-network.de/threads/t.gift-001/"}

    async def mock_fetch_page(url, client):
        return [new_listing]

    with patch("app.scraper.orchestrator.CATEGORIES", single_cat), \
         patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator.parse_detail") as mock_parse:

        mock_parse.return_value = {
            "title": "Freebie", "price": None, "condition": None, "shipping": None,
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

    assert result["new"] == 1

    row = await db_session.execute(
        text("SELECT category FROM listings WHERE external_id = 'gift-001'")
    )
    assert row.fetchone()[0] == "verschenken"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_marks_sold_listing(db_session: AsyncSession):
    """Phase 2 sets is_sold=True when parser detects sold status."""
    # Insert a non-sold listing
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('sold-test', 'https://rc-network.de/t/999/', 'Selling item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:

        mock_parse.return_value = {"is_sold": True}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html>verkauft</html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        result = await _phase2_sold_recheck(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    assert result["rechecked"] == 1
    assert result["sold_found"] == 1

    # Verify DB was updated
    row = await db_session.execute(
        text("SELECT is_sold FROM listings WHERE external_id = 'sold-test'")
    )
    assert row.fetchone()[0] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_rotates_scraped_at(db_session: AsyncSession):
    """Phase 2 updates scraped_at so listings cycle to end of recheck queue."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('rotate-test', 'https://rc-network.de/t/888/', 'Item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:

        mock_parse.return_value = {"is_sold": False}
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html></html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    row = await db_session.execute(
        text("SELECT scraped_at FROM listings WHERE external_id = 'rotate-test'")
    )
    scraped_at = row.fetchone()[0]
    # scraped_at must be recent (within last 5 seconds)
    from datetime import datetime, timezone, timedelta
    assert scraped_at > datetime.now(timezone.utc) - timedelta(seconds=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase3_strips_images_from_old_sold_listings(db_session: AsyncSession):
    """Phase 3 strips images from sold listings older than 2 weeks, keeps the listing itself."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author,
                              scraped_at, posted_at, is_sold)
        VALUES
            -- Old sold: images should be stripped, listing kept
            ('old-sold', 'https://rc-network.de/t/1/', 'Old sold', '',
             '["https://example.com/img1.jpg", "https://example.com/img2.jpg"]',
             '[]', 'u', '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00', TRUE),
            -- Recent sold: images must NOT be stripped (only 1 day old)
            ('new-sold', 'https://rc-network.de/t/2/', 'New sold', '',
             '["https://example.com/img3.jpg"]',
             '[]', 'u', NOW(), NOW(), TRUE),
            -- Old not-sold with recent posted_at: should NOT be affected (not sold, not stale)
            ('old-active', 'https://rc-network.de/t/3/', 'Old active', '', '[]', '[]', 'u',
             NOW(), NOW(), FALSE)
    """))
    await db_session.commit()

    result = await _phase3_cleanup(db_session)

    assert result["cleaned_sold"] == 1

    remaining = await db_session.execute(
        text("SELECT external_id FROM listings ORDER BY external_id")
    )
    ids = {r[0] for r in remaining.fetchall()}
    assert "old-sold" in ids       # listing still exists
    assert "new-sold" in ids
    assert "old-active" in ids

    old_sold_images = await db_session.execute(
        text("SELECT images FROM listings WHERE external_id = 'old-sold'")
    )
    assert old_sold_images.fetchone()[0] == []

    new_sold_images = await db_session.execute(
        text("SELECT images FROM listings WHERE external_id = 'new-sold'")
    )
    assert new_sold_images.fetchone()[0] == ["https://example.com/img3.jpg"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase3_deletes_stale_listings(db_session: AsyncSession):
    """Phase 3 deletes non-sold listings with posted_at older than 8 weeks."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author,
                              scraped_at, posted_at, is_sold)
        VALUES
            -- Old: should be deleted
            ('stale', 'https://rc-network.de/t/10/', 'Stale', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00', FALSE),
            -- Recent: should NOT be deleted
            ('fresh', 'https://rc-network.de/t/11/', 'Fresh', '', '[]', '[]', 'u',
             NOW(), NOW(), FALSE),
            -- NULL posted_at: should NOT be deleted
            ('nodate', 'https://rc-network.de/t/12/', 'No date', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', NULL, FALSE)
    """))
    await db_session.commit()

    result = await _phase3_cleanup(db_session)

    assert result["deleted_stale"] == 1
    remaining = await db_session.execute(
        text("SELECT external_id FROM listings ORDER BY external_id")
    )
    ids = {r[0] for r in remaining.fetchall()}
    assert "stale" not in ids
    assert "fresh" in ids
    assert "nodate" in ids


# ---------------------------------------------------------------------------
# PLAN-007: Listing lifecycle timestamp tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_created_at_set_on_insert_not_overwritten_on_upsert(db_session: AsyncSession):
    """created_at is stamped on first insert and never overwritten by a subsequent upsert."""
    from app.config import Category
    from app.scraper.orchestrator import _upsert_listing

    scraped_at_first = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _upsert_listing(
        session=db_session,
        external_id="lifecycle-001",
        url="https://rc-network.de/t/lifecycle-001/",
        parsed={
            "title": "Original Title",
            "price": None, "condition": None, "shipping": None,
            "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": False,
            "plz": None, "city": None,
        },
        latitude=None,
        longitude=None,
        scraped_at=scraped_at_first,
        category="flugmodelle",
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT created_at FROM listings WHERE external_id = 'lifecycle-001'")
    )
    created_at_after_insert = row.fetchone()[0]
    assert created_at_after_insert is not None

    # Re-upsert with a different title and a newer scraped_at
    scraped_at_second = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _upsert_listing(
        session=db_session,
        external_id="lifecycle-001",
        url="https://rc-network.de/t/lifecycle-001/",
        parsed={
            "title": "Updated Title",
            "price": None, "condition": None, "shipping": None,
            "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": False,
            "plz": None, "city": None,
        },
        latitude=None,
        longitude=None,
        scraped_at=scraped_at_second,
        category="flugmodelle",
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT created_at, title FROM listings WHERE external_id = 'lifecycle-001'")
    )
    result_row = row.fetchone()
    assert result_row[0] == created_at_after_insert  # created_at unchanged
    assert result_row[1] == "Updated Title"  # title was updated


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_upsert_sets_sold_at_when_is_sold_flips_true(db_session: AsyncSession):
    """Phase 1 upsert sets sold_at when is_sold transitions from FALSE to TRUE."""
    from app.scraper.orchestrator import _upsert_listing

    scraped_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Initial insert: not sold
    await _upsert_listing(
        session=db_session,
        external_id="lifecycle-002",
        url="https://rc-network.de/t/lifecycle-002/",
        parsed={
            "title": "Item For Sale",
            "price": None, "condition": None, "shipping": None,
            "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": False,
            "plz": None, "city": None,
        },
        latitude=None,
        longitude=None,
        scraped_at=scraped_at,
        category="flugmodelle",
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT sold_at FROM listings WHERE external_id = 'lifecycle-002'")
    )
    assert row.fetchone()[0] is None

    # Re-upsert with is_sold=True
    scraped_at_sold = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    await _upsert_listing(
        session=db_session,
        external_id="lifecycle-002",
        url="https://rc-network.de/t/lifecycle-002/",
        parsed={
            "title": "Item For Sale",
            "price": None, "condition": None, "shipping": None,
            "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": True,
            "plz": None, "city": None,
        },
        latitude=None,
        longitude=None,
        scraped_at=scraped_at_sold,
        category="flugmodelle",
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT is_sold, sold_at FROM listings WHERE external_id = 'lifecycle-002'")
    )
    result_row = row.fetchone()
    assert result_row[0] is True
    assert result_row[1] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_path_a_404_sets_sold_at(db_session: AsyncSession):
    """Phase 2 Path A: 404 response marks listing as sold and sets sold_at."""
    import httpx
    from unittest.mock import AsyncMock, patch, MagicMock

    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('p2a-404', 'https://rc-network.de/t/p2a-404/', 'Item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_http.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)
        )
        mock_client_cls.return_value = mock_http

        result = await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    assert result["sold_found"] == 1

    row = await db_session.execute(
        text("SELECT is_sold, sold_at FROM listings WHERE external_id = 'p2a-404'")
    )
    result_row = row.fetchone()
    assert result_row[0] is True
    assert result_row[1] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_path_a_404_does_not_overwrite_existing_sold_at(db_session: AsyncSession):
    """Phase 2 Path A: existing sold_at is not overwritten on subsequent 404."""
    import httpx
    from unittest.mock import AsyncMock, patch, MagicMock

    past_sold_at = datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
    await db_session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, description, images, tags, author,
                                  scraped_at, is_sold, sold_at)
            VALUES ('p2a-idem', 'https://rc-network.de/t/p2a-idem/', 'Item', '', '[]', '[]', 'user',
                    '2026-01-01 00:00:00+00', TRUE, :sold_at)
        """),
        {"sold_at": past_sold_at},
    )
    await db_session.commit()

    with patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator._RECHECK_SQL", new=text(
             "SELECT id, url, external_id FROM listings WHERE external_id = 'p2a-idem'"
         )):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_http.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)
        )
        mock_client_cls.return_value = mock_http

        await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    row = await db_session.execute(
        text("SELECT sold_at FROM listings WHERE external_id = 'p2a-idem'")
    )
    assert row.fetchone()[0] == past_sold_at


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_path_b_parser_sets_sold_at(db_session: AsyncSession):
    """Phase 2 Path B: parser-detected sold sets sold_at."""
    from unittest.mock import AsyncMock, patch, MagicMock

    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('p2b-sold', 'https://rc-network.de/t/p2b-sold/', 'Item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:

        mock_parse.return_value = {"is_sold": True}
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html>verkauft</html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        result = await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    assert result["sold_found"] == 1

    row = await db_session.execute(
        text("SELECT is_sold, sold_at FROM listings WHERE external_id = 'p2b-sold'")
    )
    result_row = row.fetchone()
    assert result_row[0] is True
    assert result_row[1] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_reactivation_retains_sold_at(db_session: AsyncSession):
    """Phase 2 Path B: sold_at is retained when is_sold flips back to FALSE (reactivation)."""
    from unittest.mock import AsyncMock, patch, MagicMock

    past_sold_at = datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
    await db_session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, description, images, tags, author,
                                  scraped_at, is_sold, sold_at)
            VALUES ('p2b-react', 'https://rc-network.de/t/p2b-react/', 'Item', '', '[]', '[]', 'user',
                    '2026-01-01 00:00:00+00', FALSE, :sold_at)
        """),
        {"sold_at": past_sold_at},
    )
    await db_session.commit()

    # Override _RECHECK_SQL so the sold listing (is_sold=FALSE forced back) is picked up
    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator._RECHECK_SQL", new=text(
             "SELECT id, url, external_id FROM listings WHERE external_id = 'p2b-react'"
         )):

        mock_parse.return_value = {"is_sold": False}
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html>active listing</html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    row = await db_session.execute(
        text("SELECT is_sold, sold_at FROM listings WHERE external_id = 'p2b-react'")
    )
    result_row = row.fetchone()
    assert result_row[0] is False       # listing is no longer sold
    assert result_row[1] == past_sold_at  # sold_at is retained
