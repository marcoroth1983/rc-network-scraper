"""Integration tests for the scrape orchestration flow.

These tests require a running PostgreSQL database (run via Docker Compose).
They mock all HTTP calls — no live network requests are made.

Run with:
    docker compose exec backend pytest tests/test_orchestration.py -v
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text

from app.scraper.orchestrator import run_scrape

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text(encoding="utf-8")


# external_ids present in overview_page.html
_OVERVIEW_LISTINGS = [
    {"external_id": "12345", "url": "https://www.rc-network.de/threads/biete-multiplex-easystar-3-komplett.12345/"},
    {"external_id": "67890", "url": "https://www.rc-network.de/threads/skywalker-1900-mit-fpv-ausruestung.67890/"},
    {"external_id": "11111", "url": "https://www.rc-network.de/threads/hangar-9-pawnee-balsabausatz.11111/"},
    {"external_id": "22222", "url": "https://www.rc-network.de/threads/e-flite-apprentice-rtf-set.22222/"},
    {"external_id": "33333", "url": "https://www.rc-network.de/threads/volantex-ranger-ex-fpv-flieger.33333/"},
]

# Only listing 12345 has a detailed fixture; all others use the same HTML so
# the parser still returns a valid (but minimal) result.
_DETAIL_HTML = _load_fixture("detail_complete.html")

# PLZ found in detail_complete.html → 80331, München
_TEST_PLZ = "80331"
_TEST_LAT = 48.1374
_TEST_LON = 11.5755


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(html: str, status_code: int = 200) -> httpx.Response:
    """Build a minimal httpx.Response with text content and a required request object."""
    request = httpx.Request("GET", "https://www.rc-network.de/threads/test.12345/")
    return httpx.Response(
        status_code=status_code,
        content=html.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
        request=request,
    )


async def _count_listings(session) -> int:
    result = await session.execute(text("SELECT COUNT(*) FROM listings"))
    return result.scalar()


async def _seed_plz(session) -> None:
    """Insert one PLZ row so geo enrichment can be tested."""
    await session.execute(
        text(
            "INSERT INTO plz_geodata (plz, city, lat, lon) "
            "VALUES (:plz, :city, :lat, :lon) "
            "ON CONFLICT (plz) DO NOTHING"
        ),
        {"plz": _TEST_PLZ, "city": "München", "lat": _TEST_LAT, "lon": _TEST_LON},
    )
    await session.commit()


async def _get_listing(session, external_id: str):
    result = await session.execute(
        text("SELECT * FROM listings WHERE external_id = :eid"),
        {"eid": external_id},
    )
    return result.mappings().fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestOrchestrationInsert:
    """Basic insert: run orchestrator, assert listings land in DB."""

    async def test_listings_inserted(self, db_session):
        """Running the orchestrator inserts all crawled listings into the DB."""
        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=_OVERVIEW_LISTINGS,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            summary = await run_scrape(db_session, max_pages=1)

        count = await _count_listings(db_session)
        assert count == len(_OVERVIEW_LISTINGS)
        assert summary["new"] == len(_OVERVIEW_LISTINGS)
        assert summary["updated"] == 0
        assert summary["skipped"] == 0
        assert summary["listings_found"] == len(_OVERVIEW_LISTINGS)

    async def test_fields_populated_correctly(self, db_session):
        """Parsed fields from detail_complete.html are stored correctly."""
        single_listing = [_OVERVIEW_LISTINGS[0]]  # external_id=12345

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            await run_scrape(db_session, max_pages=1)

        row = await _get_listing(db_session, "12345")
        assert row is not None
        assert row["title"] == "Biete Multiplex EasyStar 3 komplett"
        assert row["price"] == "150€"
        assert row["condition"] == "Neuwertig"
        assert row["shipping"] == "DHL 5€"
        assert row["author"] == "TestUser"
        assert row["plz"] == "80331"
        assert row["city"] == "München"
        assert row["external_id"] == "12345"
        # scraped_at must be recent (within last 60 seconds)
        assert row["scraped_at"] is not None
        age = datetime.now(timezone.utc) - row["scraped_at"]
        assert age.total_seconds() < 60

    async def test_lat_lon_populated_when_plz_found(self, db_session):
        """latitude/longitude are set when PLZ exists in plz_geodata."""
        await _seed_plz(db_session)
        single_listing = [_OVERVIEW_LISTINGS[0]]  # PLZ 80331

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            await run_scrape(db_session, max_pages=1)

        row = await _get_listing(db_session, "12345")
        assert row is not None
        assert abs(row["latitude"] - _TEST_LAT) < 0.001
        assert abs(row["longitude"] - _TEST_LON) < 0.001

    async def test_lat_lon_null_when_plz_missing(self, db_session):
        """latitude/longitude remain NULL when PLZ is not in plz_geodata."""
        # Do NOT seed PLZ row → geo lookup should return (None, None)
        single_listing = [_OVERVIEW_LISTINGS[0]]

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            await run_scrape(db_session, max_pages=1)

        row = await _get_listing(db_session, "12345")
        assert row is not None
        assert row["latitude"] is None
        assert row["longitude"] is None


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrchestrationUpsert:
    """Upsert correctness: re-running must not create duplicates."""

    async def test_no_duplicates_on_rerun(self, db_session):
        """Running the orchestrator twice with the same data must not duplicate rows."""
        single_listing = [_OVERVIEW_LISTINGS[0]]

        mock_kwargs = dict(
            new_callable=AsyncMock,
            return_value=_make_http_response(_DETAIL_HTML),
        )

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(httpx.AsyncClient, "get", **mock_kwargs),
        ):
            # First run — inserts
            summary1 = await run_scrape(db_session, max_pages=1, fresh_threshold_days=0)

        # After first run, fresh_threshold_days=0 means ALL listings are considered
        # stale immediately — so second run will re-scrape and update (not insert).
        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(httpx.AsyncClient, "get", **mock_kwargs),
        ):
            summary2 = await run_scrape(db_session, max_pages=1, fresh_threshold_days=0)

        count = await _count_listings(db_session)
        assert count == 1, f"Expected 1 row after re-run, got {count}"
        assert summary1["new"] == 1
        assert summary2["new"] == 0
        assert summary2["updated"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrchestrationFreshnessStaleness:
    """Fresh listings are skipped; stale listings are re-scraped."""

    async def _insert_listing_with_scraped_at(
        self, session, scraped_at: datetime
    ) -> None:
        """Insert the listing from detail_complete.html with a given scraped_at."""
        await session.execute(
            text("""
                INSERT INTO listings (
                    external_id, url, title, price, condition, shipping,
                    description, images, tags, author, posted_at, posted_at_raw,
                    plz, city, latitude, longitude, scraped_at
                ) VALUES (
                    '12345',
                    'https://www.rc-network.de/threads/biete-multiplex-easystar-3-komplett.12345/',
                    'Biete Multiplex EasyStar 3 komplett',
                    '150€', 'Neuwertig', 'DHL 5€',
                    'Some description.', '[]'::jsonb, '[]'::jsonb, 'TestUser',
                    NULL, NULL, '80331', 'München', NULL, NULL,
                    :scraped_at
                )
            """),
            {"scraped_at": scraped_at},
        )
        await session.commit()

    async def test_fresh_listing_is_skipped(self, db_session):
        """A listing scraped within fresh_threshold_days must not be re-fetched."""
        # Insert as freshly scraped (1 minute ago)
        fresh_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        await self._insert_listing_with_scraped_at(db_session, fresh_time)

        single_listing = [_OVERVIEW_LISTINGS[0]]
        mock_get = AsyncMock(return_value=_make_http_response(_DETAIL_HTML))

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(httpx.AsyncClient, "get", mock_get),
        ):
            summary = await run_scrape(db_session, max_pages=1, fresh_threshold_days=7)

        # HTTP GET for detail page must NOT have been called
        mock_get.assert_not_called()
        assert summary["skipped"] == 1
        assert summary["new"] == 0
        assert summary["updated"] == 0

    async def test_stale_listing_is_rescraped(self, db_session):
        """A listing older than fresh_threshold_days must be re-scraped and updated."""
        # Insert as stale (scraped 10 days ago)
        stale_time = datetime.now(timezone.utc) - timedelta(days=10)
        await self._insert_listing_with_scraped_at(db_session, stale_time)

        single_listing = [_OVERVIEW_LISTINGS[0]]

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=single_listing,
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            summary = await run_scrape(db_session, max_pages=1, fresh_threshold_days=7)

        assert summary["updated"] == 1
        assert summary["new"] == 0

        # scraped_at must be updated to a recent timestamp
        row = await _get_listing(db_session, "12345")
        assert row is not None
        age = datetime.now(timezone.utc) - row["scraped_at"]
        assert age.total_seconds() < 60, (
            f"scraped_at was not updated — age is {age.total_seconds():.0f}s"
        )

    async def test_stale_scraped_at_updated(self, db_session):
        """After re-scraping a stale listing, scraped_at is newer than before."""
        stale_time = datetime.now(timezone.utc) - timedelta(days=10)
        await self._insert_listing_with_scraped_at(db_session, stale_time)

        with (
            patch(
                "app.scraper.orchestrator.fetch_listings",
                new_callable=AsyncMock,
                return_value=[_OVERVIEW_LISTINGS[0]],
            ),
            patch(
                "app.scraper.orchestrator.settings",
                SCRAPE_DELAY=0.0,
            ),
            patch.object(
                httpx.AsyncClient,
                "get",
                new_callable=AsyncMock,
                return_value=_make_http_response(_DETAIL_HTML),
            ),
        ):
            await run_scrape(db_session, max_pages=1, fresh_threshold_days=7)

        row = await _get_listing(db_session, "12345")
        assert row is not None
        assert row["scraped_at"] > stale_time
