"""Integration tests for the REST API endpoints.

These tests require a running PostgreSQL database (run via Docker Compose).
All tests use the ``api_client`` fixture which wires FastAPI to the test DB
via ``app.dependency_overrides``.

Run with:
    docker compose exec backend pytest tests/test_api.py -v
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scraper.orchestrator import _parse_price_numeric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_listing(
    session: AsyncSession,
    *,
    external_id: str,
    title: str,
    description: str = "",
    price: str | None = None,
    price_numeric: float | None = None,
    plz: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    """Insert a minimal test listing into the DB.

    price_numeric is auto-computed from price when not supplied explicitly.
    """
    computed_price_numeric = price_numeric if price_numeric is not None else _parse_price_numeric(price)
    await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, price, price_numeric, condition, shipping,
                description, images, tags, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at)
            VALUES (:eid, :url, :title, :price, :price_numeric, NULL, NULL,
                :desc, '[]', '[]', 'TestUser', NOW(), NULL, :plz, NULL,
                :lat, :lon, NOW())
        """),
        {
            "eid": external_id,
            "url": f"https://example.com/{external_id}",
            "title": title,
            "price": price,
            "price_numeric": computed_price_numeric,
            "desc": description,
            "plz": plz,
            "lat": lat,
            "lon": lon,
        },
    )
    await session.commit()


async def _insert_listing_with_date(
    session: AsyncSession,
    *,
    external_id: str,
    title: str,
    posted_at: str,
) -> None:
    """Insert a test listing with an explicit posted_at timestamp (ISO 8601 string)."""
    dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, price, condition, shipping,
                description, images, tags, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at)
            VALUES (:eid, :url, :title, NULL, NULL, NULL,
                '', '[]', '[]', 'TestUser', :posted_at, NULL, NULL, NULL,
                NULL, NULL, NOW())
        """),
        {
            "eid": external_id,
            "url": f"https://example.com/{external_id}",
            "title": title,
            "posted_at": dt,
        },
    )
    await session.commit()


async def _seed_plz(
    session: AsyncSession,
    plz: str,
    city: str,
    lat: float,
    lon: float,
) -> None:
    """Insert a PLZ geodata row."""
    await session.execute(
        text(
            "INSERT INTO plz_geodata (plz, city, lat, lon) "
            "VALUES (:plz, :city, :lat, :lon) ON CONFLICT (plz) DO NOTHING"
        ),
        {"plz": plz, "city": city, "lat": lat, "lon": lon},
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Step 3: PLZ resolution endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestResolvePlz:
    async def test_resolve_plz_found(self, api_client: AsyncClient, db_session: AsyncSession) -> None:
        await db_session.execute(
            text(
                "INSERT INTO plz_geodata (plz, city, lat, lon) "
                "VALUES ('80331', 'München', 48.1374, 11.5755)"
            )
        )
        await db_session.commit()

        response = await api_client.get("/api/geo/plz/80331")

        assert response.status_code == 200
        data = response.json()
        assert data["plz"] == "80331"
        assert data["city"] == "München"
        assert isinstance(data["lat"], float)
        assert isinstance(data["lon"], float)

    async def test_resolve_plz_not_found(self, api_client: AsyncClient) -> None:
        response = await api_client.get("/api/geo/plz/00000")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Step 4: Text search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestSearch:
    async def test_search_filters_by_title(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing(db_session, external_id="1", title="Multiplex EasyStar 3")
        await _insert_listing(db_session, external_id="2", title="Unrelated listing")

        response = await api_client.get("/api/listings?search=Multiplex")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert "Multiplex" in data["items"][0]["title"]

    async def test_search_no_match_returns_empty(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing(db_session, external_id="1", title="Some listing")

        response = await api_client.get("/api/listings?search=xyzzy_no_match")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_search_matches_description(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing(
            db_session,
            external_id="1",
            title="Some listing",
            description="This has a unique_keyword_xyz inside",
        )

        response = await api_client.get("/api/listings?search=unique_keyword_xyz")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    async def test_search_is_case_insensitive(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing(db_session, external_id="1", title="Multiplex EasyStar")

        response = await api_client.get("/api/listings?search=multiplex")

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_search_matches_tags(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Search must find listings where the query matches a tag."""
        await db_session.execute(text("""
            INSERT INTO listings (external_id, url, title, description, images, tags,
                author, scraped_at, is_sold)
            VALUES ('tag-test', 'https://example.com/tag-test', 'Some plane', '', '[]',
                    '["dle 111", "pilot rc"]', 'TestUser', NOW(), FALSE)
        """))
        await db_session.commit()

        response = await api_client.get("/api/listings?search=dle+111")
        assert response.status_code == 200
        assert response.json()["total"] == 1


