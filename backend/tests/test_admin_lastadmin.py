"""Tests for last-admin invariant, jti replay, and cookie break-glass in admin routes.

All tests use dependency_overrides to inject a specific CockpitOperator without
requiring a real JWKS endpoint — mirroring the pattern in conftest.admin_client.
"""

from __future__ import annotations

import contextlib
import time
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cockpit_auth import CockpitOperator, _clear_jti_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_admin(db_session: AsyncSession, google_id: str, email: str) -> int:
    """Insert an approved admin user and return their DB id."""
    await db_session.execute(
        text("""
            INSERT INTO users (google_id, email, name, is_approved, role)
            VALUES (:g, :e, NULL, TRUE, 'admin')
        """),
        {"g": google_id, "e": email},
    )
    await db_session.commit()
    return (
        await db_session.execute(
            text("SELECT id FROM users WHERE google_id = :g"), {"g": google_id}
        )
    ).scalar_one()


async def _seed_member(db_session: AsyncSession, google_id: str, email: str) -> int:
    """Insert an approved regular user and return their DB id."""
    await db_session.execute(
        text("""
            INSERT INTO users (google_id, email, name, is_approved, role)
            VALUES (:g, :e, NULL, TRUE, 'member')
        """),
        {"g": google_id, "e": email},
    )
    await db_session.commit()
    return (
        await db_session.execute(
            text("SELECT id FROM users WHERE google_id = :g"), {"g": google_id}
        )
    ).scalar_one()


@contextlib.asynccontextmanager
async def _cockpit_client(test_engine, *, google_id: str, email: str, jti: str | None):
    """Async context manager: HTTP test client with a specific CockpitOperator injected."""
    from app.api.deps import require_any_admin  # noqa: PLC0415
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_session() -> AsyncSession:
        async with factory() as session:
            yield session

    async def _fake_operator() -> CockpitOperator:
        return CockpitOperator(
            google_id=google_id,
            email=email,
            jti=jti,
            token_exp=time.time() + 300 if jti is not None else None,
        )

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[require_any_admin] = _fake_operator
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_jti_cache():
    """Ensure jti replay cache is clean before and after every test."""
    _clear_jti_cache()
    yield
    _clear_jti_cache()


# ---------------------------------------------------------------------------
# Last-admin invariant — DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_admin_delete_matched_409(test_engine, db_session):
    """Last approved admin cannot be deleted by a matched cockpit operator (409)."""
    # One approved admin is the target. Operator is a different matched user.
    target_id = await _seed_admin(db_session, "last-del-admin", "last-del@example.com")
    await _seed_member(db_session, "del-op-matched", "del-op@example.com")

    async with _cockpit_client(
        test_engine, google_id="del-op-matched", email="del-op@example.com", jti="jti-del-matched"
    ) as client:
        r = await client.delete(f"/api/admin/users/{target_id}")

    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_last_admin_delete_unmatched_409(test_engine, db_session):
    """Last approved admin cannot be deleted by an unmatched cockpit operator (409)."""
    target_id = await _seed_admin(db_session, "last-del-admin2", "last-del2@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="foreign-operator-never-in-db",
        email="foreign@example.com",
        jti="jti-del-unmatched",
    ) as client:
        r = await client.delete(f"/api/admin/users/{target_id}")

    assert r.status_code == 409, r.text


# ---------------------------------------------------------------------------
# Last-admin invariant — PATCH approval (demote)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_admin_demote_matched_409(test_engine, db_session):
    """Last approved admin cannot be demoted (is_approved=False) by a matched operator (409)."""
    target_id = await _seed_admin(db_session, "last-demote-admin", "last-demote@example.com")
    await _seed_member(db_session, "demote-op-matched", "demote-op@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="demote-op-matched",
        email="demote-op@example.com",
        jti="jti-demote-matched",
    ) as client:
        r = await client.patch(
            f"/api/admin/users/{target_id}/approval", json={"is_approved": False}
        )

    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_last_admin_demote_unmatched_409(test_engine, db_session):
    """Last approved admin cannot be demoted by an unmatched operator (409)."""
    target_id = await _seed_admin(db_session, "last-demote-admin2", "last-demote2@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="foreign-demote-never-in-db",
        email="foreign-demote@example.com",
        jti="jti-demote-unmatched",
    ) as client:
        r = await client.patch(
            f"/api/admin/users/{target_id}/approval", json={"is_approved": False}
        )

    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_non_last_admin_can_be_deleted_204(test_engine, db_session):
    """A non-last admin can be deleted when another approved admin exists."""
    target_id = await _seed_admin(db_session, "del-target-admin", "del-target@example.com")
    _other_id = await _seed_admin(db_session, "del-other-admin", "del-other@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="foreign-del-op",
        email="foreign-del@example.com",
        jti="jti-non-last-del",
    ) as client:
        r = await client.delete(f"/api/admin/users/{target_id}")

    assert r.status_code == 204, r.text


