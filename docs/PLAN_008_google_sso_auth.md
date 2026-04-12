# PLAN_008 — Google SSO Authentication & Deployment Readiness

## Context & Goal

Currently all `/api/*` endpoints are open — no authentication whatsoever. The app
will be deployed on a VPS accessible from the internet. This plan adds Google OAuth2
login with a manual DB approval gate: anyone with a Google account can attempt login,
but only users with `is_approved = true` in the DB get through. The first user
(the owner) approves themselves via a one-time SQL command after first login.

Scope:
- Google OAuth2 flow (backend redirect + callback)
- `users` table with `is_approved` flag
- httpOnly session cookie (JWT via PyJWT)
- Login page with error state
- All existing API endpoints become auth-protected (9 endpoints listed explicitly)
- CORS middleware for VPS deployment
- `.env.example` + docker-compose env wiring
- Existing test suite updated to use dependency override

Out of scope: Nginx/SSL config, multi-user management UI, PWA.

Note: `docs/definition.md` and `docs/architektur.md` currently say "no auth".
Adding auth is a conscious scope expansion — both docs must be updated after this
plan is implemented. This will be announced as a doc-update step per workflow.

---

## Breaking Changes

**YES.**

All 9 `/api/*` business endpoints go from open to requiring a valid session cookie.
Any existing direct API calls (curl, browser URL) will return 401.

Recovery: remove `Depends(get_current_user)` from all 9 routes and delete
`backend/app/api/auth.py`, `deps.py`, `security.py` — app is back to open access.

---

## Approval Table

| Approval | Status   | Date       |
|----------|----------|------------|
| Reviewer | approved | 2026-04-11 |
| Human    | approved | 2026-04-12 |

---

## Reviewer Notes (incorporated into plan)

Issues fixed in this revision:
1. Circular import → JWT helpers extracted to `backend/app/security.py`
2. `BrowserRouter` not added in `App.tsx` (already in `main.tsx`)
3. Existing tests → `conftest.py` gets `get_current_user` dependency override
4. Empty-string JWT secret no longer has a default — `@field_validator` rejects empty
5. `redirect_uri` uses explicit `PUBLIC_BASE_URL` config, not `request.base_url`
6. All 9 protected endpoints listed explicitly in Step 5
7. Clarified: only `/auth/google` and `/auth/google/callback` are open; `/auth/me` is protected
8. `ALLOWED_ORIGINS` uses comma-split `@field_validator` for env-var compatibility
9. Structural elements added: step status, BREAK marker, test file specified
10. `oauth_state` cookie deleted on `not_approved` branch
11. `secrets.compare_digest` for state comparison
12. Google consent-denial (`?error=access_denied`) handled in callback
13. `AuthGuard` component removed — auth check is inline in `App.tsx`
14. Bootstrap step moved to Post-Deployment section
15. `python-jose` replaced with `PyJWT` (actively maintained)

---

## Prerequisites (Human action required before implementation)

1. **Google Cloud Console** — create an OAuth2 app:
   - Go to console.cloud.google.com → APIs & Services → Credentials
   - Create OAuth 2.0 Client ID (Web application)
   - Add Authorized redirect URIs:
     - `http://localhost:8002/api/auth/google/callback` (dev)
     - `https://<yourdomain>/api/auth/google/callback` (prod)
   - Copy `Client ID` and `Client Secret`

2. **Generate a JWT secret** (random 32-byte hex):
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Create `.env` file** in project root before starting (see `.env.example` from Step 10).

---

## UI Mockup

### Login Page — default state

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│                  🛩  RC-Markt Scout                  │
│                                                      │
│          Dein persönlicher RC-Flohmarkt-Scout        │
│                                                      │
│      ┌────────────────────────────────────────┐      │
│      │  G  Mit Google anmelden               │      │
│      └────────────────────────────────────────┘      │
│                                                      │
│      Zugang nur für freigeschaltete Mitglieder.      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Login Page — not_approved error state

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│                  🛩  RC-Markt Scout                  │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  ⚠  Kein Zugang                             │   │
│  │  Dein Account (user@email.com) wurde noch   │   │
│  │  nicht freigeschaltet.                      │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│      ┌────────────────────────────────────────┐      │
│      │  G  Mit anderem Account anmelden      │      │
│      └────────────────────────────────────────┘      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Header — authenticated state

