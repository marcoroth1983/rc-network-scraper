"""Outbound Telegram Bot API client."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_BLOCKED_FRAGMENTS = ("blocked by the user", "bot was blocked", "user is deactivated")


async def send_message(
    chat_id: int,
    text_body: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """Send a message. Returns True on 200. On 403-blocked, clears user.telegram_chat_id."""
    if not settings.telegram_enabled:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text_body,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("telegram.bot: network error chat_id=%d err=%s", chat_id, exc)
        return False

    if resp.status_code == 200:
        logger.info("telegram.bot: sent chat_id=%d bytes=%d", chat_id, len(text_body))
        return True

    body = resp.text[:300]
    if resp.status_code == 403 and any(frag in body.lower() for frag in _BLOCKED_FRAGMENTS):
        logger.info(
            "telegram.bot: chat_id=%d blocked by user — clearing telegram_chat_id", chat_id
        )
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE users SET telegram_chat_id = NULL, telegram_linked_at = NULL"
                    " WHERE telegram_chat_id = :cid"
                ),
                {"cid": chat_id},
            )
            await session.commit()
    else:
        logger.warning(
            "telegram.bot: send FAILED chat_id=%d status=%d body=%s",
            chat_id,
            resp.status_code,
            body,
        )
    return False
