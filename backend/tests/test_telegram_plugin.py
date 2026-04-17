"""Tests for TelegramPlugin — new-search-results digest via notification registry."""

import pytest
from unittest.mock import AsyncMock, patch
from app.notifications.base import MatchResult
from app.telegram.plugin import TelegramPlugin
from app.config import settings


def _match(user_id: int = 1, search_id: int = 12, titles=None, ids=None, name: str = "Seglerr") -> MatchResult:
    titles = titles or ["Easy Glider", "Multiplex Cular"]
    ids = ids or [101, 102]
    return MatchResult(
        saved_search_id=search_id,
        search_name=name,
        user_id=user_id,
        new_listing_ids=ids,
        new_listing_titles=titles,
        total_new=len(ids),
    )


@pytest.mark.asyncio
async def test_is_configured_true_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    p = TelegramPlugin()
    assert await p.is_configured() is True


@pytest.mark.asyncio
async def test_is_configured_false_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    assert await TelegramPlugin().is_configured() is False


@pytest.mark.asyncio
async def test_send_skipped_when_user_not_linked(db_user, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    # db_user has no telegram_chat_id
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user.id))
        mock.assert_not_called()
    assert ok is False


@pytest.mark.asyncio
async def test_send_skipped_when_pref_off(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    from app.telegram import prefs
    await prefs.set_prefs(db_user_linked.user_id, new_search_results=False)
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user_linked.user_id))
        mock.assert_not_called()
    assert ok is False


@pytest.mark.asyncio
async def test_send_sends_digest_when_enabled(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user_linked.user_id, name="Seglerr"))
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["chat_id"] == db_user_linked.chat_id
        assert "Seglerr" in kwargs["text_body"]
        assert "Easy Glider" in kwargs["text_body"]
    assert ok is True


@pytest.mark.asyncio
async def test_send_truncates_to_digest_top_n(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setattr(settings, "TELEGRAM_DIGEST_TOP_N", 2)
    titles = ["A", "B", "C", "D", "E"]
    ids = [1, 2, 3, 4, 5]
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        await TelegramPlugin().send(_match(user_id=db_user_linked.user_id, titles=titles, ids=ids))
    body = mock.call_args.kwargs["text_body"]
    assert "A" in body and "B" in body
    assert "C" not in body  # top-2 only
    assert "5" in body  # "5 insgesamt" summary