```
┌────────────────────────────────────────────────────────────┐
│  🛩 RC-Markt Scout    [ScrapeLog ...]    marco@gmail.com   │
│                                              [Abmelden]    │
└────────────────────────────────────────────────────────────┘
```

---

## New Dependencies

Backend (`backend/requirements.txt`):
```
PyJWT>=2.8.0
```

Frontend: none.

---

## Test File

`backend/tests/conftest.py` — add `get_current_user` dependency override so all
existing tests pass without a real session cookie.

`backend/tests/test_api.py` — no changes to test logic; auth is bypassed via override.

---

## Steps

---

### Step 1 — User model [ open ]

**File:** `backend/app/models.py`

Add `User` class alongside the existing `Listing` model:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    google_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    is_approved: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

`metadata.create_all()` already runs in `init_db()` — the new table is created
automatically on next startup. No manual migration needed.

---

### Step 2 — Config [ open ]

**File:** `backend/app/config.py`

Add fields to `Settings`. Required secrets have no default so Pydantic raises a clear
error on startup if they are missing from the environment:

```python
from pydantic import field_validator

# Required — no default (startup fails with clear error if missing)
GOOGLE_CLIENT_ID: str
GOOGLE_CLIENT_SECRET: str
JWT_SECRET: str

# Optional with sensible defaults
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_DAYS: int = 30
PUBLIC_BASE_URL: str = "http://localhost:8002"   # used for OAuth redirect_uri
FRONTEND_URL: str = "http://localhost:4200"
ALLOWED_ORIGINS: list[str] = ["http://localhost:4200"]
COOKIE_SECURE: bool = False  # set True in production (HTTPS)

@field_validator("JWT_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
@classmethod
def must_not_be_empty(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("must not be empty")
    return v

@field_validator("ALLOWED_ORIGINS", mode="before")
@classmethod
def parse_origins(cls, v):
    # Env var arrives as a plain string: "http://a.com,http://b.com"
    if isinstance(v, str):
        return [o.strip() for o in v.split(",") if o.strip()]
    return v
```

---

### Step 3 — JWT helpers (`backend/app/security.py`) [ open ]

New file. Extracted here to avoid circular imports between `auth.py` and `deps.py`.

```python
"""JWT creation and decoding using PyJWT."""
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_jwt(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired token."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
```

---

### Step 4 — Auth dependency (`backend/app/api/deps.py`) [ open ]

New file:

```python
"""FastAPI dependencies for authentication."""
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import decode_jwt


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_jwt(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid session")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_approved:
        raise HTTPException(status_code=401, detail="Not authorized")
    return user
```

---

### Step 5 — Protect all existing endpoints [ open ]

**File:** `backend/app/api/routes.py`

Add `_: User = Depends(get_current_user)` to all 9 business endpoints. List:

| Endpoint | Method |
|----------|--------|
| `/api/scrape` | POST |
| `/api/scrape/status` | GET |
| `/api/scrape/log` | GET |
| `/api/geo/plz/{plz}` | GET |
| `/api/listings` | GET |
| `/api/listings/{listing_id}` | GET |
| `/api/listings/{listing_id}/sold` | PATCH |
| `/api/listings/{listing_id}/favorite` | PATCH |
| `/api/favorites` | GET |

Pattern (same for every endpoint):
```python
from app.api.deps import get_current_user
from app.models import User

@router.get("/listings")
async def list_listings(
    ...,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
```

**Open endpoints (no auth required):**
- `GET /api/auth/google` — initiates OAuth, must be open
- `GET /api/auth/google/callback` — Google redirects here, must be open
- `GET /health` — health check

**Protected auth endpoint:**
- `GET /api/auth/me` — requires valid session (protected via its own `Depends`)
- `POST /api/auth/logout` — requires valid session

---

