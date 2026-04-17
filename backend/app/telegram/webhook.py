"""Inbound Telegram webhook — handles /start <token> for account linking."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.telegram import bot, link

logger = logging.getLogger(__name__)

# Absolute prefix — this router is mounted directly on the FastAPI app
router = APIRouter(prefix="/api/telegram", tags=["telegram-webhook"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict:
    if not settings.telegram_enabled:
        raise HTTPException(status_code=404, detail="Telegram subsystem disabled")
    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("telegram.webhook: bad/missing secret header")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("telegram.webhook: unparseable body")
        return {"ok": True}

    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text_body = (message.get("text") or "").strip()

    if not chat_id or not text_body:
        return {"ok": True}
    chat_id = int(chat_id)

    if text_body.startswith("/start "):
        token = text_body[len("/start "):].strip()
        user_id = await link.redeem_token(token, chat_id=chat_id)
        if user_id is not None:
            await bot.send_message(
                chat_id=chat_id,
                text_body=(
                    "✅ <b>Verbunden!</b>\n\n"
                    "Du erhältst jetzt Benachrichtigungen zu deinen gespeicherten Suchen und "
                    "Statusänderungen in deiner Merkliste.\n\n"
                    "Einstellungen: im Profil unter <i>Benachrichtigungen</i>."
                ),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text_body=(
                    "❌ Ungültiger oder abgelaufener Verbindungslink."
                    " Erzeuge einen neuen in deinem Profil."
                ),
            )
        return {"ok": True}

    await bot.send_message(
        chat_id=chat_id,
        text_body=(
            "Ich verstehe nur <code>/start &lt;token&gt;</code>."
            " Bitte verbinde deinen Account im Profil."
        ),
    )
    return {"ok": True}