# ---------------------------------------------------------------------------
# Step 5: Sorting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestSorting:
    async def test_sort_by_date_returns_newest_first(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing_with_date(
            db_session, external_id="old", title="Old listing", posted_at="2024-01-01T00:00:00Z"
        )
        await _insert_listing_with_date(
            db_session, external_id="new", title="New listing", posted_at="2024-06-01T00:00:00Z"
        )

        response = await api_client.get("/api/listings?sort=date")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2
        assert items[0]["title"] == "New listing"
        assert items[1]["title"] == "Old listing"

    async def test_sort_by_price_ascending(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing(db_session, external_id="1", title="Cheap", price="50€")
        await _insert_listing(db_session, external_id="2", title="Expensive", price="300€")
        await _insert_listing(db_session, external_id="3", title="NoPrize", price=None)

        response = await api_client.get("/api/listings?sort=price&sort_dir=asc")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 3
        assert items[0]["title"] == "Cheap"
        assert items[1]["title"] == "Expensive"
        assert items[2]["title"] == "NoPrize"

    async def test_sort_by_price_space_thousands_separator(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Prices with space as thousands separator must sort correctly."""
        await _insert_listing(db_session, external_id="1", title="Expensive", price="1 300,00 €")
        await _insert_listing(db_session, external_id="2", title="Cheap", price="25 €")
        await _insert_listing(db_session, external_id="3", title="Mid", price="250 €")

        response = await api_client.get("/api/listings?sort=price&sort_dir=asc")

        assert response.status_code == 200
        items = response.json()["items"]
        assert items[0]["title"] == "Cheap"
        assert items[1]["title"] == "Mid"
        assert items[2]["title"] == "Expensive"

    async def test_sort_distance_without_plz_returns_400(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.get("/api/listings?sort=distance")

        assert response.status_code == 400

    async def test_sort_by_distance_with_plz(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # München ref point
        await _seed_plz(db_session, "80331", "München", 48.1374, 11.5755)
        # Hamburg ~612km away
        await _seed_plz(db_session, "20095", "Hamburg", 53.5753, 10.0153)

        # Listing near München
        await _insert_listing(
            db_session, external_id="munich", title="Near München",
            lat=48.1374, lon=11.5755
        )
        # Listing near Hamburg
        await _insert_listing(
            db_session, external_id="hamburg", title="Near Hamburg",
            lat=53.5753, lon=10.0153
        )

        response = await api_client.get("/api/listings?sort=distance&sort_dir=asc&plz=80331")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2
        assert items[0]["title"] == "Near München"
        assert items[0]["distance_km"] is not None
        assert items[0]["distance_km"] < items[1]["distance_km"]


# ---------------------------------------------------------------------------
# Step 6: Distance filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
class TestDistanceFilter:
    async def test_max_distance_filters_far_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_plz(db_session, "80331", "München", 48.1374, 11.5755)

        # Near: München itself (~0km)
        await _insert_listing(
            db_session, external_id="near", title="Near listing",
            lat=48.1374, lon=11.5755
        )
        # Far: Hamburg (~612km)
        await _insert_listing(
            db_session, external_id="far", title="Far listing",
            lat=53.5753, lon=10.0153
        )

        response = await api_client.get("/api/listings?plz=80331&max_distance=100")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Near listing"

    async def test_max_distance_excludes_listings_without_coords(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listings without coordinates must be excluded when max_distance is active."""
        await _seed_plz(db_session, "80331", "München", 48.1374, 11.5755)

        # Listing with coordinates within range
        await _insert_listing(
            db_session, external_id="near", title="Near listing",
            lat=48.1374, lon=11.5755
        )
        # Listing without coordinates (e.g. Belgium, no German PLZ)
        await _insert_listing(
            db_session, external_id="nocoords", title="No coordinates listing",
            lat=None, lon=None
        )

        response = await api_client.get("/api/listings?plz=80331&max_distance=100")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Near listing"

    async def test_max_distance_requires_plz(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.get("/api/listings?max_distance=100")

        assert response.status_code == 400

    async def test_distance_shown_when_sort_date_and_plz_provided(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Distance must be computed for page items even when sort=date."""
        await _seed_plz(db_session, "80331", "München", 48.1374, 11.5755)
        await _insert_listing(
            db_session, external_id="near", title="Near München",
            lat=48.1374, lon=11.5755
        )
        await _insert_listing(
            db_session, external_id="nocoord", title="No coordinates",
            lat=None, lon=None
        )

        response = await api_client.get("/api/listings?sort=date&plz=80331")

        assert response.status_code == 200
        items = response.json()["items"]
        near = next(i for i in items if i["external_id"] == "near")
        nocoord = next(i for i in items if i["external_id"] == "nocoord")
        assert near["distance_km"] is not None
        assert near["distance_km"] < 1  # same location
        assert nocoord["distance_km"] is None  # no coords → no distance

    async def test_total_reflects_distance_filter(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_plz(db_session, "80331", "München", 48.1374, 11.5755)

        # Two near listings (München area)
        await _insert_listing(
            db_session, external_id="near1", title="Near 1",
            lat=48.1374, lon=11.5755
        )
        await _insert_listing(
            db_session, external_id="near2", title="Near 2",
            lat=48.2, lon=11.6
        )
        # One far listing (Hamburg)
        await _insert_listing(
            db_session, external_id="far", title="Far",
            lat=53.5753, lon=10.0153
        )

        response = await api_client.get("/api/listings?plz=80331&max_distance=100")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2


# ---------------------------------------------------------------------------
# Task 7: Scrape endpoints + Favorites
# ---------------------------------------------------------------------------

async def _insert_listing_full(
    session: AsyncSession,
    *,
    external_id: str,
    title: str = "Test",
    is_sold: bool = False,
    lat: float | None = None,
    lon: float | None = None,
) -> int:
    """Insert a listing and return its auto-incremented id."""
    result = await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, price, condition, shipping,
                description, images, tags, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at, is_sold)
            VALUES (:eid, :url, :title, NULL, NULL, NULL,
                '', '[]', '[]', 'TestUser', NOW(), NULL, NULL, NULL,
                :lat, :lon, NOW(), :is_sold)
            RETURNING id
        """),
        {
            "eid": external_id, "url": f"https://example.com/{external_id}",
            "title": title, "lat": lat, "lon": lon,
            "is_sold": is_sold,
        },
    )
    await session.commit()
    return result.fetchone()[0]


async def _seed_test_user(session: AsyncSession, user_id: int = 1) -> None:
    """Insert the fake user row required for user_favorites FK constraints."""
    await session.execute(
        text(
            "INSERT INTO users (id, google_id, email, name, is_approved) "
            "VALUES (:uid, 'test-google-id', 'test@example.com', 'Test User', true) "
            "ON CONFLICT DO NOTHING"
        ),
        {"uid": user_id},
    )
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
class TestScrapeEndpoints:
    async def test_start_scrape_returns_202(self, api_client: AsyncClient) -> None:
        """POST /api/scrape starts background job and returns 202."""
        from unittest.mock import patch, AsyncMock
        with patch("app.api.routes.start_update_job", new_callable=AsyncMock, return_value=True):
            resp = await api_client.post("/api/scrape")
        assert resp.status_code == 202
        assert resp.json()["status"] == "started"

    async def test_start_scrape_returns_409_when_running(
        self, api_client: AsyncClient
    ) -> None:
        """POST /api/scrape returns 409 if already running."""
        from unittest.mock import patch, AsyncMock
        with patch("app.api.routes.start_update_job", new_callable=AsyncMock, return_value=False):
            resp = await api_client.post("/api/scrape")
        assert resp.status_code == 409

    async def test_scrape_status_returns_idle(self, api_client: AsyncClient) -> None:
        """GET /api/scrape/status returns current state."""
        from app.scrape_runner import reset_state
        reset_state()
        resp = await api_client.get("/api/scrape/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"

    async def test_scrape_log_returns_empty_initially(self, api_client: AsyncClient) -> None:
        """GET /api/scrape/log returns empty list on fresh start."""
        from app.scrape_runner import reset_state
        reset_state()
        resp = await api_client.get("/api/scrape/log")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
@pytest.mark.integration
class TestFavorites:
    async def test_toggle_favorite_inserts_into_user_favorites(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_test_user(db_session)
        listing_id = await _insert_listing_full(db_session, external_id="fav1")

        resp = await api_client.patch(
            f"/api/listings/{listing_id}/favorite?is_favorite=true"
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True

        # Verify the row exists in user_favorites
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM user_favorites WHERE user_id = 1 AND listing_id = :lid"),
            {"lid": listing_id},
        )
        assert result.scalar_one() == 1

    async def test_toggle_favorite_removes_from_user_favorites(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_test_user(db_session)
        listing_id = await _insert_listing_full(db_session, external_id="fav-clear")

        # Insert directly into user_favorites
        await db_session.execute(
            text("INSERT INTO user_favorites (user_id, listing_id) VALUES (1, :lid)"),
            {"lid": listing_id},
        )
        await db_session.commit()

        resp = await api_client.patch(
            f"/api/listings/{listing_id}/favorite?is_favorite=false"
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is False

        result = await db_session.execute(
            text("SELECT COUNT(*) FROM user_favorites WHERE user_id = 1 AND listing_id = :lid"),
            {"lid": listing_id},
        )
        assert result.scalar_one() == 0

    async def test_toggle_favorite_404_for_unknown(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_test_user(db_session)
        resp = await api_client.patch("/api/listings/999999/favorite?is_favorite=true")
        assert resp.status_code == 404

    async def test_get_favorites_returns_only_user_favorites(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_test_user(db_session)
        listing_a = await _insert_listing_full(db_session, external_id="favA")
        await _insert_listing_full(db_session, external_id="favB")

        # Only listing A is favorited by the test user
        await db_session.execute(
            text("INSERT INTO user_favorites (user_id, listing_id) VALUES (1, :lid)"),
            {"lid": listing_a},
        )
        await db_session.commit()

        resp = await api_client.get("/api/favorites")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["external_id"] == "favA"
        assert items[0]["is_favorite"] is True

    async def test_get_favorites_includes_sold_status(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_test_user(db_session)
        listing_id = await _insert_listing_full(
            db_session, external_id="favSold", is_sold=True
        )
        await db_session.execute(
            text("INSERT INTO user_favorites (user_id, listing_id) VALUES (1, :lid)"),
            {"lid": listing_id},
        )
        await db_session.commit()

        resp = await api_client.get("/api/favorites")
        assert resp.status_code == 200
        assert resp.json()[0]["is_sold"] is True


# ---------------------------------------------------------------------------
# Step 13 (Plan 013): Categories endpoint + category filter
# ---------------------------------------------------------------------------

async def _insert_listing_with_category(
    session: AsyncSession,
    *,
    external_id: str,
    title: str,
    category: str,
) -> None:
    """Insert a minimal test listing with an explicit category."""
    await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, description, images, tags,
                author, scraped_at, is_sold, category)
            VALUES (:eid, :url, :title, '', '[]', '[]', 'TestUser', NOW(), FALSE, :category)
        """),
        {
            "eid": external_id,
            "url": f"https://example.com/{external_id}",
            "title": title,
            "category": category,
        },
    )
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
class TestCategoriesEndpoint:
    async def test_get_categories_returns_all_seven(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /api/categories returns all 7 categories."""
        resp = await api_client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 7
        keys = {item["key"] for item in data}
        assert keys == {
            "flugmodelle", "schiffsmodelle", "antriebstechnik",
            "rc-elektronik", "rc-cars", "einzelteile", "verschenken",
        }

    async def test_get_categories_counts_reflect_db_state(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Category counts match the actual DB contents."""
        await _insert_listing_with_category(db_session, external_id="f1", title="Flugmodell 1", category="flugmodelle")
        await _insert_listing_with_category(db_session, external_id="f2", title="Flugmodell 2", category="flugmodelle")
        await _insert_listing_with_category(db_session, external_id="r1", title="RC-Car 1", category="rc-cars")

        resp = await api_client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        count_by_key = {item["key"]: item["count"] for item in data}
        assert count_by_key["flugmodelle"] == 2
        assert count_by_key["rc-cars"] == 1
        assert count_by_key["schiffsmodelle"] == 0

    async def test_get_categories_has_label_field(
        self, api_client: AsyncClient
    ) -> None:
        """Each category entry has key, label, and count fields."""
        resp = await api_client.get("/api/categories")
        assert resp.status_code == 200
        for item in resp.json():
            assert "key" in item
            assert "label" in item
            assert "count" in item


@pytest.mark.asyncio
@pytest.mark.integration
class TestCategoryFilter:
    async def test_filter_by_category_returns_matching_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /api/listings?category=flugmodelle only returns flugmodelle listings."""
        await _insert_listing_with_category(db_session, external_id="fly1", title="Segler", category="flugmodelle")
        await _insert_listing_with_category(db_session, external_id="car1", title="Buggy", category="rc-cars")

        resp = await api_client.get("/api/listings?category=flugmodelle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["external_id"] == "fly1"

    async def test_filter_by_category_all_returns_all_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /api/listings?category=all returns all listings regardless of category."""
        await _insert_listing_with_category(db_session, external_id="fly1", title="Segler", category="flugmodelle")
        await _insert_listing_with_category(db_session, external_id="car1", title="Buggy", category="rc-cars")

        resp = await api_client.get("/api/listings?category=all")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_filter_by_unknown_category_returns_400(
        self, api_client: AsyncClient
    ) -> None:
        """GET /api/listings?category=unknown returns 400."""
        resp = await api_client.get("/api/listings?category=unknown")
        assert resp.status_code == 400

    async def test_no_category_param_returns_all_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /api/listings without category param returns all listings."""
        await _insert_listing_with_category(db_session, external_id="fly1", title="Segler", category="flugmodelle")
        await _insert_listing_with_category(db_session, external_id="ship1", title="Yacht", category="schiffsmodelle")

        resp = await api_client.get("/api/listings")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_listing_response_includes_category_field(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listing items in response include the category field."""
        await _insert_listing_with_category(
            db_session, external_id="fly1", title="Segler", category="flugmodelle"
        )
        resp = await api_client.get("/api/listings")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["category"] == "flugmodelle"


# ---------------------------------------------------------------------------
# PLAN-014 Step 4: Price indicator
# ---------------------------------------------------------------------------

async def _insert_listing_analyzed(
    session: AsyncSession,
    *,
    external_id: str,
    title: str = "Test listing",
    price_numeric: float | None = None,
    manufacturer: str | None = None,
    model_name: str | None = None,
    category: str = "flugmodelle",
    is_sold: bool = False,
) -> int:
    """Insert a listing with analysis fields set, returning the auto-incremented id."""
    result = await session.execute(
        text("""
            INSERT INTO listings (
                external_id, url, title, price, price_numeric, condition, shipping,
                description, images, tags, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at, is_sold, category,
                manufacturer, model_name, analyzed_at
            ) VALUES (
                :eid, :url, :title, NULL, :price_numeric, NULL, NULL,
                '', '[]', '[]', 'TestUser', NOW(), NULL, NULL, NULL,
                NULL, NULL, NOW(), :is_sold, :category,
                :manufacturer, :model_name, NOW()
            ) RETURNING id
        """),
        {
            "eid": external_id,
            "url": f"https://example.com/{external_id}",
            "title": title,
            "price_numeric": price_numeric,
            "is_sold": is_sold,
            "category": category,
            "manufacturer": manufacturer,
            "model_name": model_name,
        },
    )
    await session.commit()
    return result.fetchone()[0]


@pytest.mark.asyncio
@pytest.mark.integration
class TestPriceIndicator:
    async def test_bargain_indicator_when_price_below_p25(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listing priced below p25 of sold comparables gets price_indicator='bargain'."""
        # Insert 3 sold comparables: 200, 300, 400 → p25=250, median=300, p75=350
        for i, price in enumerate([200.0, 300.0, 400.0]):
            await _insert_listing_analyzed(
                db_session,
                external_id=f"sold-{i}",
                price_numeric=price,
                manufacturer="Multiplex",
                model_name="EasyStar 3",
                category="flugmodelle",
                is_sold=True,
            )
        # Active listing priced at 100 (below p25=250)
        listing_id = await _insert_listing_analyzed(
            db_session,
            external_id="active-cheap",
            price_numeric=100.0,
            manufacturer="Multiplex",
            model_name="EasyStar 3",
            category="flugmodelle",
            is_sold=False,
        )

        # Test via list endpoint
        resp = await api_client.get("/api/listings")
        assert resp.status_code == 200
        items = resp.json()["items"]
        active = next(i for i in items if i["external_id"] == "active-cheap")
        assert active["price_indicator"] == "bargain"
        assert active["price_indicator_median"] is not None
        assert active["price_indicator_sample"] == 3

        # Test via detail endpoint
        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["price_indicator"] == "bargain"
        assert detail["price_indicator_sample"] == 3

    async def test_expensive_indicator_when_price_above_p75(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listing priced above p75 of sold comparables gets price_indicator='expensive'."""
        for i, price in enumerate([200.0, 300.0, 400.0]):
            await _insert_listing_analyzed(
                db_session,
                external_id=f"sold-{i}",
                price_numeric=price,
                manufacturer="Black Horse",
                model_name="L-39",
                category="flugmodelle",
                is_sold=True,
            )
        listing_id = await _insert_listing_analyzed(
            db_session,
            external_id="active-expensive",
            price_numeric=999.0,
            manufacturer="Black Horse",
            model_name="L-39",
            category="flugmodelle",
            is_sold=False,
        )

        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["price_indicator"] == "expensive"

    async def test_fair_indicator_when_price_between_p25_and_p75(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listing priced between p25 and p75 gets price_indicator='fair'."""
        for i, price in enumerate([200.0, 300.0, 400.0]):
            await _insert_listing_analyzed(
                db_session,
                external_id=f"sold-{i}",
                price_numeric=price,
                manufacturer="FMS",
                model_name="P-47",
                category="flugmodelle",
                is_sold=True,
            )
        listing_id = await _insert_listing_analyzed(
            db_session,
            external_id="active-fair",
            price_numeric=300.0,
            manufacturer="FMS",
            model_name="P-47",
            category="flugmodelle",
            is_sold=False,
        )

        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["price_indicator"] == "fair"

    async def test_no_indicator_when_fewer_than_3_comparables(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """price_indicator is null when fewer than 3 sold comparables exist."""
        # Only 2 sold comparables — below minimum
        for i, price in enumerate([200.0, 400.0]):
            await _insert_listing_analyzed(
                db_session,
                external_id=f"sold-{i}",
                price_numeric=price,
                manufacturer="Robbe",
                model_name="Arcus",
                category="flugmodelle",
                is_sold=True,
            )
        listing_id = await _insert_listing_analyzed(
            db_session,
            external_id="active-few",
            price_numeric=300.0,
            manufacturer="Robbe",
            model_name="Arcus",
            category="flugmodelle",
            is_sold=False,
        )

        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["price_indicator"] is None
        assert resp.json()["price_indicator_sample"] is None

    async def test_no_indicator_when_manufacturer_or_model_null(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """price_indicator is null for unanalyzed listings (manufacturer/model_name null)."""
        listing_id = await _insert_listing_full(
            db_session, external_id="unanalyzed", title="No analysis"
        )

        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["price_indicator"] is None

    async def test_no_indicator_when_listing_has_no_price(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """price_indicator is null when the listing itself has no price_numeric."""
        for i, price in enumerate([200.0, 300.0, 400.0]):
            await _insert_listing_analyzed(
                db_session,
                external_id=f"sold-{i}",
                price_numeric=price,
                manufacturer="Graupner",
                model_name="ASK-21",
                category="flugmodelle",
                is_sold=True,
            )
        listing_id = await _insert_listing_analyzed(
            db_session,
            external_id="active-noprice",
            price_numeric=None,
            manufacturer="Graupner",
            model_name="ASK-21",
            category="flugmodelle",
            is_sold=False,
        )

        resp = await api_client.get(f"/api/listings/{listing_id}")
        assert resp.status_code == 200
        assert resp.json()["price_indicator"] is None
