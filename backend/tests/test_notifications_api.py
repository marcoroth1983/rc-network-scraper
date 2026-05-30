"""Tests for /api/notifications/* — uses authenticated_client fixture from conftest."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_vapid_public_key_returns_key(api_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "BPub")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:x@y")
    r = await api_client.get("/api/notifications/vapid-public-key")
    assert r.status_code == 200
    assert r.json() == {"public_key": "BPub"}


@pytest.mark.asyncio
async def test_get_vapid_public_key_503_when_unconfigured(api_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    r = await api_client.get("/api/notifications/vapid-public-key")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_subscription_creates_row(authenticated_client):
    body = {
        "endpoint": "https://fcm.googleapis.com/abc",
        "keys": {"p256dh": "P1", "auth": "A1"},
        "user_agent": "test-ua",
        "device_label": "Pixel 8",
    }
    r = await authenticated_client.post("/api/notifications/subscriptions", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["endpoint"] == body["endpoint"]
    assert data["device_label"] == "Pixel 8"


@pytest.mark.asyncio
async def test_post_subscription_upserts_existing_endpoint(authenticated_client):
    body = {"endpoint": "https://fcm/abc", "keys": {"p256dh": "P", "auth": "A"}}
    a = await authenticated_client.post("/api/notifications/subscriptions", json=body)
    b = await authenticated_client.post(
        "/api/notifications/subscriptions", json={**body, "device_label": "renamed"},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["device_label"] == "renamed"


@pytest.mark.asyncio
async def test_get_subscriptions_returns_only_owned(authenticated_client, other_user_with_sub):
    await authenticated_client.post(
        "/api/notifications/subscriptions",
        json={"endpoint": "https://fcm/owned", "keys": {"p256dh": "P", "auth": "A"}},
    )
    r = await authenticated_client.get("/api/notifications/subscriptions")
    assert r.status_code == 200
    endpoints = [s["endpoint"] for s in r.json()]
    assert "https://fcm/owned" in endpoints
    assert "https://other-user-endpoint" not in endpoints


@pytest.mark.asyncio
async def test_delete_subscription_removes_row(authenticated_client):
    create = await authenticated_client.post(
        "/api/notifications/subscriptions",
        json={"endpoint": "https://fcm/x", "keys": {"p256dh": "P", "auth": "A"}},
    )
    sub_id = create.json()["id"]
    r = await authenticated_client.delete(f"/api/notifications/subscriptions/{sub_id}")
    assert r.status_code == 204
    r2 = await authenticated_client.get("/api/notifications/subscriptions")
    assert all(s["id"] != sub_id for s in r2.json())


@pytest.mark.asyncio
async def test_delete_subscription_404_when_not_owned(authenticated_client, other_user_with_sub):
    r = await authenticated_client.delete(
        f"/api/notifications/subscriptions/{other_user_with_sub.sub_ids[0]}"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_preferences_creates_default(authenticated_client):
    r = await authenticated_client.get("/api/notifications/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["web_push_enabled"] is True
    assert body["new_search_results"] is True
    assert "fav_sold" in body and "fav_price" in body and "fav_deleted" in body


@pytest.mark.asyncio
async def test_put_preferences_updates_web_push_enabled(authenticated_client):
    r = await authenticated_client.put(
        "/api/notifications/preferences", json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["web_push_enabled"] is False


@pytest.mark.asyncio
async def test_put_preferences_partial_does_not_clobber_other_fields(authenticated_client):
    await authenticated_client.put("/api/notifications/preferences", json={"fav_sold": False})
    r = await authenticated_client.put(
        "/api/notifications/preferences", json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["fav_sold"] is False  # unchanged