# ---------------------------------------------------------------------------
# Self-guard (google_id comparison)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_guard_matched_operator_delete_400(test_engine, db_session):
    """Matched operator cannot delete their own account even if not the last admin (400)."""
    _other_id = await _seed_admin(db_session, "self-guard-other", "sg-other@example.com")
    self_id = await _seed_admin(db_session, "self-guard-self", "sg-self@example.com")

    # Operator matched to the TARGET (self-delete attempt)
    async with _cockpit_client(
        test_engine,
        google_id="self-guard-self",
        email="sg-self@example.com",
        jti="jti-self-guard",
    ) as client:
        r = await client.delete(f"/api/admin/users/{self_id}")

    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# jti replay — one test per destructive route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_jti_refresh_409(test_engine, db_session, monkeypatch):
    """Replayed jti on POST /llm-models/refresh returns 409."""
    async def _noop(*_a, **_kw):  # type: ignore[return]
        return None

    async def _empty_rows() -> list:
        return []

    monkeypatch.setattr("app.api.admin.model_cascade.refresh_from_openrouter", _noop)
    monkeypatch.setattr("app.api.admin._fetch_all_rows", _empty_rows)

    async with _cockpit_client(
        test_engine,
        google_id="replay-refresh-op",
        email="rr@example.com",
        jti="jti-replay-refresh",
    ) as client:
        r1 = await client.post("/api/admin/llm-models/refresh")
        assert r1.status_code == 200, r1.text   # first call: jti consumed

        r2 = await client.post("/api/admin/llm-models/refresh")
        assert r2.status_code == 409, r2.text   # second call: replay rejected


@pytest.mark.asyncio
async def test_replayed_jti_approval_409(test_engine, db_session):
    """Replayed jti on PATCH /users/{id}/approval returns 409."""
    # Two admins so the approval change does not trigger last-admin invariant
    target_id = await _seed_admin(db_session, "replay-appr-target", "rat@example.com")
    _other_id = await _seed_admin(db_session, "replay-appr-other", "rao@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="replay-appr-op",
        email="rop@example.com",
        jti="jti-replay-approval",
    ) as client:
        r1 = await client.patch(
            f"/api/admin/users/{target_id}/approval", json={"is_approved": True}
        )
        assert r1.status_code == 200, r1.text   # first call: jti consumed

        r2 = await client.patch(
            f"/api/admin/users/{target_id}/approval", json={"is_approved": True}
        )
        assert r2.status_code == 409, r2.text   # second call: replay rejected


@pytest.mark.asyncio
async def test_replayed_jti_delete_409(test_engine, db_session):
    """Replayed jti on DELETE /users/{id} returns 409 (jti consumed before target check)."""
    # Three admins: target gets deleted on first call; second call hits jti cache before 404
    target_id = await _seed_admin(db_session, "replay-del-target", "rdt@example.com")
    _a_id = await _seed_admin(db_session, "replay-del-a", "rda@example.com")
    _b_id = await _seed_admin(db_session, "replay-del-b", "rdb@example.com")

    async with _cockpit_client(
        test_engine,
        google_id="replay-del-op",
        email="rdo@example.com",
        jti="jti-replay-delete",
    ) as client:
        r1 = await client.delete(f"/api/admin/users/{target_id}")
        assert r1.status_code == 204, r1.text   # first call: deletes target, jti consumed

        r2 = await client.delete(f"/api/admin/users/{target_id}")
        assert r2.status_code == 409, r2.text   # second call: replay rejected (before 404)


# ---------------------------------------------------------------------------
# Cookie break-glass path (jti=None — no replay check applies)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# S3 — real require_any_admin cookie break-glass (no fixture override)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_require_any_admin_admin_cookie_200_member_cookie_403(test_engine, db_session):
    """S3: COCKPIT_AUTH_ENABLED=False — admin cookie → 200, non-admin cookie → 403.

    Uses the REAL require_any_admin (no dependency_overrides for it), exercising
    the cookie break-glass path end-to-end through the actual implementation.
    """
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.security import create_jwt  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: PLC0415

    admin_id = await _seed_admin(db_session, "s3-real-admin", "s3-real-admin@example.com")
    member_id = await _seed_member(db_session, "s3-real-member", "s3-real-member@example.com")

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session():
        async with factory() as session:
            yield session

    # Override get_session for admin route handlers that use Depends(get_session),
    # but do NOT override require_any_admin — that is the whole point of this test.
    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Admin cookie → 200 (cookie break-glass allows access)
            admin_token = create_jwt(admin_id)
            r_admin = await client.get(
                "/api/admin/users",
                cookies={"session": admin_token},
            )
            assert r_admin.status_code == 200, (
                f"admin should get 200 via cookie, got {r_admin.status_code}: {r_admin.text}"
            )

            # Non-admin (member) cookie → 403
            member_token = create_jwt(member_id)
            r_member = await client.get(
                "/api/admin/users",
                cookies={"session": member_token},
            )
            assert r_member.status_code == 403, (
                f"member should get 403 via cookie, got {r_member.status_code}: {r_member.text}"
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cookie_break_glass_jti_none_no_replay(test_engine, db_session, monkeypatch):
    """Cookie-path operator (jti=None) can call destructive routes repeatedly without 409."""
    async def _noop(*_a, **_kw):  # type: ignore[return]
        return None

    async def _empty_rows() -> list:
        return []

    monkeypatch.setattr("app.api.admin.model_cascade.refresh_from_openrouter", _noop)
    monkeypatch.setattr("app.api.admin._fetch_all_rows", _empty_rows)

    async with _cockpit_client(
        test_engine,
        google_id="cookie-op",
        email="cookie@example.com",
        jti=None,   # cookie path: jti=None → replay check skipped
    ) as client:
        r1 = await client.post("/api/admin/llm-models/refresh")
        r2 = await client.post("/api/admin/llm-models/refresh")

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text   # no 409 — cookie path bypasses replay check
