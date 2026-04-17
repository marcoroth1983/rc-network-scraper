"""Tests for user-facing /api/telegram/* endpoints + /auth/me telegram fields."""

import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.config import settings


@pytest.mark.asyncio
async def test_link_returns_deeplink(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "rcn_scout_bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    r = await authenticated_client.post("/api/telegram/link")
    assert r.status_code == 200
    body = r.json()
    assert body["deeplink"].startswith("https://t.me/rcn_scout_bot?start=")
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_link_503_when_disabled(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    r = await authenticated_client.post("/api/telegram/link")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_unlink_clears_chat_id(authenticated_client_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    r = await authenticated_client_linked.post("/api/telegram/unlink")
    assert r.status_code == 200
    me = await authenticated_client_linked.get("/api/auth/me")
    assert me.json().get("telegram_chat_id") is None


@pytest.mark.asyncio
async def test_get_prefs_returns_defaults(authenticated_client):
    r = await authenticated_client.get("/api/telegram/prefs")
    assert r.status_code == 200
    assert r.json()["fav_sold"] is True


@pytest.mark.asyncio
async def test_put_prefs_partial_update(authenticated_client):
    r = await authenticated_client.put("/api/telegram/prefs", json={"fav_sold": False})
    assert r.status_code == 200
    assert r.json()["fav_sold"] is False
    assert r.json()["fav_price"] is True


@pytest.mark.asyncio
async def test_auth_me_includes_telegram_fields(authenticated_client_linked):
    r = await authenticated_client_linked.get("/api/auth/me")
    body = r.json()
    assert "telegram_chat_id" in body
    assert "telegram_linked_at" in body


@pytest.mark.asyncio
async def test_unauthenticated_endpoints_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/telegram/link")).status_code == 401
        assert (await c.get("/api/telegram/prefs")).status_code == 401
        assert (await c.put("/api/telegram/prefs", json={})).status_code == 401
        assert (await c.post("/api/telegram/unlink")).status_code == 401
