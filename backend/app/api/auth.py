"""Google OAuth2 flow + session management."""
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, text, update
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


@router.get("/auth/google")
async def auth_google(request: Request):
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
    response = RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie(
        "oauth_state", state,
        httponly=True, max_age=300, samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return response


@router.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Handle Google OAuth callback."""
    # User denied consent
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=denied")

    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    # Validate CSRF state
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or not secrets.compare_digest(stored_state, state):
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=denied")

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
        resp = RedirectResponse(f"{settings.FRONTEND_URL}/login?error=denied")
        resp.delete_cookie("oauth_state")
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

    # Always clear the state cookie
    if not is_approved:
        from urllib.parse import quote
        response = RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=not_approved&email={quote(email)}"
        )
        response.delete_cookie("oauth_state")
        return response

    token = create_jwt(user_id)
    response = RedirectResponse(settings.FRONTEND_URL)
    response.delete_cookie("oauth_state")
    response.set_cookie(
        "session", token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_DAYS * 86400,
    )
    return response


@router.get("/auth/me")
async def auth_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return current authenticated user. 401 if not authenticated."""
    await session.execute(
        text("UPDATE users SET last_seen_at = now() WHERE id = :uid"),
        {"uid": user.id},
    )
    await session.commit()
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.post("/auth/logout")
async def auth_logout(_: User = Depends(get_current_user)):
    """Clear session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response
