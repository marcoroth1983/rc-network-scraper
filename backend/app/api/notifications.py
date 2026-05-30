"""REST endpoints for Web Push subscriptions, preferences, and VAPID public key."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.models import User
from app.notifications import prefs as prefs_module

router = APIRouter(prefix="/notifications", tags=["notifications"])


class _Keys(BaseModel):
    p256dh: str
    auth: str


class CreateSubscriptionDto(BaseModel):
    endpoint: str
    keys: _Keys
    user_agent: str | None = Field(default=None, max_length=512)
    device_label: str | None = Field(default=None, max_length=120)


class PushSubscriptionDto(BaseModel):
    id: int
    endpoint: str
    device_label: str | None
    user_agent: str | None
    last_used_at: datetime
    created_at: datetime


class PreferencesDto(BaseModel):
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    web_push_enabled: bool


class UpdatePreferencesDto(BaseModel):
    new_search_results: bool | None = None
    fav_sold: bool | None = None
    fav_price: bool | None = None
    fav_deleted: bool | None = None
    web_push_enabled: bool | None = None


class VapidKeyDto(BaseModel):
    public_key: str


def _to_prefs_dto(p: prefs_module.NotificationPrefs) -> PreferencesDto:
    return PreferencesDto(
        new_search_results=p.new_search_results,
        fav_sold=p.fav_sold,
        fav_price=p.fav_price,
        fav_deleted=p.fav_deleted,
        web_push_enabled=p.web_push_enabled,
    )


@router.get("/vapid-public-key", response_model=VapidKeyDto)
async def get_vapid_public_key() -> VapidKeyDto:
    if not settings.web_push_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Web Push not configured")
    return VapidKeyDto(public_key=settings.VAPID_PUBLIC_KEY)


@router.get("/subscriptions", response_model=list[PushSubscriptionDto])
async def list_subscriptions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PushSubscriptionDto]:
    rows = (
        await session.execute(
            text(
                "SELECT id, endpoint, device_label, user_agent, last_used_at, created_at "
                "FROM push_subscriptions WHERE user_id = :uid ORDER BY last_used_at DESC"
            ),
            {"uid": user.id},
        )
    ).all()
    return [
        PushSubscriptionDto(
            id=r[0], endpoint=r[1], device_label=r[2],
            user_agent=r[3], last_used_at=r[4], created_at=r[5],
        )
        for r in rows
    ]


@router.post("/subscriptions", response_model=PushSubscriptionDto, status_code=201)
async def create_subscription(
    dto: CreateSubscriptionDto,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PushSubscriptionDto:
    # ON CONFLICT (endpoint) — idempotent re-subscribe; re-assigning user_id is
    # intentional (a browser endpoint may move between accounts on one device).
    await session.execute(
        text("""
            INSERT INTO push_subscriptions
                (user_id, endpoint, p256dh, auth, user_agent, device_label, last_used_at)
            VALUES (:uid, :ep, :p, :a, :ua, :lbl, now())
            ON CONFLICT (endpoint) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth,
                user_agent = EXCLUDED.user_agent,
                device_label = EXCLUDED.device_label,
                last_used_at = now()
        """),
        {
            "uid": user.id, "ep": dto.endpoint,
            "p": dto.keys.p256dh, "a": dto.keys.auth,
            "ua": dto.user_agent, "lbl": dto.device_label,
        },
    )
    await session.commit()
    row = (
        await session.execute(
            text(
                "SELECT id, endpoint, device_label, user_agent, last_used_at, created_at "
                "FROM push_subscriptions WHERE endpoint = :ep"
            ),
            {"ep": dto.endpoint},
        )
    ).one()
    return PushSubscriptionDto(
        id=row[0], endpoint=row[1], device_label=row[2],
        user_agent=row[3], last_used_at=row[4], created_at=row[5],
    )


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        text("DELETE FROM push_subscriptions WHERE id = :id AND user_id = :uid"),
        {"id": sub_id, "uid": user.id},
    )
    await session.commit()
    if (result.rowcount or 0) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found")


@router.get("/preferences", response_model=PreferencesDto)
async def get_preferences(user: User = Depends(get_current_user)) -> PreferencesDto:
    return _to_prefs_dto(await prefs_module.get_prefs(user.id))


@router.put("/preferences", response_model=PreferencesDto)
async def put_preferences(
    dto: UpdatePreferencesDto,
    user: User = Depends(get_current_user),
) -> PreferencesDto:
    patch = {k: v for k, v in dto.model_dump(exclude_unset=True).items() if v is not None}
    return _to_prefs_dto(await prefs_module.set_prefs(user.id, **patch))
