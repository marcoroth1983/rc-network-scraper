"""Admin-only endpoints: LLM cascade management."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.analysis import model_cascade
from app.api.deps import require_admin
from app.db import AsyncSessionLocal
from app.models import User
from sqlalchemy import text

router = APIRouter(prefix="/admin", tags=["admin"])


class UserRow(BaseModel):
    id: int
    email: str
    name: str | None
    is_approved: bool
    role: str
    created_at: datetime
    last_seen_at: datetime | None


class ApprovalUpdate(BaseModel):
    is_approved: bool


class LLMModelRow(BaseModel):
    model_id: str
    position: int
    is_active: bool
    active_now: bool
    context_length: int | None
    created_upstream: datetime | None
    added_at: datetime
    last_refresh_at: datetime
    consecutive_failures: int
    disabled_until: datetime | None
    last_error: str | None


async def _fetch_all_rows() -> list[LLMModelRow]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT
                model_id,
                position,
                is_active,
                context_length,
                created_upstream,
                added_at,
                last_refresh_at,
                consecutive_failures,
                disabled_until,
                last_error
            FROM llm_models
            ORDER BY position ASC
        """))
        rows = result.all()

    return [
        LLMModelRow(
            model_id=row.model_id,
            position=row.position,
            is_active=row.is_active,
            active_now=(
                row.is_active
                and (row.disabled_until is None or row.disabled_until < now)
            ),
            context_length=row.context_length,
            created_upstream=row.created_upstream,
            added_at=row.added_at,
            last_refresh_at=row.last_refresh_at,
            consecutive_failures=row.consecutive_failures,
            disabled_until=row.disabled_until,
            last_error=row.last_error,
        )
        for row in rows
    ]


@router.get("/llm-models", response_model=list[LLMModelRow])
async def list_llm_models(_: User = Depends(require_admin)) -> list[LLMModelRow]:
    """Return all cascade models with live active_now computed field."""
    return await _fetch_all_rows()


@router.post("/llm-models/refresh", response_model=list[LLMModelRow])
async def refresh_llm_models(_: User = Depends(require_admin)) -> list[LLMModelRow]:
    """Trigger an immediate cascade refresh from OpenRouter, return updated rows."""
    await model_cascade.refresh_from_openrouter()
    return await _fetch_all_rows()


