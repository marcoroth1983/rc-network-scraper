"""TelegramPlugin: delivers new-search-results digests via the notification registry."""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications.base import MatchResult, NotificationPlugin
from app.telegram import bot
from app.telegram import prefs as prefs_module

logger = logging.getLogger(__name__)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_digest(
    search_name: str,
    titles: list[str],
    ids: list[int],
    total: int,
    top_n: int,
) -> str:
    shown = list(zip(ids[:top_n], titles[:top_n]))
    lines = [
        f'• <a href="{settings.PUBLIC_BASE_URL}/listings/{i}">{_escape_html(t)}</a>'
        for i, t in shown
    ]
    header = f"🔔 <b>Neue Treffer: {_escape_html(search_name)}</b>\n"
    count_line = f"{total} neue Treffer" + (f" (Top {top_n}):" if total > top_n else ":")
    return header + count_line + "\n\n" + "\n".join(lines)


class TelegramPlugin(NotificationPlugin):
    """Sends a digest message to a user's linked Telegram chat."""

    async def is_configured(self) -> bool:
        return settings.telegram_enabled

    async def send(self, match: MatchResult) -> bool:
        # 1. Fetch chat_id
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                text("SELECT telegram_chat_id FROM users WHERE id = :uid"),
                {"uid": match.user_id},
            )
            chat_id = row.scalar()

        if chat_id is None:
            logger.info(
                "telegram.plugin: search_id=%d user_id=%d skipped (no telegram_chat_id)",
                match.saved_search_id,
                match.user_id,
            )
            return False

        # 2. Check pref
        p = await prefs_module.get_prefs(match.user_id)
        if not p.new_search_results:
            logger.info(
                "telegram.plugin: search_id=%d user_id=%d skipped (new_search_results=false)",
                match.saved_search_id,
                match.user_id,
            )
            return False

        # 3. Format + send
        message = _format_digest(
            search_name=match.search_name,
            titles=match.new_listing_titles,
            ids=match.new_listing_ids,
            total=match.total_new,
            top_n=settings.TELEGRAM_DIGEST_TOP_N,
        )
        ok = await bot.send_message(chat_id=chat_id, text_body=message)
        if ok:
            logger.info(
                "telegram.plugin: search_id=%d user_id=%d listings=%d sent ok",
                match.saved_search_id,
                match.user_id,
                match.total_new,
            )
        else:
            logger.warning(
                "telegram.plugin: search_id=%d user_id=%d listings=%d send FAILED",
                match.saved_search_id,
                match.user_id,
                match.total_new,
            )
        return ok
