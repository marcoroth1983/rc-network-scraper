"""Tests for saved search CRUD endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def seed_test_user(db_session: AsyncSession) -> None:
    """Insert the fake user (id=1) that api_client's get_current_user returns.

    The TRUNCATE in clean_listings resets identity — so we explicitly set id=1
    to match the fake user returned by the dependency override.
    """
    await db_session.execute(
        text(
            "INSERT INTO users (id, google_id, email, name, is_approved) "
            "VALUES (1, 'test-google-id', 'test@example.com', 'Test User', true) "
            "ON CONFLICT DO NOTHING"
        )
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Name generation
# ---------------------------------------------------------------------------

def test_generate_search_name_search_only():
    from app.api.routes import _generate_search_name
    assert _generate_search_name("Multiplex", None, None) == "Multiplex"


def test_generate_search_name_search_and_plz():
    from app.api.routes import _generate_search_name
    assert _generate_search_name("Multiplex", "49356", None) == "Multiplex in 49356"


def test_generate_search_name_plz_and_distance():
    from app.api.routes import _generate_search_name
    assert _generate_search_name(None, "49356", 50) == "Alles in 49356 (+50km)"


def test_generate_search_name_plz_only():
    from app.api.routes import _generate_search_name
    assert _generate_search_name(None, "49356", None) == "Alles in 49356"


def test_generate_search_name_fallback():
    from app.api.routes import _generate_search_name
    assert _generate_search_name(None, None, None) == "Alle Anzeigen"


# ---------------------------------------------------------------------------
# POST /api/searches — create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_search_basic(api_client: AsyncClient):
    """POST /api/searches with search term → 201, auto-generated name."""
    resp = await api_client.post("/api/searches", json={"search": "Multiplex"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["search"] == "Multiplex"
    assert data["name"] == "Multiplex"
    assert data["match_count"] == 0
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_search_with_plz(api_client: AsyncClient, db_session: AsyncSession):
    """POST /api/searches with valid PLZ → 201."""
    await db_session.execute(
        text("INSERT INTO plz_geodata (plz, city, lat, lon) VALUES ('49356', 'Diepholz', 52.6, 8.3)")
    )
    await db_session.commit()

    resp = await api_client.post(
        "/api/searches",
        json={"search": "Multiplex", "plz": "49356", "max_distance": 50},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Multiplex in 49356"
    assert data["plz"] == "49356"
    assert data["max_distance"] == 50


@pytest.mark.asyncio
async def test_create_search_invalid_plz(api_client: AsyncClient):
    """POST /api/searches with unknown PLZ → 400."""
    resp = await api_client.post(
        "/api/searches",
        json={"plz": "99999"},
    )
    assert resp.status_code == 400
    assert "PLZ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_search_distance_without_plz(api_client: AsyncClient):
    """POST /api/searches with max_distance but no PLZ → 422 (schema validation)."""
    resp = await api_client.post(
        "/api/searches",
        json={"max_distance": 100},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_search_duplicate_allowed(api_client: AsyncClient):
    """POST duplicate criteria → allowed (no unique constraint on criteria)."""
    resp1 = await api_client.post("/api/searches", json={"search": "Graupner"})
    resp2 = await api_client.post("/api/searches", json={"search": "Graupner"})
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]


# ---------------------------------------------------------------------------
# GET /api/searches — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_searches_empty(api_client: AsyncClient):
    """GET /api/searches → empty list when no searches exist."""
    resp = await api_client.get("/api/searches")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_searches_returns_own(api_client: AsyncClient):
    """GET /api/searches → returns searches for current user with match_count."""
    await api_client.post("/api/searches", json={"search": "Multiplex"})
    await api_client.post("/api/searches", json={"search": "Graupner"})

    resp = await api_client.get("/api/searches")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert "match_count" in item
        assert item["match_count"] == 0


# ---------------------------------------------------------------------------
# PUT /api/searches/{id} — update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_search(api_client: AsyncClient, db_session: AsyncSession):
    """PUT /api/searches/{id} updates criteria and regenerates name."""
    await db_session.execute(
        text("INSERT INTO plz_geodata (plz, city, lat, lon) VALUES ('49356', 'Diepholz', 52.6, 8.3)")
    )
    await db_session.commit()

    create_resp = await api_client.post("/api/searches", json={"search": "Multiplex"})
    search_id = create_resp.json()["id"]

    resp = await api_client.put(
        f"/api/searches/{search_id}",
        json={"search": "Multiplex", "plz": "49356"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Multiplex in 49356"
    assert data["plz"] == "49356"


@pytest.mark.asyncio
async def test_update_search_not_found(api_client: AsyncClient):
    """PUT /api/searches/9999 → 404."""
    resp = await api_client.put("/api/searches/9999", json={"search": "Test"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/searches/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_search(api_client: AsyncClient):
    """DELETE /api/searches/{id} → 200 with {ok: true}."""
    create_resp = await api_client.post("/api/searches", json={"search": "Multiplex"})
    search_id = create_resp.json()["id"]

    resp = await api_client.delete(f"/api/searches/{search_id}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Verify gone
    list_resp = await api_client.get("/api/searches")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_search_not_found(api_client: AsyncClient):
    """DELETE /api/searches/9999 → 404."""
    resp = await api_client.delete("/api/searches/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/searches/{id} — toggle active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toggle_search_inactive(api_client: AsyncClient):
    """PATCH /api/searches/{id}?is_active=false → is_active updated."""
    create_resp = await api_client.post("/api/searches", json={"search": "Multiplex"})
    search_id = create_resp.json()["id"]

    resp = await api_client.patch(f"/api/searches/{search_id}?is_active=false")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_toggle_search_active(api_client: AsyncClient):
    """PATCH /api/searches/{id}?is_active=true → is_active updated."""
    create_resp = await api_client.post("/api/searches", json={"search": "Multiplex"})
    search_id = create_resp.json()["id"]

    # Deactivate first
    await api_client.patch(f"/api/searches/{search_id}?is_active=false")
    # Re-activate
    resp = await api_client.patch(f"/api/searches/{search_id}?is_active=true")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_toggle_search_not_found(api_client: AsyncClient):
    """PATCH /api/searches/9999 → 404."""
    resp = await api_client.patch("/api/searches/9999?is_active=false")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/searches/mark-viewed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_viewed_sets_timestamp(api_client: AsyncClient, db_session: AsyncSession):
    """POST /api/searches/mark-viewed sets last_viewed_at on all user's searches."""
    await api_client.post("/api/searches", json={"search": "Multiplex"})
    await api_client.post("/api/searches", json={"search": "Graupner"})

    resp = await api_client.post("/api/searches/mark-viewed")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify last_viewed_at is now set
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM saved_searches WHERE last_viewed_at IS NOT NULL")
    )
    count = result.scalar_one()
    assert count == 2
