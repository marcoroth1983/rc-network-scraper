"""Tests for app.telegram.link — token lifecycle."""

import pytest
import app.db as _app_db
from app.telegram import link
from sqlalchemy import text


@pytest.mark.asyncio
async def test_create_token_distinct(db_user):
    t1 = await link.create_token(user_id=db_user.id)
    t2 = await link.create_token(user_id=db_user.id)
    assert t1.token != t2.token
    assert len(t1.token) >= 32


@pytest.mark.asyncio
async def test_redeem_valid_token_sets_chat_id(db_user):
    t = await link.create_token(user_id=db_user.id)
    uid = await link.redeem_token(t.token, chat_id=999)
    assert uid == db_user.id
    # Second redemption fails (single-use)
    assert await link.redeem_token(t.token, chat_id=999) is None


@pytest.mark.asyncio
async def test_redeem_expired_token_returns_none(db_user):
    t = await link.create_token(user_id=db_user.id)
    async with _app_db.AsyncSessionLocal() as s:
        await s.execute(
            text(
                "UPDATE telegram_link_tokens SET expires_at = now() - interval '1 minute'"
                " WHERE token = :t"
            ),
            {"t": t.token},
        )
        await s.commit()
    assert await link.redeem_token(t.token, chat_id=999) is None


@pytest.mark.asyncio
async def test_redeem_unknown_token(db_user):
    assert await link.redeem_token("does-not-exist", chat_id=1) is None


@pytest.mark.asyncio
async def test_unlink_clears_chat_id(db_user_linked):
    await link.unlink_user(db_user_linked.user_id)
    async with _app_db.AsyncSessionLocal() as s:
        row = await s.execute(
            text("SELECT telegram_chat_id FROM users WHERE id = :u"),
            {"u": db_user_linked.user_id},
        )
        assert row.scalar() is None
