"""Telegram deep-link token lifecycle: create, redeem, unlink."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkToken:
    token: str
    expires_at: datetime


async def create_token(user_id: int) -> LinkToken:
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.TELEGRAM_LINK_TOKEN_TTL_MIN)
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO telegram_link_tokens (token, user_id, expires_at)
                VALUES (:t, :uid, :exp)
            """),
            {"t": token, "uid": user_id, "exp": expires_at},
        )
        await session.commit()
    logger.info(
        "telegram.link: token=%s... for user_id=%d expires_at=%s",
        token[:6],
        user_id,
        expires_at.isoformat(),
    )
    return LinkToken(token=token, expires_at=expires_at)


async def redeem_token(token: str, chat_id: int) -> int | None:
    """Single-use redemption. Returns user_id on success, None otherwise."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT user_id, used_at, expires_at FROM telegram_link_tokens WHERE token = :t"),
            {"t": token},
        )
        r = row.one_or_none()
        if r is None:
            logger.info("telegram.link: unknown token chat_id=%d", chat_id)
            return None
        user_id, used_at, expires_at = r
        if used_at is not None or expires_at < now:
            logger.info(
                "telegram.link: invalid/expired token user_id=%d chat_id=%d", user_id, chat_id
            )
            return None
        await session.execute(
            text("UPDATE telegram_link_tokens SET used_at = :now WHERE token = :t"),
            {"now": now, "t": token},
        )
        await session.execute(
            text(
                "UPDATE users SET telegram_chat_id = :cid, telegram_linked_at = :now WHERE id = :uid"
            ),
            {"cid": chat_id, "now": now, "uid": user_id},
        )
        await session.commit()
    logger.info(
        "telegram.link: redeemed token=%s... user_id=%d chat_id=%d", token[:6], user_id, chat_id
    )
    return user_id


async def unlink_user(user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE users SET telegram_chat_id = NULL, telegram_linked_at = NULL WHERE id = :uid"
            ),
            {"uid": user_id},
        )
        await session.commit()
    logger.info("telegram.link: unlinked user_id=%d", user_id)


async def cleanup_expired_tokens(older_than_days: int = 7) -> int:
    """Delete tokens whose expires_at is older than the threshold. Called from fav sweep."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "DELETE FROM telegram_link_tokens WHERE expires_at < now() - (:d || ' days')::interval"
            ),
            {"d": str(older_than_days)},
        )
        await session.commit()
    return result.rowcount or 0
