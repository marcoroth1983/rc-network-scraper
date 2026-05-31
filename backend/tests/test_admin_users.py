"""Tests for admin user-approval endpoints."""

from __future__ import annotations

import pytest
from sqlalchemy import text


async def _seed_user(db_session, google_id, email, *, is_approved, role="member"):
    await db_session.execute(
        text("""
            INSERT INTO users (google_id, email, name, is_approved, role)
            VALUES (:g, :e, :n, :a, :r)
        """),
        {"g": google_id, "e": email, "n": None, "a": is_approved, "r": role},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM users WHERE google_id = :g"), {"g": google_id})
    ).scalar_one()


@pytest.mark.asyncio
async def test_list_users_returns_all_pending_first(admin_client, db_session):
    client, _admin_id = admin_client
    await _seed_user(db_session, "u-approved", "approved@example.com", is_approved=True)
    await _seed_user(db_session, "u-pending", "pending@example.com", is_approved=False)

    resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    rows = resp.json()
    emails = [r["email"] for r in rows]
    # Admin (approved) + 2 seeded; pending must come before any approved user
    assert "pending@example.com" in emails
    assert emails.index("pending@example.com") == 0
    # DTO shape
    sample = next(r for r in rows if r["email"] == "pending@example.com")
    assert set(sample) == {"id", "email", "name", "is_approved", "role", "created_at", "last_seen_at"}


@pytest.mark.asyncio
async def test_approve_user_sets_flag(admin_client, db_session):
    client, _admin_id = admin_client
    uid = await _seed_user(db_session, "u-x", "x@example.com", is_approved=False)

    resp = await client.patch(f"/api/admin/users/{uid}/approval", json={"is_approved": True})
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is True

    row = await db_session.execute(text("SELECT is_approved FROM users WHERE id = :id"), {"id": uid})
    assert row.scalar_one() is True


@pytest.mark.asyncio
async def test_revoke_other_user_succeeds(admin_client, db_session):
    client, _admin_id = admin_client
    uid = await _seed_user(db_session, "u-y", "y@example.com", is_approved=True)

    resp = await client.patch(f"/api/admin/users/{uid}/approval", json={"is_approved": False})
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is False


@pytest.mark.asyncio
async def test_admin_cannot_revoke_own_approval(admin_client):
    client, admin_id = admin_client
    resp = await client.patch(f"/api/admin/users/{admin_id}/approval", json={"is_approved": False})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_unknown_user_returns_404(admin_client):
    client, _admin_id = admin_client
    resp = await client.patch("/api/admin/users/999999/approval", json={"is_approved": True})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_forbidden(authenticated_client):
    # authenticated_client authenticates as a member (role defaults to 'member')
    resp = await authenticated_client.get("/api/admin/users")
    assert resp.status_code == 403
