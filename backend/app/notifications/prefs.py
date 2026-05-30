"""Per-user notification prefs — 5 booleans, defaults TRUE. (Moved from app.telegram.prefs in PLAN-027.)"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.db import AsyncSessionLocal


@dataclass(frozen=True)
class NotificationPrefs:
    user_id: int
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    web_push_enabled: bool


async def get_prefs(user_id: int) -> NotificationPrefs:
    """Return prefs; creates default row if missing (upsert no-op then SELECT)."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        result = await session.execute(
            text("""
                SELECT new_search_results, fav_sold, fav_price, fav_deleted, web_push_enabled
                FROM user_notification_prefs WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        r = result.one()
        await session.commit()
    return NotificationPrefs(user_id, r[0], r[1], r[2], r[3], r[4])


async def set_prefs(user_id: int, **partial: bool | None) -> NotificationPrefs:
    """Partial update: only fields passed as non-None are written.

    Uses a fixed parameterized statement with COALESCE so no field name is
    ever interpolated into the SQL string. None means "leave unchanged".
    """
    # Fast-path: nothing to write
    has_update = any(
        partial.get(f) is not None
        for f in ("new_search_results", "fav_sold", "fav_price", "fav_deleted", "web_push_enabled")
    )
    if not has_update:
        return await get_prefs(user_id)

    # COALESCE(:field, field) keeps existing value when :field is NULL (i.e. not passed).
    # All five field names are fixed literals — no dynamic SQL construction.
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        await session.execute(
            text("""
                UPDATE user_notification_prefs SET
                    new_search_results = COALESCE(:new_search_results, new_search_results),
                    fav_sold           = COALESCE(:fav_sold,           fav_sold),
                    fav_price          = COALESCE(:fav_price,          fav_price),
                    fav_deleted        = COALESCE(:fav_deleted,        fav_deleted),
                    web_push_enabled   = COALESCE(:web_push_enabled,   web_push_enabled),
                    updated_at         = now()
                WHERE user_id = :uid
            """),
            {
                "uid": user_id,
                "new_search_results": partial.get("new_search_results"),
                "fav_sold": partial.get("fav_sold"),
                "fav_price": partial.get("fav_price"),
                "fav_deleted": partial.get("fav_deleted"),
                "web_push_enabled": partial.get("web_push_enabled"),
            },
        )
        await session.commit()
    return await get_prefs(user_id)
