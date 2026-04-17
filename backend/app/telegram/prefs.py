"""Per-user notification prefs — 5 booleans, defaults TRUE."""

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
    fav_indicator: bool


async def get_prefs(user_id: int) -> NotificationPrefs:
    """Return prefs; creates default row if missing (upsert no-op then SELECT)."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        result = await session.execute(
            text("""
                SELECT new_search_results, fav_sold, fav_price, fav_deleted, fav_indicator
                FROM user_notification_prefs WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        r = result.one()
        await session.commit()
    return NotificationPrefs(user_id, r[0], r[1], r[2], r[3], r[4])


async def set_prefs(user_id: int, **partial: bool | None) -> NotificationPrefs:
    """Partial update: only fields passed as non-None are written."""
    updates = []
    params: dict = {"uid": user_id}
    for field in ("new_search_results", "fav_sold", "fav_price", "fav_deleted", "fav_indicator"):
        val = partial.get(field)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val
    if not updates:
        return await get_prefs(user_id)

    set_clause = ", ".join(updates + ["updated_at = now()"])
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        await session.execute(
            text(f"UPDATE user_notification_prefs SET {set_clause} WHERE user_id = :uid"),
            params,
        )
        await session.commit()
    return await get_prefs(user_id)