@router.get("/users", response_model=list[UserRow])
async def list_users(_: User = Depends(require_admin)) -> list[UserRow]:
    """Return all users: not-yet-approved first; within each group: newest-registered first."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT id, email, name, is_approved, role, created_at, last_seen_at
            FROM users
            ORDER BY is_approved ASC, created_at DESC
        """))
        rows = result.all()
    return [
        UserRow(
            id=row.id,
            email=row.email,
            name=row.name,
            is_approved=row.is_approved,
            role=row.role,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows
    ]


@router.patch("/users/{user_id}/approval", response_model=UserRow)
async def set_user_approval(
    user_id: int,
    body: ApprovalUpdate,
    current_admin: User = Depends(require_admin),
) -> UserRow:
    """Set a user's is_approved flag. Returns the updated row.

    Refuses to revoke the calling admin's own approval (self-lockout guard).
    """
    if user_id == current_admin.id and not body.is_approved:
        raise HTTPException(status_code=400, detail="Cannot revoke your own approval")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                UPDATE users SET is_approved = :is_approved
                WHERE id = :user_id
                RETURNING id, email, name, is_approved, role, created_at, last_seen_at
            """),
            {"is_approved": body.is_approved, "user_id": user_id},
        )
        row = result.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="User not found")

        await session.commit()

    return UserRow(
        id=row.id,
        email=row.email,
        name=row.name,
        is_approved=row.is_approved,
        role=row.role,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


class MetricsSummary(BaseModel):
    users_total: int
    users_approved: int
    users_pending: int
    users_active_7d: int
    users_active_30d: int
    listings_total: int
    favorites_total: int
    saved_searches_total: int


class TimeseriesPoint(BaseModel):
    day: str  # ISO date (YYYY-MM-DD)
    value: int


class MetricsTimeseries(BaseModel):
    days: int
    listings_new: list[TimeseriesPoint]
    listings_closed: list[TimeseriesPoint]
    users_new: list[TimeseriesPoint]
    logins: list[TimeseriesPoint]
    notifications: list[TimeseriesPoint]


@router.get("/metrics/summary", response_model=MetricsSummary)
async def metrics_summary(_: User = Depends(require_admin)) -> MetricsSummary:
    """Snapshot counts for KPI tiles."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text("""
            SELECT
                (SELECT count(*) FROM users)                                          AS users_total,
                (SELECT count(*) FROM users WHERE is_approved)                        AS users_approved,
                (SELECT count(*) FROM users WHERE NOT is_approved)                    AS users_pending,
                (SELECT count(*) FROM users WHERE last_seen_at >= now() - interval '7 days')  AS active_7d,
                (SELECT count(*) FROM users WHERE last_seen_at >= now() - interval '30 days') AS active_30d,
                (SELECT count(*) FROM listings)                                       AS listings_total,
                (SELECT count(*) FROM user_favorites)                                 AS favorites_total,
                (SELECT count(*) FROM saved_searches)                                 AS saved_total
        """))).one()
    return MetricsSummary(
        users_total=row.users_total,
        users_approved=row.users_approved,
        users_pending=row.users_pending,
        users_active_7d=row.active_7d,
        users_active_30d=row.active_30d,
        listings_total=row.listings_total,
        favorites_total=row.favorites_total,
        saved_searches_total=row.saved_total,
    )


# Fixed, server-controlled series definitions (no user input in SQL identifiers).
_SERIES_SQL: dict[str, str] = {
    "listings_new": "SELECT created_at::date AS d, count(*) AS c FROM listings "
                    "WHERE created_at >= now()::date - make_interval(days => :n - 1) GROUP BY d",
    "listings_closed": "SELECT sold_at::date AS d, count(*) AS c FROM listings "
                       "WHERE sold_at IS NOT NULL AND sold_at >= now()::date - make_interval(days => :n - 1) GROUP BY d",
    "users_new": "SELECT created_at::date AS d, count(*) AS c FROM users "
                 "WHERE created_at >= now()::date - make_interval(days => :n - 1) GROUP BY d",
    "logins": "SELECT logged_in_at::date AS d, count(*) AS c FROM login_events "
              "WHERE logged_in_at >= now()::date - make_interval(days => :n - 1) GROUP BY d",
    "notifications": "SELECT notified_at::date AS d, count(*) AS c FROM search_notifications "
                     "WHERE notified_at >= now()::date - make_interval(days => :n - 1) GROUP BY d",
}


async def _series(session, key: str, days: int) -> list[TimeseriesPoint]:
    """Run a fixed series query and zero-fill every day in the window."""
    rows = (await session.execute(text(_SERIES_SQL[key]), {"n": days})).all()
    counts = {r.d.isoformat(): r.c for r in rows}
    # Zero-fill the full window so charts have a continuous x-axis.
    base = (await session.execute(
        text("SELECT (now()::date - make_interval(days => :n - 1))::date AS start"), {"n": days}
    )).scalar_one()
    out: list[TimeseriesPoint] = []
    for i in range(days):
        day = (base + timedelta(days=i)).isoformat()
        out.append(TimeseriesPoint(day=day, value=counts.get(day, 0)))
    return out


@router.get("/metrics/timeseries", response_model=MetricsTimeseries)
async def metrics_timeseries(
    days: int = 30,
    _: User = Depends(require_admin),
) -> MetricsTimeseries:
    """Per-day counts for the selected window. days clamped to 1..365."""
    days = max(1, min(days, 365))
    async with AsyncSessionLocal() as session:
        return MetricsTimeseries(
            days=days,
            listings_new=await _series(session, "listings_new", days),
            listings_closed=await _series(session, "listings_closed", days),
            users_new=await _series(session, "users_new", days),
            logins=await _series(session, "logins", days),
            notifications=await _series(session, "notifications", days),
        )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    current_admin: User = Depends(require_admin),
) -> None:
    """DSGVO hard-delete: remove a user and all owned data (cascade).

    Cascades: saved_searches (+ their notifications), user_favorites,
    push_subscriptions, login_events. Refuses self-deletion (lockout guard).
    """
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM users WHERE id = :uid RETURNING id"),
            {"uid": user_id},
        )
        if result.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found")
        await session.commit()


class UserStats(BaseModel):
    user_id: int
    saved_searches: int
    favorites: int
    push_devices: int
    logins_total: int
    logins_30d: int
    created_at: datetime
    last_seen_at: datetime | None


@router.get("/users/{user_id}/stats", response_model=UserStats)
async def user_stats(user_id: int, _: User = Depends(require_admin)) -> UserStats:
    """Per-user activity counts for the analysis dialog."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text("""
            SELECT
                u.id AS user_id,
                (SELECT count(*) FROM saved_searches    WHERE user_id = u.id) AS saved_searches,
                (SELECT count(*) FROM user_favorites     WHERE user_id = u.id) AS favorites,
                (SELECT count(*) FROM push_subscriptions WHERE user_id = u.id) AS push_devices,
                (SELECT count(*) FROM login_events       WHERE user_id = u.id) AS logins_total,
                (SELECT count(*) FROM login_events       WHERE user_id = u.id
                    AND logged_in_at >= now() - interval '30 days')           AS logins_30d,
                u.created_at, u.last_seen_at
            FROM users u WHERE u.id = :uid
        """), {"uid": user_id})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserStats(
        user_id=row.user_id, saved_searches=row.saved_searches, favorites=row.favorites,
        push_devices=row.push_devices, logins_total=row.logins_total,
        logins_30d=row.logins_30d, created_at=row.created_at, last_seen_at=row.last_seen_at,
    )
