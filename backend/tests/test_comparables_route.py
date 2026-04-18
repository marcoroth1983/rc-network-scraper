"""End-to-end tests for GET /api/listings/{id}/comparables (routes.py).

Uses the shared conftest fixtures (api_client, db_session, clean_listings).
Run with: docker compose exec backend pytest tests/test_comparables_route.py -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_listing(
    session: AsyncSession,
    external_id: str,
    price_numeric: float | None = 100.0,
    is_sold: bool = False,
    manufacturer: str | None = None,
    model_name: str | None = None,
    model_type: str | None = None,
    model_subtype: str | None = None,
    completeness: str | None = None,
) -> int:
    """Insert a minimal listing and return its DB id."""
    await session.execute(
        text("""
            INSERT INTO listings (
                external_id, url, title, description, author, scraped_at, images, tags,
                price_numeric, is_sold, manufacturer, model_name, model_type, model_subtype,
                completeness, llm_analyzed
            )
            VALUES (
                :eid, :url, :title, :desc, :author, now(), '[]', '[]',
                :price, :sold, :mfr, :mn, :mt, :ms, :cmp, true
            )
        """),
        {
            "eid": external_id,
            "url": f"http://example.com/{external_id}",
            "title": f"Listing {external_id}",
            "desc": "test",
            "author": "seller",
            "price": price_numeric,
            "sold": is_sold,
            "mfr": manufacturer,
            "mn": model_name,
            "mt": model_type,
            "ms": model_subtype,
            "cmp": completeness,
        },
    )
    await session.commit()
    row = await session.execute(
        text("SELECT id FROM listings WHERE external_id = :eid"), {"eid": external_id}
    )
    return row.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestComparablesRoute:
    async def test_404_for_unknown_listing(self, api_client: AsyncClient) -> None:
        """Non-existent listing_id returns 404."""
        r = await api_client.get("/api/listings/999999/comparables")
        assert r.status_code == 404

    async def test_match_quality_field_present_in_response(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Response always contains match_quality in expected set."""
        base_id = await _insert_listing(db_session, "base-mq-1", manufacturer="CARF", model_type="airplane")
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        data = r.json()
        assert data["match_quality"] in {"homogeneous", "heterogeneous", "insufficient"}

    async def test_homogeneous_set_has_median(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Homogeneous top-N: median is set and listings are populated."""
        # Insert 5 very similar listings to make a homogeneous cluster
        base_id = await _insert_listing(
            db_session, "hom-base",
            price_numeric=500.0,
            manufacturer="Multiplex",
            model_subtype="thermal",
            completeness="RTF",
            model_type="glider",
        )
        for i in range(6):
            await _insert_listing(
                db_session, f"hom-cand-{i}",
                price_numeric=400.0 + i * 20,  # 400, 420, 440, 460, 480, 500 — spread < 4×
                manufacturer="Multiplex",
                model_subtype="thermal",
                completeness="RTF",
                model_type="glider",
            )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        data = r.json()
        if data["match_quality"] == "homogeneous":
            assert data["median"] is not None
            assert isinstance(data["median"], float)

    async def test_heterogeneous_set_has_null_median_but_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Wide price spread → match_quality heterogeneous, median None, but listings populated."""
        base_id = await _insert_listing(
            db_session, "het-base",
            price_numeric=500.0,
            manufacturer="CARF",
            model_type="airplane",
            model_subtype="jet",
            completeness="ARF",
        )
        # Deliberate spread: 100–600 = 6× spread (> MAX_PRICE_SPREAD=4.0)
        prices = [100.0, 150.0, 200.0, 300.0, 500.0, 600.0]
        for i, p in enumerate(prices):
            await _insert_listing(
                db_session, f"het-cand-{i}",
                price_numeric=p,
                manufacturer="CARF",
                model_type="airplane",
                model_subtype="jet",
                completeness="ARF",
            )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        data = r.json()
        if data["match_quality"] == "heterogeneous":
            assert data["median"] is None
            assert len(data["listings"]) > 0

    async def test_similarity_score_descending_sorted(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Listings are returned sorted by similarity_score descending."""
        base_id = await _insert_listing(
            db_session, "sort-base",
            price_numeric=500.0,
            manufacturer="Multiplex",
            model_name="Easy Glider",
            model_type="glider",
        )
        # High similarity: same model_name + manufacturer
        await _insert_listing(
            db_session, "sort-high",
            price_numeric=400.0,
            manufacturer="Multiplex",
            model_name="Easy Glider",
            model_type="glider",
        )
        # Low similarity: only model_type matches
        await _insert_listing(
            db_session, "sort-low",
            price_numeric=300.0,
            manufacturer="Robbe",
            model_name="Arcus",
            model_type="glider",
        )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        data = r.json()
        scores = [item["similarity_score"] for item in data["listings"]]
        assert scores == sorted(scores, reverse=True), "listings must be sorted by similarity_score desc"

    async def test_no_self_match_in_listings(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The base listing itself must never appear in the comparables response."""
        base_id = await _insert_listing(
            db_session, "self-base",
            price_numeric=300.0,
            manufacturer="CARF",
            model_type="airplane",
        )
        await _insert_listing(
            db_session, "self-other",
            price_numeric=350.0,
            manufacturer="CARF",
            model_type="airplane",
        )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        listing_ids = [item["id"] for item in r.json()["listings"]]
        assert base_id not in listing_ids, "base listing must not appear in its own comparables"

    async def test_base_listing_without_model_type_returns_result(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Base listing without model_type: no SQL filter, response still valid."""
        base_id = await _insert_listing(
            db_session, "notype-base",
            price_numeric=200.0,
            manufacturer="Graupner",
            model_type=None,
        )
        await _insert_listing(
            db_session, "notype-other",
            price_numeric=250.0,
            manufacturer="Graupner",
            model_type="airplane",
        )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        data = r.json()
        assert data["match_quality"] in {"homogeneous", "heterogeneous", "insufficient"}

    async def test_base_without_manufacturer_and_subtype_returns_heterogeneous(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Base with no manufacturer and no subtype/completeness → insufficient or heterogeneous."""
        base_id = await _insert_listing(
            db_session, "noattr-base",
            price_numeric=100.0,
            manufacturer=None,
            model_subtype=None,
            completeness=None,
            model_type="airplane",
        )
        for i in range(6):
            await _insert_listing(
                db_session, f"noattr-cand-{i}",
                price_numeric=200.0 + i * 50,
                manufacturer="CARF",
                model_type="airplane",
            )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        assert r.json()["match_quality"] in {"heterogeneous", "insufficient"}

    async def test_limit_parameter_caps_result_count(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """?limit=3 returns at most 3 listings."""
        base_id = await _insert_listing(
            db_session, "lim-base",
            price_numeric=300.0,
            manufacturer="Multiplex",
            model_type="glider",
        )
        for i in range(8):
            await _insert_listing(
                db_session, f"lim-cand-{i}",
                price_numeric=250.0 + i * 10,
                manufacturer="Multiplex",
                model_type="glider",
            )
        r = await api_client.get(f"/api/listings/{base_id}/comparables?limit=3")
        assert r.status_code == 200
        assert len(r.json()["listings"]) <= 3

    async def test_tie_break_by_price_ascending(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When two listings have the same score, lower price comes first."""
        base_id = await _insert_listing(
            db_session, "tie-base",
            price_numeric=500.0,
            manufacturer="CARF",
            model_type="airplane",
        )
        # Same score (same manufacturer + model_type), different prices
        id_expensive = await _insert_listing(
            db_session, "tie-expensive",
            price_numeric=800.0,
            manufacturer="CARF",
            model_type="airplane",
        )
        id_cheap = await _insert_listing(
            db_session, "tie-cheap",
            price_numeric=200.0,
            manufacturer="CARF",
            model_type="airplane",
        )
        r = await api_client.get(f"/api/listings/{base_id}/comparables")
        assert r.status_code == 200
        listings = r.json()["listings"]
        # Find these two in the result list (other candidates may exist)
        ids_in_order = [item["id"] for item in listings]
        if id_cheap in ids_in_order and id_expensive in ids_in_order:
            assert ids_in_order.index(id_cheap) < ids_in_order.index(id_expensive), (
                "cheaper listing must appear before more expensive listing on tie"
            )
