"""Tests for app.notifications.fav_sweep — favorites status-change sweep via Web Push."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.notifications import fav_sweep


async def _seed_user_with_sub(db_session) -> int:
    await db_session.execute(text("""
        INSERT INTO users (google_id, email, name, is_approved)
        VALUES ('fav-sweep-u', 'fav_sweep@example.com', 'Fav Sweep', TRUE)
    """))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'fav-sweep-u'")
    )).scalar_one()
    await db_session.execute(
        text("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (:u, 'https://fcm/fav', 'P', 'A')"""),
        {"u": uid},
    )
    await db_session.commit()
    return uid


async def _seed_favorite(db_session, uid: int, *, is_sold: bool, lk_sold: bool) -> int:
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text("""INSERT INTO listings (external_id, url, title, description, author, scraped_at, images, tags, is_sold)
                VALUES ('fav-ext', 'http://x/1', 'My Fav', 'd', 'a', :now, '[]', '[]', :sold)"""),
        {"now": now, "sold": is_sold},
    )
    lid = (await db_session.execute(
        text("SELECT id FROM listings WHERE external_id = 'fav-ext'")
    )).scalar_one()
    await db_session.execute(
        text("""INSERT INTO user_favorites (user_id, listing_id, last_known_is_sold, last_known_scraped_at)
                VALUES (:u, :l, :lk, :now)"""),
        {"u": uid, "l": lid, "lk": lk_sold, "now": now},
    )
    await db_session.commit()
    return lid


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_web_push_disabled(monkeypatch):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "")
    assert await fav_sweep.run_fav_status_sweep() == 0


@pytest.mark.asyncio
async def test_sweep_pushes_on_sold_transition(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 1
    assert m.await_count == 1
    payload = m.await_args.args[1]
    assert "Verkauft" in payload["body"]


@pytest.mark.asyncio
async def test_sweep_no_push_when_no_event(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    await _seed_favorite(db_session, uid, is_sold=False, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 0
    assert m.await_count == 0


@pytest.mark.asyncio
async def test_sweep_updates_snapshot_even_without_push(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    lid = await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)):
        await fav_sweep.run_fav_status_sweep()
    snap = (await db_session.execute(
        text("SELECT last_known_is_sold FROM user_favorites WHERE user_id=:u AND listing_id=:l"),
        {"u": uid, "l": lid},
    )).scalar_one()
    assert snap is True


@pytest.mark.asyncio
async def test_sweep_skips_user_without_subscription(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    # user with a favorite but NO push subscription
    await db_session.execute(text("""
        INSERT INTO users (google_id, email, name, is_approved)
        VALUES ('no-sub-u', 'nosub@example.com', 'No Sub', TRUE)
    """))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'no-sub-u'")
    )).scalar_one()
    await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 0
    assert m.await_count == 0
