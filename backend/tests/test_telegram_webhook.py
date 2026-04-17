"""Tests for app.telegram.webhook — inbound webhook with secret validation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.config import settings

WEBHOOK_SECRET = "test-secret"


def _make_response(status_code: int, json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = json_body.get("description", "")
    return resp


@pytest.mark.asyncio
async def test_webhook_rejects_missing_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/telegram/webhook", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/telegram/webhook",
            json={},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_correct_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_make_response(200, {"ok": True}))
        mock_client_cls.return_value = mock_client
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/telegram/webhook",
                json={"update_id": 1, "message": {"chat": {"id": 999}, "text": "hello"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_start_token_links_user(monkeypatch, db_user):
    """/start <valid_token> sets user.telegram_chat_id."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    from app.telegram import link
    t = await link.create_token(user_id=db_user.id)
    # Mock the outbound bot.send_message so it doesn't try to reach Telegram
    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_make_response(200, {"ok": True}))
        mock_client_cls.return_value = mock_client
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/telegram/webhook",
                json={"update_id": 1, "message": {"chat": {"id": 12345}, "text": f"/start {t.token}"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
    assert resp.status_code == 200
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(
            text("SELECT telegram_chat_id FROM users WHERE id = :u"),
            {"u": db_user.id},
        )
        assert row.scalar() == 12345


@pytest.mark.asyncio
async def test_webhook_malformed_payload_returns_200(monkeypatch):
    """Unexpected shapes (no message, no text) must not 500."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for payload in (
            {},
            {"update_id": 1},
            {"update_id": 1, "message": {}},
            {"update_id": 1, "message": {"chat": {}}},
        ):
            resp = await c.post(
                "/api/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_start_with_already_used_token_replies_with_error(monkeypatch, db_user):
    """Second /start with the same token must trigger the error-reply branch."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)

    from app.telegram import link
    t = await link.create_token(user_id=db_user.id)

    sent_texts: list[str] = []

    async def _capture(chat_id, text_body, parse_mode="HTML", disable_web_page_preview=False):
        sent_texts.append(text_body)
        return True

    with patch("app.telegram.webhook.bot.send_message", side_effect=_capture):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # First call: succeeds, sends welcome message
            r1 = await c.post(
                "/api/telegram/webhook",
                json={"update_id": 1, "message": {"chat": {"id": 99}, "text": f"/start {t.token}"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            # Second call with same (now-used) token: must hit the error branch
            r2 = await c.post(
                "/api/telegram/webhook",
                json={"update_id": 2, "message": {"chat": {"id": 99}, "text": f"/start {t.token}"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(sent_texts) == 2
    assert "Verbunden" in sent_texts[0]
    assert "Ungültiger" in sent_texts[1] or "abgelaufen" in sent_texts[1]
