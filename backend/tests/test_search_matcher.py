"""Tests for the search matcher service."""

import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from app.models import Listing, SavedSearch, SearchNotification
from app.notifications.log_plugin import LogPlugin
from app.notifications.registry import notification_registry
from app.services.search_matcher import check_new_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_listing(
    session: AsyncSession,
    *,
    external_id: str,
    title: str,
    plz: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    category: str = "flugmodelle",
) -> Listing:
    """Build a Listing ORM object (not yet flushed)."""
    now = datetime.now(timezone.utc)
    listing = Listing(
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=title,
        description=title,
        images=[],
        tags=[],
        author="Test",
        plz=plz,
        latitude=lat,
        longitude=lon,
        scraped_at=now,
        category=category,
    )
    session.add(listing)
    return listing


def _make_saved_search(
    session: AsyncSession,
    *,
    user_id: int,
    search: str | None = None,
    plz: str | None = None,
    max_distance: int | None = None,
    is_active: bool = True,
    name: str = "Test Suche",
    category: str | None = None,
) -> SavedSearch:
    """Build a SavedSearch ORM object (not yet flushed)."""
    saved = SavedSearch(
        user_id=user_id,
        name=name,
        search=search,
        plz=plz,
        max_distance=max_distance,
        is_active=is_active,
        category=category,
    )
    session.add(saved)
    return saved


async def _seed_user(session: AsyncSession) -> int:
    """Insert a test user and return their id."""
    result = await session.execute(
        text(
            "INSERT INTO users (google_id, email, name, is_approved) "
            "VALUES ('gid-test', 'test@example.com', 'Test', true) "
            "RETURNING id"
        )
    )
    user_id = result.scalar_one()
    await session.commit()
    return user_id


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_new_ids_returns_zero(db_session: AsyncSession):
    """check_new_matches with empty list → 0, no DB queries needed."""
    result = await check_new_matches(db_session, [])
    assert result == 0


@pytest.mark.asyncio
async def test_inactive_search_is_skipped(db_session: AsyncSession):
    """Inactive saved searches are not processed."""
    user_id = await _seed_user(db_session)

    listing = _make_listing(db_session, external_id="L001", title="Multiplex BK Funray")
    saved = _make_saved_search(db_session, user_id=user_id, search="Multiplex", is_active=False)
    await db_session.flush()
    await db_session.commit()

    result = await check_new_matches(db_session, [listing.id])
    assert result == 0

    count_result = await db_session.execute(text("SELECT COUNT(*) FROM search_notifications"))
    assert count_result.scalar_one() == 0


@pytest.mark.asyncio
async def test_match_by_search_term(db_session: AsyncSession):
    """Saved search 'Multiplex' matches listing with 'Multiplex' in title."""
    user_id = await _seed_user(db_session)

    listing = _make_listing(db_session, external_id="L001", title="Multiplex BK Funray")
    _make_listing(db_session, external_id="L002", title="Graupner Segler")
    saved = _make_saved_search(db_session, user_id=user_id, search="Multiplex")
    await db_session.flush()
    await db_session.commit()

    matches = await check_new_matches(db_session, [listing.id])
    assert matches == 1

    count_result = await db_session.execute(text("SELECT COUNT(*) FROM search_notifications"))
    assert count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_match_by_plz_distance(db_session: AsyncSession):
    """Saved search PLZ 49356 +20km matches nearby listing, excludes distant one."""
    user_id = await _seed_user(db_session)

    # Seed PLZ geodata
    await db_session.execute(
        text("INSERT INTO plz_geodata (plz, city, lat, lon) VALUES ('49356', 'Diepholz', 52.607, 8.371)")
    )
    # PLZ 49393 is nearby Diepholz (~15km)
    await db_session.execute(
        text("INSERT INTO plz_geodata (plz, city, lat, lon) VALUES ('49393', 'Lohne', 52.666, 8.239)")
    )

    nearby = _make_listing(db_session, external_id="L001", title="Segler", plz="49393", lat=52.666, lon=8.239)
    distant = _make_listing(db_session, external_id="L002", title="Segler", lat=48.137, lon=11.576)  # Munich

    saved = _make_saved_search(db_session, user_id=user_id, plz="49356", max_distance=20)
    await db_session.flush()
    await db_session.commit()

    matches = await check_new_matches(db_session, [nearby.id, distant.id])
    assert matches == 1

    notif_result = await db_session.execute(
        text("SELECT listing_id FROM search_notifications")
    )
    notified_ids = [row[0] for row in notif_result.fetchall()]
    assert nearby.id in notified_ids
    assert distant.id not in notified_ids


