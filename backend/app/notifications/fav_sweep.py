"""Favorites-status sweep: detect sold/price/deleted changes, deliver via Web Push.

Runs every FAV_SWEEP_INTERVAL_MIN minutes via APScheduler (registered in main.py).
Migrated from app.telegram.fav_sweep in PLAN-027.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications import prefs as prefs_module
from app.notifications.web_push_plugin import send_web_push_to_user

logger = logging.getLogger(__name__)


def _decimal_eq(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is b
    return Decimal(str(a)) == Decimal(str(b))


def _detect_events(row: dict, deleted_cutoff: datetime, user_prefs: prefs_module.NotificationPrefs) -> list[str]:
    """Return plain-text event lines based on diffs + per-user prefs."""
    events: list[str] = []
    lk_sold = row["last_known_is_sold"]
    lk_price = row["last_known_price_numeric"]
    lk_scr = row["last_known_scraped_at"]
    title = row["title"]
    is_sold = row["is_sold"]
    price = row["price_numeric"]
    scraped_at = row["scraped_at"]

    if lk_sold is not None and lk_sold is False and is_sold is True and user_prefs.fav_sold:
        events.append(f"Verkauft: {title}")

    if (
        lk_price is not None
        and price is not None
        and not _decimal_eq(lk_price, price)
        and user_prefs.fav_price
    ):
        events.append(f"Preis geändert: {title} — {float(lk_price):.0f}€ → {float(price):.0f}€")

    listing_gone = scraped_at is not None and scraped_at < deleted_cutoff
    snapshot_alive = lk_scr is not None and lk_scr >= deleted_cutoff
    if listing_gone and snapshot_alive and user_prefs.fav_deleted:
        events.append(f"Gelöscht: {title}")

    return events


async def run_fav_status_sweep() -> int:
    """Scan user_favorites, diff against snapshots, push per-favorite event digests.

    Returns the number of users a push was delivered to.
    Always updates snapshots (even when no push sent / pref disabled).
    """
    if not settings.web_push_enabled:
        return 0

    deleted_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.FAV_DELETED_DAYS)
    sent_count = 0

    try:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT uf.user_id, uf.listing_id,
                           uf.last_known_is_sold, uf.last_known_price_numeric,
                           uf.last_known_scraped_at,
                           l.title, l.url,
                           l.is_sold, l.price_numeric, l.scraped_at
                    FROM user_favorites uf
                    JOIN listings l ON l.id = uf.listing_id
                    WHERE EXISTS (
                        SELECT 1 FROM push_subscriptions ps WHERE ps.user_id = uf.user_id
                    )
                """)
            )
            favorites = [row._asdict() for row in rows.all()]
    except Exception:
        logger.exception("notifications.sweep.fav: load FAILED — aborting sweep")
        return 0

    for fav in favorites:
        user_id = fav["user_id"]
        listing_id = fav["listing_id"]
        try:
            user_prefs = await prefs_module.get_prefs(user_id)
            events = _detect_events(fav, deleted_cutoff, user_prefs)

            if events and user_prefs.web_push_enabled:
                payload = {
                    "title": "Merkliste aktualisiert",
                    "body": "\n".join(events),
                    "url": f"/listings/{listing_id}",
                    "tag": f"fav-{listing_id}",
                }
                if await send_web_push_to_user(user_id, payload):
                    sent_count += 1
                    logger.info(
                        "notifications.sweep.fav: user_id=%d listing_id=%d triggers=%d pushed",
                        user_id, listing_id, len(events),
                    )

            # Always update snapshot (even when no push sent / pref disabled)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("""
                        UPDATE user_favorites
                        SET last_known_is_sold = :sold,
                            last_known_price_numeric = :price,
                            last_known_scraped_at = :scr
                        WHERE user_id = :u AND listing_id = :l
                    """),
                    {
                        "sold": fav["is_sold"], "price": fav["price_numeric"],
                        "scr": fav["scraped_at"], "u": user_id, "l": listing_id,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "notifications.sweep.fav: user_id=%d listing_id=%d FAILED — skipping",
                user_id, listing_id,
            )
            continue

    return sent_count
