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
    plz: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    """Insert a minimal test listing into the DB."""
    await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, price, condition, shipping,
                description, images, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at)
            VALUES (:eid, :url, :title, :price, NULL, NULL,
                :desc, '[]', 'TestUser', NOW(), NULL, :plz, NULL,
                :lat, :lon, NOW())
        """),
        {
            "eid": external_id,
            "url": f"https://example.com/{external_id}",
            "title": title,
            "price": price,
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
                description, images, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at)
            VALUES (:eid, :url, :title, NULL, NULL, NULL,
                '', '[]', 'TestUser', :posted_at, NULL, NULL, NULL,
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

        response = await api_client.get("/api/listings?sort=price")

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

        response = await api_client.get("/api/listings?sort=price")

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

        response = await api_client.get("/api/listings?sort=distance&plz=80331")

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