@pytest.mark.asyncio
async def test_no_duplicate_notifications(db_session: AsyncSession):
    """Running matcher twice with same listings produces notifications only on first run."""
    user_id = await _seed_user(db_session)

    listing = _make_listing(db_session, external_id="L001", title="Multiplex BK Funray")
    _make_saved_search(db_session, user_id=user_id, search="Multiplex")
    await db_session.flush()
    await db_session.commit()

    first = await check_new_matches(db_session, [listing.id])
    second = await check_new_matches(db_session, [listing.id])

    assert first == 1
    assert second == 0

    count_result = await db_session.execute(text("SELECT COUNT(*) FROM search_notifications"))
    assert count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_last_checked_at_updated(db_session: AsyncSession):
    """last_checked_at is updated after matching, even when no new matches found."""
    user_id = await _seed_user(db_session)

    listing = _make_listing(db_session, external_id="L001", title="Graupner")
    saved = _make_saved_search(db_session, user_id=user_id, search="Multiplex")
    await db_session.flush()
    await db_session.commit()

    assert saved.last_checked_at is None

    await check_new_matches(db_session, [listing.id])

    await db_session.refresh(saved)
    assert saved.last_checked_at is not None


# ---------------------------------------------------------------------------
# Integration test with LogPlugin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_plugin_receives_match(db_session: AsyncSession, caplog):
    """Integration: LogPlugin receives match result and logs it."""
    # Register LogPlugin for this test only
    notification_registry._plugins.clear()
    notification_registry.register(LogPlugin())
    try:
        user_id = await _seed_user(db_session)

        listing = _make_listing(db_session, external_id="L001", title="Multiplex BK Funray")
        saved = _make_saved_search(
            db_session, user_id=user_id, search="Multiplex", name="Multiplex Suche"
        )
        await db_session.flush()
        await db_session.commit()

        with caplog.at_level(logging.INFO, logger="app.notifications.log_plugin"):
            matches = await check_new_matches(db_session, [listing.id])

        assert matches == 1
        assert any("Multiplex Suche" in record.message for record in caplog.records)

        count_result = await db_session.execute(text("SELECT COUNT(*) FROM search_notifications"))
        assert count_result.scalar_one() == 1
    finally:
        notification_registry._plugins.clear()


# ---------------------------------------------------------------------------
# Runner integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_update_job_calls_matcher_when_new_ids():
    """run_update_job calls check_new_matches when new_ids is non-empty."""
    from app.scrape_runner import run_update_job, reset_state

    reset_state()
    phase1_result = {"pages_crawled": 1, "new": 2, "updated": 0, "new_ids": [1, 2]}

    def _mock_session():
        s = AsyncMock()
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=None)
        return s

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=phase1_result), \
         patch("app.scrape_runner.check_new_matches", new_callable=AsyncMock, return_value=2) as mock_matcher, \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_update_job()

    mock_matcher.assert_called_once()
    call_args = mock_matcher.call_args
    assert call_args[0][1] == [1, 2]  # new_ids positional arg


@pytest.mark.asyncio
async def test_category_filter_excludes_wrong_category(db_session: AsyncSession):
    """Saved search with category='rc-cars' does not match a listing with category='flugmodelle'."""
    user_id = await _seed_user(db_session)

    flug_listing = _make_listing(
        db_session, external_id="L001", title="Segler", category="flugmodelle"
    )
    car_listing = _make_listing(
        db_session, external_id="L002", title="Buggy", category="rc-cars"
    )
    saved = _make_saved_search(db_session, user_id=user_id, category="rc-cars")
    await db_session.flush()
    await db_session.commit()

    matches = await check_new_matches(db_session, [flug_listing.id, car_listing.id])
    assert matches == 1

    notif_result = await db_session.execute(
        text("SELECT listing_id FROM search_notifications")
    )
    notified_ids = {row[0] for row in notif_result.fetchall()}
    assert flug_listing.id not in notified_ids
    assert car_listing.id in notified_ids


@pytest.mark.asyncio
async def test_category_filter_none_matches_all_categories(db_session: AsyncSession):
    """Saved search with category=None matches listings from any category."""
    user_id = await _seed_user(db_session)

    flug_listing = _make_listing(
        db_session, external_id="L001", title="Segler", category="flugmodelle"
    )
    car_listing = _make_listing(
        db_session, external_id="L002", title="Buggy", category="rc-cars"
    )
    saved = _make_saved_search(db_session, user_id=user_id, category=None)
    await db_session.flush()
    await db_session.commit()

    matches = await check_new_matches(db_session, [flug_listing.id, car_listing.id])
    assert matches == 2


@pytest.mark.asyncio
async def test_run_update_job_skips_matcher_when_no_new_ids():
    """run_update_job does NOT call check_new_matches when new_ids is empty."""
    from app.scrape_runner import run_update_job, reset_state

    reset_state()
    phase1_result = {"pages_crawled": 1, "new": 0, "updated": 5, "new_ids": []}

    def _mock_session():
        s = AsyncMock()
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=None)
        return s

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=phase1_result), \
         patch("app.scrape_runner.check_new_matches", new_callable=AsyncMock) as mock_matcher, \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=_mock_session()):
        await run_update_job()

    mock_matcher.assert_not_called()
