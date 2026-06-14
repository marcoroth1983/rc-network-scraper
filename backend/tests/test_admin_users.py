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


@pytest.mark.asyncio
async def test_non_admin_forbidden_patch(authenticated_client):
    # member must not be able to approve users via PATCH
    resp = await authenticated_client.patch("/api/admin/users/1/approval", json={"is_approved": True})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_hard_deletes_and_cascades(admin_client, db_session):
    client, _admin_id = admin_client
    await _seed_user(db_session, "del-g", "del@example.com", is_approved=True)
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'del-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'x')"), {"u": uid}
    )
    await db_session.commit()

    resp = await client.delete(f"/api/admin/users/{uid}")
    assert resp.status_code == 204
    assert (await db_session.execute(
        text("SELECT count(*) FROM users WHERE id = :u"), {"u": uid}
    )).scalar_one() == 0
    assert (await db_session.execute(
        text("SELECT count(*) FROM saved_searches WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0


@pytest.mark.asyncio
async def test_delete_self_is_blocked(admin_client):
    client, admin_id = admin_client
    resp = await client.delete(f"/api/admin/users/{admin_id}")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_missing_user_404(admin_client):
    client, _ = admin_client
    resp = await client.delete("/api/admin/users/999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_stats_counts(admin_client, db_session):
    client, _ = admin_client
    await _seed_user(db_session, "st-g", "st@example.com", is_approved=True)
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'st-g'")
    )).scalar_one()
    await db_session.execute(text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'a')"), {"u": uid})
    await db_session.execute(text("INSERT INTO login_events (user_id) VALUES (:u)"), {"u": uid})
    await db_session.commit()

    resp = await client.get(f"/api/admin/users/{uid}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved_searches"] == 1
    assert body["logins_total"] == 1
    assert set(body) >= {"favorites", "push_devices", "logins_30d", "created_at", "last_seen_at"}


@pytest.mark.asyncio
async def test_user_stats_404(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/users/999999/stats")
    assert resp.status_code == 404
