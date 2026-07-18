"""FastAPI dependencies for authentication."""
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cockpit_auth import (
    CockpitOperator,
    JwksUnreachable,
    verify_cockpit_bearer,
)
from app.config import settings
from app.db import get_session
from app.models import User
from app.security import decode_jwt


# ---------------------------------------------------------------------------
# Shared plain helper (not a FastAPI dependency)
# ---------------------------------------------------------------------------


async def _load_cookie_user(request: Request, db: AsyncSession) -> User:
    """Load the authenticated user from the session cookie.

    Mirrors get_current_user's logic; accepts an explicit session so it can be
    called from both get_current_user (cookie path) and require_any_admin
    (break-glass path) without nesting FastAPI Depends calls.
    """
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_jwt(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid session")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_approved:
        raise HTTPException(status_code=401, detail="Not authorized")
    return user


# ---------------------------------------------------------------------------
# Cookie-only dependencies (existing break-glass path — UNTOUCHED)
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    return await _load_cookie_user(request, session)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency: require role=admin, raise HTTP 403 otherwise."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ---------------------------------------------------------------------------
# Dual-auth dependency (cockpit RS256 assertion OR cookie break-glass)
# ---------------------------------------------------------------------------


async def require_any_admin(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CockpitOperator:
    """Accept either a cockpit RS256 Bearer assertion OR the existing cookie session.

    - Bearer present + COCKPIT_AUTH_ENABLED → verify RS256 assertion (contract §8).
    - Anything else → fall back to cookie break-glass (require_admin behaviour).

    Returns a CockpitOperator in both cases; jti=None on the cookie path.
    Never calls another Depends-function as a plain function — only plain helpers.
    """
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")

    if settings.COCKPIT_AUTH_ENABLED and has_bearer:
        try:
            return await verify_cockpit_bearer(request, db)
        except JwksUnreachable:
            raise HTTPException(503, "cockpit key set unreachable")
        except Exception as exc:
            # InvalidTokenError and any other JWT failure → 401
            raise HTTPException(401, "invalid cockpit assertion") from exc

    # Cookie break-glass path — call PLAIN helper with the injected db.
    user = await _load_cookie_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return CockpitOperator(
        google_id=user.google_id,
        email=user.email,
        jti=None,        # cookie path has no jti
        token_exp=None,
    )
