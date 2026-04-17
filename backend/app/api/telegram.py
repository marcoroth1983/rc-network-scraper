"""User-facing Telegram endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.config import settings
from app.models import User
from app.telegram import link, prefs

# Relative prefix — mounted under parent /api
router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkResponse(BaseModel):
    deeplink: str
    expires_at: str


class PrefsBody(BaseModel):
    new_search_results: bool | None = None
    fav_sold: bool | None = None
    fav_price: bool | None = None
    fav_deleted: bool | None = None
    fav_indicator: bool | None = None


class PrefsResponse(BaseModel):
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    fav_indicator: bool


def _prefs_to_response(p: prefs.NotificationPrefs) -> PrefsResponse:
    return PrefsResponse(
        new_search_results=p.new_search_results,
        fav_sold=p.fav_sold,
        fav_price=p.fav_price,
        fav_deleted=p.fav_deleted,
        fav_indicator=p.fav_indicator,
    )


@router.post("/link", response_model=LinkResponse)
async def create_link(user: User = Depends(get_current_user)) -> LinkResponse:
    if not settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="Telegram subsystem not configured")
    t = await link.create_token(user.id)
    return LinkResponse(
        deeplink=f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={t.token}",
        expires_at=t.expires_at.isoformat(),
    )


@router.post("/unlink")
async def unlink(user: User = Depends(get_current_user)) -> dict:
    await link.unlink_user(user.id)
    return {"ok": True}


@router.get("/prefs", response_model=PrefsResponse)
async def get_prefs_endpoint(user: User = Depends(get_current_user)) -> PrefsResponse:
    return _prefs_to_response(await prefs.get_prefs(user.id))


@router.put("/prefs", response_model=PrefsResponse)
async def put_prefs(body: PrefsBody, user: User = Depends(get_current_user)) -> PrefsResponse:
    # exclude_unset=True: only fields actually sent by the client are forwarded.
    # Unsent fields keep their current DB value (true PATCH semantics).
    return _prefs_to_response(await prefs.set_prefs(user.id, **body.model_dump(exclude_unset=True)))