### Step 6 — Auth router (`backend/app/api/auth.py`) [ open ]

New file. Four endpoints.

```python
"""Google OAuth2 flow + session management."""
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
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
        raise HTTPException(400, "Invalid OAuth state")

    # Exchange code for access token
    redirect_uri = f"{settings.PUBLIC_BASE_URL}/api/auth/google/callback"
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
async def auth_me(user: User = Depends(get_current_user)):
    """Return current authenticated user. 401 if not authenticated."""
    return {"id": user.id, "email": user.email, "name": user.name}


@router.post("/auth/logout")
async def auth_logout(_: User = Depends(get_current_user)):
    """Clear session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response
```

---

### Step 7 — CORS + router registration (`backend/app/main.py`) [ open ]

```python
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(router)  # existing business router — unchanged
```

--- BREAK ---
At this point the backend is fully secured. Before continuing with the frontend:
1. Rebuild and start: `docker compose up --build -d`
2. Confirm `curl http://localhost:8002/api/listings` returns `{"detail":"Not authenticated"}`
3. Confirm `/health` still returns `{"status":"ok"}`
4. Run `docker compose exec backend pytest tests/ -v` — must be green (see Step 8)

Wait for Human confirmation before proceeding to frontend steps.

---

### Step 8 — Test suite: auth dependency override (`backend/tests/conftest.py`) [ open ]

All existing tests make unauthenticated requests and expect 200/404. After Step 5
they would all get 401. Fix: override `get_current_user` with a stub in the test
app so no real session cookie is needed.

Add to `backend/tests/conftest.py`:

```python
from app.api.deps import get_current_user
from app.models import User

def _fake_user() -> User:
    return User(id=1, google_id="test-google-id", email="test@example.com",
                name="Test User", is_approved=True)

# Applied once for the whole test session
@pytest.fixture(autouse=True, scope="session")
def override_auth(app):
    app.dependency_overrides[get_current_user] = _fake_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
```

`app` here refers to the FastAPI application instance imported in `conftest.py`.
Check the existing `conftest.py` for how `app` and the `AsyncClient` are set up —
the override must be applied to the same instance used by the test client.

Also add `users` to the `clean_listings` autouse fixture's truncation list:
```python
await session.execute(text("TRUNCATE TABLE listings, users RESTART IDENTITY CASCADE"))
```

---

### Step 9 — Frontend: LoginPage (`frontend/src/pages/LoginPage.tsx`) [ open ]

New file. **Aurora Dark** style — dark background with animated aurora gradient
blobs, translucent glassmorphic card.

Visual reference: `docs/mockup_login.html` → "Aurora Dark" tab.

