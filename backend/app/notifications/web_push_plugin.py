"""WebPushPlugin + shared send helper — delivers payloads as Web Push notifications."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pywebpush import WebPushException, webpush
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications import prefs as prefs_module
from app.notifications.base import MatchResult, NotificationPlugin

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Subscription:
    id: int
    endpoint: str
    p256dh: str
    auth: str


async def send_web_push_to_user(user_id: int, payload: dict) -> bool:
    """Send `payload` (dict with title/body/url/tag) to every push_subscription of `user_id`.

    Garbage-collects 404/410 (Gone/Not Found) subscriptions and bumps last_used_at
    only for subscriptions that actually delivered. Returns True if at least one
    delivery succeeded. VAPID config is the caller's responsibility (checked via
    settings.web_push_enabled before calling).
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
                    "WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).all()
    subs = [_Subscription(r[0], r[1], r[2], r[3]) for r in rows]
    if not subs:
        return False

    data = json.dumps(payload)
    succeeded_ids: list[int] = []
    stale_ids: list[int] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
            )
            succeeded_ids.append(sub.id)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response else None
            if status in (404, 410):
                stale_ids.append(sub.id)
                logger.info("web_push: stale subscription id=%d (status=%s) — removing", sub.id, status)
            else:
                logger.warning("web_push: send failed sub_id=%d status=%s err=%s", sub.id, status, exc)

    if stale_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM push_subscriptions WHERE user_id = :uid AND id = ANY(:ids)"),
                {"uid": user_id, "ids": stale_ids},
            )
            await session.commit()

    if succeeded_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE push_subscriptions SET last_used_at = now() WHERE id = ANY(:ids)"),
                {"ids": succeeded_ids},
            )
            await session.commit()

    return bool(succeeded_ids)


def _build_search_payload(match: MatchResult) -> dict:
    top = match.new_listing_titles[:3]
    body_lines = list(top)
    if match.total_new > len(top):
        body_lines.append(f"… und {match.total_new - len(top)} weitere")
    return {
        "title": f"Neue Treffer: {match.search_name}",
        "body": "\n".join(body_lines),
        "url": f"/?saved_search={match.saved_search_id}",
        "tag": f"saved-search-{match.saved_search_id}",
    }


class WebPushPlugin(NotificationPlugin):
    """Sends a SavedSearch digest to every push_subscription belonging to the user."""

    async def is_configured(self) -> bool:
        return settings.web_push_enabled

    async def send(self, match: MatchResult) -> bool:
        p = await prefs_module.get_prefs(match.user_id)
        if not p.web_push_enabled or not p.new_search_results:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d skipped (pref off)",
                match.saved_search_id, match.user_id,
            )
            return False
        ok = await send_web_push_to_user(match.user_id, _build_search_payload(match))
        if not ok:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d no delivery (no subs or all failed)",
                match.saved_search_id, match.user_id,
            )
        return ok
