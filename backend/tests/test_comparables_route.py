"""End-to-end tests for GET /api/listings/{id}/comparables (routes.py).

New hard-attribute filter logic (PLAN-025). All tests are integration tests that
require a running PostgreSQL database (run via Docker Compose).

Uses the ``authenticated_client`` fixture from conftest.py:303 (real user in DB).
Run with: docker compose exec backend pytest tests/test_comparables_route.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_listing(
    session: AsyncSession,
    external_id: str,
    *,
    category: str = "flugmodelle",
    price_numeric: float | None = 100.0,
    is_sold: bool = False,
    is_outdated: bool = False,
    model_type: str | None = None,
    model_subtype: str | None = None,
    drive_type: str | None = None,
    attributes: str = "{}",
    posted_at: datetime | None = None,
    title: str | None = None,
) -> int:
    """Insert a minimal listing and return its DB id."""
    if posted_at is None:
        posted_at = datetime.now(timezone.utc)
    if title is None:
        title = f"Listing {external_id}"
    await session.execute(
        text("""
            INSERT INTO listings (
                external_id, url, title, description, author, scraped_at, images, tags,
                price_numeric, is_sold, is_outdated, category,
                model_type, model_subtype, drive_type, attributes, posted_at
            )
            VALUES (
                :eid, :url, :title, '', 'seller', now(), '[]', '[]',
                :price, :sold, :outdated, :category,
                :mt, :ms, :dt, CAST(:attrs AS jsonb), :posted_at
            )
        """),
        {
            "eid": external_id,
            "url": f"http://example.com/{external_id}",
            "title": title,
            "price": price_numeric,
            "sold": is_sold,
            "outdated": is_outdated,
            "category": category,
            "mt": model_type,
            "ms": model_subtype,
            "dt": drive_type,
            "attrs": attributes,
            "posted_at": posted_at,
        },
    )
    await session.commit()
    row = await session.execute(
        text("SELECT id FROM listings WHERE external_id = :eid"), {"eid": external_id}
    )
    return row.scalar_one()


# ---------------------------------------------------------------------------
# Scenario 1 — No discriminating attribute on base → count=0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_discriminating_attribute_returns_count_zero(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Base with no model_type/subtype/drive_type/wingspan → count=0, listings=[]."""
    base_id = await _insert_listing(
        db_session, "s1-base",
        category="flugmodelle",
        model_type=None,
        model_subtype=None,
        drive_type=None,
        attributes="{}",
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["listings"] == []


# ---------------------------------------------------------------------------
# Scenario 2 — Only model_type set → candidates with same type or NULL type match
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_only_model_type_set_null_type_tolerated(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """model_type='airplane': candidates with same type or NULL match; different type does not."""
    base_id = await _insert_listing(
        db_session, "s2-base",
        category="flugmodelle",
        model_type="airplane",
    )
    id_a = await _insert_listing(
        db_session, "s2-a",
        category="flugmodelle",
        model_type="airplane",
    )
    await _insert_listing(
        db_session, "s2-b",
        category="flugmodelle",
        model_type="glider",  # different type — NO match
    )
    id_c = await _insert_listing(
        db_session, "s2-c",
        category="flugmodelle",
        model_type=None,  # NULL tolerated — match
    )
    await _insert_listing(
        db_session, "s2-d",
        category="rc-cars",  # different category — NO match
        model_type="airplane",
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    returned_ids = {item["id"] for item in data["listings"]}
    assert id_a in returned_ids
    assert id_c in returned_ids


# ---------------------------------------------------------------------------
# Scenario 3 — model_subtype hard when set (jet vs. turbine stays strict)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_model_subtype_strict_when_set(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """model_subtype='jet': turbine does NOT match; NULL subtype is tolerated."""
    base_id = await _insert_listing(
        db_session, "s3-base",
        category="flugmodelle",
        model_type="airplane",
        model_subtype="jet",
    )
    id_a = await _insert_listing(
        db_session, "s3-a",
        category="flugmodelle",
        model_type="airplane",
        model_subtype="jet",  # match
    )
    await _insert_listing(
        db_session, "s3-b",
        category="flugmodelle",
        model_type="airplane",
        model_subtype="turbine",  # different subtype — NO match
    )
    id_c = await _insert_listing(
        db_session, "s3-c",
        category="flugmodelle",
        model_type="airplane",
        model_subtype=None,  # NULL tolerated — match
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    returned_ids = {item["id"] for item in data["listings"]}
    assert id_a in returned_ids
    assert id_c in returned_ids
    assert data["count"] == 2


# ---------------------------------------------------------------------------
# Scenario 4 — wingspan_mm ±25 % + NULL tolerance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_wingspan_range_and_null_tolerance(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """wingspan_mm=2000: range 1500..2500. Boundaries inclusive; non-numeric treated as NULL (tolerated)."""
    base_id = await _insert_listing(
        db_session, "s4-base",
        category="flugmodelle",
        attributes='{"wingspan_mm": "2000"}',
    )
    # Below lower bound — NO
    id_1499 = await _insert_listing(
        db_session, "s4-1499",
        category="flugmodelle",
        attributes='{"wingspan_mm": "1499"}',
    )
    # Lower boundary — YES (BETWEEN inclusive)
    id_1500 = await _insert_listing(
        db_session, "s4-1500",
        category="flugmodelle",
        attributes='{"wingspan_mm": "1500"}',
    )
    # Upper boundary — YES
    id_2500 = await _insert_listing(
        db_session, "s4-2500",
        category="flugmodelle",
        attributes='{"wingspan_mm": "2500"}',
    )
    # Above upper bound — NO
    id_2501 = await _insert_listing(
        db_session, "s4-2501",
        category="flugmodelle",
        attributes='{"wingspan_mm": "2501"}',
    )
    # No key — YES (tolerated, treated as NULL)
    id_nokey = await _insert_listing(
        db_session, "s4-nokey",
        category="flugmodelle",
        attributes="{}",
    )
    # Non-numeric value — YES (regex guard treats as NULL, tolerated)
    id_nonnumeric = await _insert_listing(
        db_session, "s4-nonnumeric",
        category="flugmodelle",
        attributes='{"wingspan_mm": "ca. 2000"}',
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    returned_ids = {item["id"] for item in data["listings"]}
    assert id_1500 in returned_ids
    assert id_2500 in returned_ids
    assert id_nokey in returned_ids
    assert id_nonnumeric in returned_ids
    # Base, 1499, and 2501 must not appear
    assert base_id not in returned_ids
    assert id_1499 not in returned_ids
    assert id_2501 not in returned_ids


# ---------------------------------------------------------------------------
# Scenario 5 — drive_type hard when set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_drive_type_strict_when_set(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """drive_type='electric': combustion does NOT match; NULL drive_type is tolerated."""
    base_id = await _insert_listing(
        db_session, "s5-base",
        category="flugmodelle",
        model_type="airplane",
        drive_type="electric",
    )
    await _insert_listing(
        db_session, "s5-combustion",
        category="flugmodelle",
        model_type="airplane",
        drive_type="combustion",  # NO match
    )
    id_null_drive = await _insert_listing(
        db_session, "s5-null-drive",
        category="flugmodelle",
        model_type="airplane",
        drive_type=None,  # NULL tolerated — YES
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    returned_ids = {item["id"] for item in data["listings"]}
    assert id_null_drive in returned_ids
    assert data["count"] == 1


# ---------------------------------------------------------------------------
# Scenario 6 — Sold + outdated listings included (explicit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_sold_and_outdated_included(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Sold and outdated listings are included in comparables (product decision)."""
    base_id = await _insert_listing(
        db_session, "s6-base",
        category="flugmodelle",
        model_type="airplane",
    )
    id_sold = await _insert_listing(
        db_session, "s6-sold",
        category="flugmodelle",
        model_type="airplane",
        is_sold=True,
    )
    id_outdated = await _insert_listing(
        db_session, "s6-outdated",
        category="flugmodelle",
        model_type="airplane",
        is_outdated=True,
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    returned_ids = {item["id"] for item in data["listings"]}
    assert id_sold in returned_ids
    assert id_outdated in returned_ids


# ---------------------------------------------------------------------------
# Scenario 7 — Order by posted_at DESC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_order_by_posted_at_desc(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Listings are returned ordered by posted_at descending (newest first)."""
    now = datetime.now(timezone.utc)
    base_id = await _insert_listing(
        db_session, "s7-base",
        category="flugmodelle",
        model_type="airplane",
        posted_at=now,
    )
    await _insert_listing(
        db_session, "s7-old",
        category="flugmodelle",
        model_type="airplane",
        posted_at=now - timedelta(days=10),
    )
    await _insert_listing(
        db_session, "s7-new",
        category="flugmodelle",
        model_type="airplane",
        posted_at=now - timedelta(days=1),
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    listings = r.json()["listings"]
    assert len(listings) == 2
    # Newer must come first
    dt0 = datetime.fromisoformat(listings[0]["posted_at"])
    dt1 = datetime.fromisoformat(listings[1]["posted_at"])
    assert dt0 > dt1


# ---------------------------------------------------------------------------
# Scenario 8 — Limit clamped at 30
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_limit_clamped_at_30(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Default limit returns at most 30; count reflects total; limit=999 → 422; limit=5 works."""
    base_id = await _insert_listing(
        db_session, "s8-base",
        category="flugmodelle",
        model_type="airplane",
    )
    for i in range(35):
        await _insert_listing(
            db_session, f"s8-cand-{i}",
            category="flugmodelle",
            model_type="airplane",
        )
    # Default limit (30)
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 35
    assert len(data["listings"]) == 30

    # Out-of-range limit → 422
    r2 = await authenticated_client.get(f"/api/listings/{base_id}/comparables?limit=999")
    assert r2.status_code == 422

    # Custom limit within range
    r3 = await authenticated_client.get(f"/api/listings/{base_id}/comparables?limit=5")
    assert r3.status_code == 200
    assert len(r3.json()["listings"]) == 5


# ---------------------------------------------------------------------------
# Scenario 9 — Base listing not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_base_listing_not_found(authenticated_client: AsyncClient) -> None:
    """GET /api/listings/99999/comparables → 404."""
    r = await authenticated_client.get("/api/listings/99999/comparables")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scenario 10 — Response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_response_shape(
    authenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Successful response has exactly count + listings; each listing has id/title/url/price/price_numeric/posted_at."""
    base_id = await _insert_listing(
        db_session, "s10-base",
        category="flugmodelle",
        model_type="airplane",
    )
    await _insert_listing(
        db_session, "s10-cand",
        category="flugmodelle",
        model_type="airplane",
    )
    r = await authenticated_client.get(f"/api/listings/{base_id}/comparables")
    assert r.status_code == 200
    data = r.json()

    # Top-level keys
    assert set(data.keys()) == {"count", "listings"}

    # Per-listing keys
    for item in data["listings"]:
        assert set(item.keys()) == {"id", "title", "url", "price", "price_numeric", "posted_at"}
        # Removed keys must not be present
        assert "match_quality" not in item
        assert "median" not in item
        assert "similarity_score" not in item
        assert "is_favorite" not in item
        assert "condition" not in item
        assert "city" not in item