```tsx
import { useSearchParams } from 'react-router-dom'

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.97 10.97 0 001 12c0 1.78.43 3.46 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  )
}

export default function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get('error')
  const email = params.get('email')

  return (
    <div className="relative min-h-screen flex items-center justify-center px-4 overflow-hidden"
         style={{ background: '#0f0f23' }}>

      {/* Aurora gradient blobs */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[10%] w-[60%] h-[60%] rounded-full opacity-25 blur-[80px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.5), transparent 70%)' }} />
        <div className="absolute bottom-[-10%] right-[10%] w-[50%] h-[50%] rounded-full opacity-20 blur-[80px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(236,72,153,0.4), transparent 70%)', animationDelay: '2s' }} />
        <div className="absolute top-[30%] right-[30%] w-[40%] h-[40%] rounded-full opacity-[0.15] blur-[60px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(45,212,191,0.3), transparent 70%)', animationDelay: '4s' }} />
      </div>

      {/* Card */}
      <div className="relative w-full max-w-[420px] rounded-3xl p-12 text-center space-y-7 border"
           style={{
             background: 'rgba(15, 15, 35, 0.6)',
             backdropFilter: 'blur(24px) saturate(1.2)',
             WebkitBackdropFilter: 'blur(24px) saturate(1.2)',
             borderColor: 'rgba(255,255,255,0.08)',
             boxShadow: '0 0 60px rgba(99,102,241,0.08), 0 8px 32px rgba(0,0,0,0.3)',
           }}>

        {/* Icon */}
        <div className="inline-flex items-center justify-center w-[60px] h-[60px] rounded-2xl border"
             style={{
               background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(236,72,153,0.3))',
               borderColor: 'rgba(255,255,255,0.1)',
             }}>
          <svg className="w-7 h-7" style={{ color: '#A78BFA' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M5 3l14 9-14 9V3z" />
          </svg>
        </div>

        <div>
          <h1 className="text-[28px] font-bold tracking-tight" style={{ color: '#F8FAFC' }}>
            RC-Markt Scout
          </h1>
          <p className="text-sm mt-1.5" style={{ color: 'rgba(248,250,252,0.5)' }}>
            Dein persönlicher RC-Flohmarkt-Scout
          </p>
        </div>

        {error === 'not_approved' && (
          <div className="rounded-xl p-4 text-sm text-left border"
               style={{
                 background: 'rgba(251,191,36,0.08)',
                 borderColor: 'rgba(251,191,36,0.2)',
                 color: '#FDE68A',
               }}>
            <strong>Kein Zugang.</strong>
            {email && <> Dein Account ({email}) wurde noch nicht freigeschaltet.</>}
          </div>
        )}

        {error === 'denied' && (
          <div className="rounded-xl p-4 text-sm text-left border"
               style={{
                 background: 'rgba(239,68,68,0.08)',
                 borderColor: 'rgba(239,68,68,0.2)',
                 color: '#FCA5A5',
               }}>
            <strong>Anmeldung abgebrochen.</strong> Die Google-Anmeldung wurde abgebrochen oder abgelehnt.
          </div>
        )}

        <a href="/api/auth/google"
           className="flex items-center justify-center gap-3 w-full rounded-xl px-4 py-3.5 text-sm font-semibold no-underline border transition-all duration-200"
           style={{
             background: 'rgba(255,255,255,0.08)',
             borderColor: 'rgba(255,255,255,0.12)',
             color: '#E2E8F0',
           }}
           onMouseOver={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.14)'; e.currentTarget.style.boxShadow = '0 0 20px rgba(99,102,241,0.15)'; }}
           onMouseOut={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.boxShadow = 'none'; }}
        >
          <GoogleIcon />
          {error === 'not_approved' ? 'Mit anderem Account anmelden' : 'Mit Google anmelden'}
        </a>

        <div className="flex items-center gap-3">
          <span className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />
          <svg className="w-4 h-4" style={{ color: 'rgba(255,255,255,0.15)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <span className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />
        </div>

        <p className="text-xs" style={{ color: 'rgba(248,250,252,0.3)' }}>
          Zugang nur für freigeschaltete Mitglieder.
        </p>
      </div>
    </div>
  )
}
```

Note: The login page uses Aurora Dark style as a standalone screen. The rest of
the app remains in the current light theme until PLAN_009 (Aurora Dark Redesign)
is implemented.

---

### Step 10 — Frontend: useAuth hook (`frontend/src/hooks/useAuth.ts`) [ open ]

New file:

```ts
import { useState, useEffect } from 'react'

export type AuthUser = { id: number; email: string; name: string | null }

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        setUser(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' })
    setUser(null)
    window.location.href = '/login'
  }

  return { user, loading, logout }
}
```

Note: `credentials: 'include'` is not needed — frontend and backend share the same
origin via the Vite proxy (dev) and nginx (prod). Cookies are sent automatically for
same-origin requests.

---

### Step 11 — Frontend: App.tsx wiring [ open ]

**File:** `frontend/src/App.tsx`

Do NOT add a new `<BrowserRouter>` — it is already provided in `main.tsx`.

Changes:
1. Call `useAuth()` at the top of `App`
2. Show a loading screen while `GET /api/auth/me` is in flight
3. Redirect unauthenticated users to `/login`
4. Add `/login` route
5. Pass `user` and `logout` to the existing header

```tsx
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import LoginPage from './pages/LoginPage'
// ... existing imports

export default function App() {
  const { user, loading, logout } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <span className="text-gray-400 text-sm">Lade…</span>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          user ? (
            // Existing layout — pass user/logout into header
            <AuthenticatedApp user={user} logout={logout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  )
}
```

