"""Google OAuth2 flow + session management."""
import secrets
from urllib.parse import quote, unquote, urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.models import User
from app.security import create_jwt

router = APIRouter()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _cookie_domain_kwargs() -> dict[str, str]:
    """Return domain kwarg for set_cookie/delete_cookie when COOKIE_DOMAIN is configured."""
    return {"domain": settings.COOKIE_DOMAIN} if settings.COOKIE_DOMAIN else {}


def _cookie_kwargs(*, max_age: int | None = None) -> dict:
    """Return full attribute dict for set_cookie/delete_cookie calls.

    Centralises path, httponly, samesite, secure, and domain so every call site
    is guaranteed to use identical attributes — mismatches silently prevent
    browsers from deleting cookies (HIGH-1).
    """
    kwargs: dict = {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": settings.COOKIE_SECURE,
        **_cookie_domain_kwargs(),
    }
    if max_age is not None:
        kwargs["max_age"] = max_age
    return kwargs


def _clear_oauth_cookies(resp: RedirectResponse) -> None:
    """Delete oauth_state and oauth_return cookies with fully-matched attributes."""
    resp.delete_cookie("oauth_state", **_cookie_kwargs())
    resp.delete_cookie("oauth_return", **_cookie_kwargs())


def _resolve_return_base(return_to: str | None) -> str:
    """Validate return_to against the exact-match allowlist; fall back to FRONTEND_URL.

    Reads settings live — correct; tests can monkeypatch the singleton.
    """
    allowed = {settings.FRONTEND_URL, settings.ADMIN_URL}
    return return_to if return_to in allowed else settings.FRONTEND_URL


@router.get("/auth/google")
async def auth_google(
    request: Request,
    return_to: str | None = Query(default=None),
) -> RedirectResponse:
    """Redirect browser to Google OAuth consent screen."""
    state = secrets.token_hex(16)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{settings.PUBLIC_BASE_URL}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    return_base = _resolve_return_base(return_to)
    response = RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie("oauth_state", state, **_cookie_kwargs(max_age=300))
    response.set_cookie("oauth_return", quote(return_base, safe=""), **_cookie_kwargs(max_age=300))
    return response


@router.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Google OAuth callback."""
    raw_return = request.cookies.get("oauth_return")
    base = _resolve_return_base(unquote(raw_return) if raw_return else None)

    # User denied consent
    if error:
        resp = RedirectResponse(f"{base}/login?error=denied")
        _clear_oauth_cookies(resp)
        return resp

    if not code or not state:
        resp = RedirectResponse(f"{base}/login?error=denied")
        _clear_oauth_cookies(resp)
        return resp

    # Validate CSRF state
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or not secrets.compare_digest(stored_state, state):
        resp = RedirectResponse(f"{base}/login?error=denied")
        _clear_oauth_cookies(resp)
        return resp

    # Exchange code for access token
    redirect_uri = f"{settings.PUBLIC_BASE_URL}/api/auth/google/callback"
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()
    except httpx.HTTPStatusError:
        # Code already used or Google rejected the exchange (e.g. duplicate callback)
        resp = RedirectResponse(f"{base}/login?error=denied")
        _clear_oauth_cookies(resp)
        return resp

    google_id = userinfo["id"]
    email = userinfo["email"]
    name = userinfo.get("name")

    # Upsert user (update email/name if returning user)
    result = await session.execute(
        text("""
            INSERT INTO users (google_id, email, name)
            VALUES (:google_id, :email, :name)
            ON CONFLICT (google_id) DO UPDATE
              SET email = EXCLUDED.email, name = EXCLUDED.name
            RETURNING id, is_approved
        """),
        {"google_id": google_id, "email": email, "name": name},
    )
    await session.commit()
    row = result.fetchone()
    user_id, is_approved = row[0], row[1]

    # Always clear the state and return cookies
    if not is_approved:
        response = RedirectResponse(
            f"{base}/login?error=not_approved&email={quote(email)}"
        )
        _clear_oauth_cookies(response)
        return response

    # PLAN-033: record successful, approved login for usage metrics
    await session.execute(
        text("INSERT INTO login_events (user_id) VALUES (:uid)"),
        {"uid": user_id},
    )
    await session.commit()

    token = create_jwt(user_id)
    response = RedirectResponse(base)
    _clear_oauth_cookies(response)
    response.set_cookie("session", token, **_cookie_kwargs(max_age=settings.JWT_EXPIRE_DAYS * 86400))
    return response


@router.get("/auth/me")
async def auth_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return current authenticated user. 401 if not authenticated."""
    await session.execute(
        text("UPDATE users SET last_seen_at = now() WHERE id = :uid"),
        {"uid": user.id},
    )
    await session.commit()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }


@router.post("/auth/logout")
async def auth_logout(_: User = Depends(get_current_user)) -> JSONResponse:
    """Clear session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie("session", **_cookie_kwargs())
    return response
