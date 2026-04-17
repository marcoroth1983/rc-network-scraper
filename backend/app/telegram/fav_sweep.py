"""Favorites-status sweep: detect sold/price/deleted/indicator changes.

Runs every TELEGRAM_FAV_SWEEP_INTERVAL_MIN minutes via APScheduler (registered in main.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.telegram import bot
from app.telegram import link
from app.telegram import prefs as prefs_module

logger = logging.getLogger(__name__)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _decimal_eq(a: object, b: object) -> bool:
    """Compare two NUMERIC values for equality, tolerating None."""
    if a is None or b is None:
        return a is b  # both must be None
    return Decimal(str(a)) == Decimal(str(b))


def _detect_events(row: tuple, deleted_cutoff: datetime, user_prefs: prefs_module.NotificationPrefs) -> list[str]:
    """Return list of formatted event lines based on diffs + per-user prefs."""
    events = []
    (_, _, lk_sold, lk_price, lk_ind, lk_scr, title, _, is_sold, price, ind, scraped_at, _) = row

    if lk_sold is not None and lk_sold is False and is_sold is True and user_prefs.fav_sold:
        events.append(f"🏷️ <b>Verkauft:</b> {_escape_html(title)}")

    if (
        lk_price is not None
        and price is not None
        and not _decimal_eq(lk_price, price)
        and user_prefs.fav_price
    ):
        events.append(
            f"💶 <b>Preis geändert:</b> {_escape_html(title)}"
            f" — {float(lk_price):.0f}€ → {float(price):.0f}€"
        )

    # Deleted: listing hasn't been re-scraped for TELEGRAM_FAV_DELETED_DAYS days
    # AND snapshot was still "alive" (scraped_at within the cutoff) at last sweep
    listing_gone = scraped_at is not None and scraped_at < deleted_cutoff
    snapshot_alive = lk_scr is not None and lk_scr >= deleted_cutoff
    if listing_gone and snapshot_alive and user_prefs.fav_deleted:
        events.append(f"🗑️ <b>Gelöscht:</b> {_escape_html(title)}")

    if lk_ind is not None and ind is not None and lk_ind != ind and user_prefs.fav_indicator:
        events.append(f"📊 <b>Preisbewertung:</b> {_escape_html(title)} — {lk_ind} → {ind}")

    return events


async def run_fav_status_sweep() -> int:
    """Scan user_favorites, diff against snapshots, send per-favorite event messages.

    Returns number of Telegram messages successfully sent.
    Always updates snapshots (even when no message was sent / pref disabled).
    """
    if not settings.telegram_enabled:
        return 0

    deleted_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TELEGRAM_FAV_DELETED_DAYS)
    sent_count = 0

    try:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT uf.user_id, uf.listing_id,
                           uf.last_known_is_sold, uf.last_known_price_numeric,
                           uf.last_known_price_indicator, uf.last_known_scraped_at,
                           l.title, l.url,
                           l.is_sold, l.price_numeric, l.price_indicator, l.scraped_at,
                           u.telegram_chat_id
                    FROM user_favorites uf
                    JOIN listings l ON l.id = uf.listing_id
                    JOIN users u ON u.id = uf.user_id
                    WHERE u.telegram_chat_id IS NOT NULL
                """)
            )
            favorites = rows.all()
    except Exception:
        logger.exception("telegram.sweep.fav: load FAILED — aborting sweep")
        return 0

    for fav in favorites:
        user_id, listing_id = fav[0], fav[1]
        try:
            user_prefs = await prefs_module.get_prefs(user_id)
            events = _detect_events(fav, deleted_cutoff, user_prefs)

            if events:
                chat_id = fav[-1]
                msg = (
                    "\n\n".join(events)
                    + f'\n\n<a href="{settings.PUBLIC_BASE_URL}/listings/{listing_id}">Zum Inserat</a>'
                )
                if await bot.send_message(chat_id=chat_id, text_body=msg):
                    sent_count += 1
                    logger.info(
                        "telegram.sweep.fav: user_id=%d listing_id=%d triggers=%d sent",
                        user_id,
                        listing_id,
                        len(events),
                    )

            # Always update snapshot (even when no message sent / pref disabled)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("""
                        UPDATE user_favorites
                        SET last_known_is_sold = :sold,
                            last_known_price_numeric = :price,
                            last_known_price_indicator = :ind,
                            last_known_scraped_at = :scr
                        WHERE user_id = :u AND listing_id = :l
                    """),
                    {
                        "sold": fav[8],
                        "price": fav[9],
                        "ind": fav[10],
                        "scr": fav[11],
                        "u": user_id,
                        "l": listing_id,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "telegram.sweep.fav: user_id=%d listing_id=%d FAILED — skipping",
                user_id,
                listing_id,
            )
            continue

    # Housekeeping: prune old link tokens
    try:
        deleted = await link.cleanup_expired_tokens(older_than_days=7)
        if deleted:
            logger.info("telegram.sweep.fav: pruned %d expired link tokens", deleted)
    except Exception:
        logger.exception("telegram.sweep.fav: token cleanup failed")

    return sent_count