Extract existing layout (header + main routes) into `AuthenticatedApp` sub-component
within `App.tsx`. Header receives `user.email` and `logout`:

```tsx
function AuthenticatedApp({ user, logout }: { user: AuthUser; logout: () => void }) {
  // Preserve ALL existing state and components from the current App component.
  // This includes: favoritesOpen state, PlzBar, FavoritesModal, ScrapeLog, etc.
  // Move them here verbatim from the current App() — only add user/logout to header.
  const [favoritesOpen, setFavoritesOpen] = useState(false)
  // ... any other existing state from current App.tsx

  return (
    <>
      {/* Existing sticky header — add email + logout link on the right */}
      <header className="...existing classes...">
        {/* existing header content (logo, ScrapeLog, etc.) */}
        <div className="flex items-center gap-3 text-sm text-gray-500">
          <span>{user.email}</span>
          <button onClick={logout} className="text-brand hover:underline">
            Abmelden
          </button>
        </div>
      </header>
      <PlzBar onOpenFavorites={() => setFavoritesOpen(true)} />
      {/* Existing main content / routes */}
      <Routes>
        <Route path="/" element={<ListingsPage />} />
        <Route path="/listings/:id" element={<DetailPage />} />
      </Routes>
      <FavoritesModal open={favoritesOpen} onClose={() => setFavoritesOpen(false)} />
    </>
  )
}
```

**Important:** The implementer must move ALL existing children and state from the
current `App()` component into `AuthenticatedApp`. The snippet above shows the
pattern — do not drop `PlzBar`, `FavoritesModal`, or any other existing UI.

---

### Step 12 — Environment wiring [ open ]

**File:** `docker-compose.yml` — add to `backend.environment`:

```yaml
GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
JWT_SECRET: ${JWT_SECRET}
PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8002}
FRONTEND_URL: ${FRONTEND_URL:-http://localhost:4200}
ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost:4200}
COOKIE_SECURE: ${COOKIE_SECURE:-false}
```

**New file:** `.env.example` in project root:

```dotenv
# Google OAuth2 — create at console.cloud.google.com
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret

# JWT — generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=change-me

# URLs — adjust for your VPS domain in production
PUBLIC_BASE_URL=http://localhost:8002
FRONTEND_URL=http://localhost:4200
ALLOWED_ORIGINS=http://localhost:4200
COOKIE_SECURE=false
```

---

## Verification

```bash
# 1. Rebuild backend (new dependency: PyJWT)
docker compose build backend

# 2. Start all services
docker compose up -d

# 3. Confirm backend starts (check for startup errors)
docker compose logs backend --tail=30

# 4. Full test suite — must be 100% green
docker compose exec backend pytest tests/ -v

# 5. Unauthenticated request to business endpoint → 401
curl -s http://localhost:8002/api/listings | python3 -c "import sys,json; print(json.load(sys.stdin)['detail'])"
# Expected: "Not authenticated"

# 6. Health check still open
curl -s http://localhost:8002/health
# Expected: {"status":"ok"}

# 7. Auth initiation endpoint still open
curl -sI http://localhost:8002/api/auth/google | head -1
# Expected: HTTP/1.1 307 Temporary Redirect  (redirect to Google)

# 8. /auth/me without cookie → 401
curl -s http://localhost:8002/api/auth/me
# Expected: {"detail":"Not authenticated"}

# 9. Frontend: visit http://localhost:4200 → redirected to /login
# 10. Click "Mit Google anmelden" → Google consent → callback → not_approved screen
# 11. Verify cookie is httpOnly (DevTools → Application → Cookies → "session")
```

---

## Post-Deployment (Human action — after first login)

After deploying and logging in for the first time, the account exists but is blocked.
Run this **once** to approve yourself:

```bash
docker compose exec db psql -U rcscout rcscout \
  -c "UPDATE users SET is_approved = true WHERE email = 'your@email.com';"
```

Then log in again — full access granted.
