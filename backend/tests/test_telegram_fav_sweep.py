"""Tests for app.telegram.fav_sweep — favorites status-change sweep."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import app.db as _app_db
from app.telegram import fav_sweep, prefs
from app.config import settings
from sqlalchemy import text


async def _insert_favorite(user_id: int, listing_id: int, snapshot: dict | None = None) -> None:
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text("INSERT INTO user_favorites (user_id, listing_id) VALUES (:u, :l) ON CONFLICT DO NOTHING"),
            {"u": user_id, "l": listing_id},
        )
        if snapshot:
            await s.execute(
                text("""
                    UPDATE user_favorites SET
                      last_known_is_sold = :sold,
                      last_known_price_numeric = :price,
                      last_known_scraped_at = :scr
                    WHERE user_id = :u AND listing_id = :l
                """),
                {
                    "sold": snapshot.get("sold"),
                    "price": snapshot.get("price"),
                    "scr": snapshot.get("scr"),
                    "u": user_id,
                    "l": listing_id,
                },
            )
        await s.commit()


@pytest.mark.asyncio
async def test_sold_transition_triggers_message(db_user_linked, db_listing, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    now = datetime.now(timezone.utc)
    await _insert_favorite(
        db_user_linked.user_id,
        db_listing.id,
        snapshot={"sold": False, "price": 100, "ind": "fair", "scr": now},
    )
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE listings SET is_sold = TRUE WHERE id = :i"), {"i": db_listing.id}
        )
        await s.commit()
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 1
    assert "Verkauft" in mock.call_args.kwargs["text_body"]


@pytest.mark.asyncio
async def test_price_change_triggers(db_user_linked, db_listing, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    now = datetime.now(timezone.utc)
    await _insert_favorite(
        db_user_linked.user_id,
        db_listing.id,
        snapshot={"sold": False, "price": 200, "ind": None, "scr": now},
    )
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE listings SET price_numeric = 150 WHERE id = :i"), {"i": db_listing.id}
        )
        await s.commit()
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 1
    assert "Preis" in mock.call_args.kwargs["text_body"]


@pytest.mark.asyncio
async def test_deleted_triggers_when_scraped_at_stale(db_user_linked, db_listing, monkeypatch):
    """listing.scraped_at = 4 days ago, snapshot was 1 day ago (was alive)."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    now = datetime.now(timezone.utc)
    stale_scraped = now - timedelta(days=4)
    recent_snapshot = now - timedelta(days=1)
    await _insert_favorite(
        db_user_linked.user_id,
        db_listing.id,
        snapshot={"sold": False, "price": None, "ind": None, "scr": recent_snapshot},
    )
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE listings SET scraped_at = :t WHERE id = :i"),
            {"t": stale_scraped, "i": db_listing.id},
        )
        await s.commit()
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 1
    assert "Gelöscht" in mock.call_args.kwargs["text_body"]


@pytest.mark.asyncio
async def test_pref_disabled_still_updates_snapshot_no_message(db_user_linked, db_listing, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    await prefs.set_prefs(db_user_linked.user_id, fav_sold=False)
    now = datetime.now(timezone.utc)
    await _insert_favorite(
        db_user_linked.user_id,
        db_listing.id,
        snapshot={"sold": False, "price": None, "ind": None, "scr": now},
    )
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE listings SET is_sold = TRUE WHERE id = :i"), {"i": db_listing.id}
        )
        await s.commit()
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        await fav_sweep.run_fav_status_sweep()
        mock.assert_not_called()
    # Snapshot must still be updated
    async with _app_db.AsyncSessionLocal() as s:
        row = await s.execute(
            text(
                "SELECT last_known_is_sold FROM user_favorites WHERE user_id = :u AND listing_id = :l"
            ),
            {"u": db_user_linked.user_id, "l": db_listing.id},
        )
        assert row.scalar() is True


@pytest.mark.asyncio
async def test_per_favorite_exception_does_not_abort_sweep(db_user_linked, monkeypatch):
    """An exception in the middle favorite must not abort the whole sweep."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    now = datetime.now(timezone.utc)

    # Insert 3 listings
    async with _app_db.AsyncSessionLocal() as s:
        for ext_id, title in [("sweep-a", "Alpha"), ("sweep-b", "Beta"), ("sweep-c", "Gamma")]:
            await s.execute(
                text("""
                    INSERT INTO listings (external_id, url, title, description, author, scraped_at, images, tags)
                    VALUES (:e, 'http://x.com', :t, 'desc', 'a', :now, '[]', '[]')
                    ON CONFLICT (external_id) DO NOTHING
                """),
                {"e": ext_id, "t": title, "now": now},
            )
        await s.commit()
        ids = {}
        for ext_id in ["sweep-a", "sweep-b", "sweep-c"]:
            r = await s.execute(text("SELECT id FROM listings WHERE external_id = :e"), {"e": ext_id})
            ids[ext_id] = r.scalar_one()

    for ext_id in ["sweep-a", "sweep-b", "sweep-c"]:
        await _insert_favorite(
            db_user_linked.user_id,
            ids[ext_id],
            snapshot={"sold": False, "price": None, "ind": None, "scr": now},
        )

    # Mark all three sold (will trigger messages for A and C)
    async with _app_db.AsyncSessionLocal() as s:
        for ext_id in ["sweep-a", "sweep-b", "sweep-c"]:
            await s.execute(
                text("UPDATE listings SET is_sold = TRUE WHERE id = :i"), {"i": ids[ext_id]}
            )
        await s.commit()

    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        # Fail on the second call (Beta)
        if call_count == 2:
            raise RuntimeError("simulated failure")
        return True

    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(side_effect=_side_effect)):
        sent = await fav_sweep.run_fav_status_sweep()

    # 2 of 3 succeed (one raised, one was never sent due to exception)
    assert sent >= 1


@pytest.mark.asyncio
async def test_no_change_no_message(db_user_linked, db_listing, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    now = datetime.now(timezone.utc)
    await _insert_favorite(
        db_user_linked.user_id,
        db_listing.id,
        snapshot={"sold": False, "price": None, "ind": None, "scr": now},
    )
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 0
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_noop_when_telegram_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 0
