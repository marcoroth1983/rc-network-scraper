"""Tests for WebPushPlugin + send_web_push_to_user — mocks pywebpush, real DB rows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pywebpush import WebPushException
from sqlalchemy import text

from app.notifications.base import MatchResult
from app.notifications.web_push_plugin import WebPushPlugin, send_web_push_to_user


def _match(user_id: int) -> MatchResult:
    return MatchResult(
        saved_search_id=1, search_name="Wing 2.5m", user_id=user_id,
        new_listing_ids=[10, 11, 12], new_listing_titles=["A", "B", "C"], total_new=3,
    )


@pytest.mark.asyncio
async def test_is_configured_false_when_no_vapid(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    assert await WebPushPlugin().is_configured() is False


@pytest.mark.asyncio
async def test_is_configured_true_when_vapid_set(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:x@y")
    assert await WebPushPlugin().is_configured() is True


@pytest.mark.asyncio
async def test_send_returns_false_when_pref_disabled(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    fake = MagicMock(web_push_enabled=False, new_search_results=True)
    monkeypatch.setattr(mod.prefs_module, "get_prefs", AsyncMock(return_value=fake))
    assert await WebPushPlugin().send(_match(seeded_user_with_subs.user_id)) is False


@pytest.mark.asyncio
async def test_send_returns_false_when_user_has_no_subscriptions(monkeypatch, db_user):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    assert await WebPushPlugin().send(_match(db_user.id)) is False


@pytest.mark.asyncio
async def test_send_calls_webpush_for_each_subscription(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    calls: list[dict] = []
    monkeypatch.setattr(mod, "webpush", lambda **kw: calls.append(kw))
    ok = await WebPushPlugin().send(_match(seeded_user_with_subs.user_id))
    assert ok is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_helper_deletes_subscription_on_410_gone(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=410)
    def raise_gone(**_):
        raise WebPushException("gone", response=response)
    monkeypatch.setattr(mod, "webpush", raise_gone)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_helper_deletes_subscription_on_404(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=404)
    def raise_404(**_):
        raise WebPushException("not found", response=response)
    monkeypatch.setattr(mod, "webpush", raise_404)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_helper_does_not_delete_other_users_subscription_on_410(
    monkeypatch, seeded_user_with_subs, other_user_with_sub, db_session
):
    """GC must be scoped by user_id — a 410 for user A never removes user B's row."""
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=410)
    def raise_gone(**_):
        raise WebPushException("gone", response=response)
    monkeypatch.setattr(mod, "webpush", raise_gone)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": other_user_with_sub.user_id},
    )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_helper_returns_false_when_all_endpoints_fail_with_500(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=500)
    def raise_500(**_):
        raise WebPushException("oops", response=response)
    monkeypatch.setattr(mod, "webpush", raise_500)
    assert await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"}) is False
