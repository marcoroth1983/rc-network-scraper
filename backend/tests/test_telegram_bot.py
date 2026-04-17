"""Tests for app.telegram.bot — outbound Telegram API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.telegram import bot


def _make_response(status_code: int, json_body: dict) -> MagicMock:
    """Build a minimal httpx.Response-like mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    description = json_body.get("description", "")
    resp.text = description
    return resp


@pytest.mark.asyncio
async def test_send_message_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "botuser")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")

    resp = _make_response(200, {"ok": True})
    mock_post = AsyncMock(return_value=resp)

    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        ok = await bot.send_message(chat_id=12345, text_body="hi")

    assert ok is True
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_403_blocked_clears_chat_id(monkeypatch, db_user_linked):
    """403 blocked should auto-clear user.telegram_chat_id."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "botuser")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")

    resp = _make_response(403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
    mock_post = AsyncMock(return_value=resp)

    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        ok = await bot.send_message(chat_id=db_user_linked.chat_id, text_body="hi")

    assert ok is False
    # Assert chat_id was cleared in DB
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(
            text("SELECT telegram_chat_id FROM users WHERE id = :u"),
            {"u": db_user_linked.user_id},
        )
        assert row.scalar() is None


@pytest.mark.asyncio
async def test_send_message_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    ok = await bot.send_message(chat_id=12345, text_body="hi")
    assert ok is False


@pytest.mark.asyncio
async def test_send_message_other_errors_do_not_clear_chat_id(monkeypatch, db_user_linked):
    """Non-403 errors (500, network) must NOT clear chat_id — transient."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "botuser")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")

    resp = _make_response(500, {"ok": False})
    mock_post = AsyncMock(return_value=resp)

    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        ok = await bot.send_message(chat_id=db_user_linked.chat_id, text_body="hi")

    assert ok is False
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(
            text("SELECT telegram_chat_id FROM users WHERE id = :u"),
            {"u": db_user_linked.user_id},
        )
        assert row.scalar() == db_user_linked.chat_id  # unchanged


@pytest.mark.asyncio
async def test_send_message_403_without_blocked_fragment_keeps_chat_id(db_user_linked, monkeypatch):
    """403 with an unknown body (e.g. 'chat not found') must NOT clear chat_id —
    only the specific blocked-by-user fragments trigger auto-unlink."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "botuser")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")

    resp = _make_response(403, {"ok": False, "description": "Forbidden: chat not found"})
    mock_post = AsyncMock(return_value=resp)

    with patch("app.telegram.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        ok = await bot.send_message(chat_id=db_user_linked.chat_id, text_body="hi")

    assert ok is False
    import app.db as _app_db
    from sqlalchemy import text
    async with _app_db.AsyncSessionLocal() as s:
        row = await s.execute(
            text("SELECT telegram_chat_id FROM users WHERE id = :u"),
            {"u": db_user_linked.user_id},
        )
        assert row.scalar() == db_user_linked.chat_id  # unchanged — generic 403 must not unlink
