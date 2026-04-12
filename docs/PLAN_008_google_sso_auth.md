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
- httpOnly session cookie (JWT)
- Login page with error state
- All existing API endpoints become auth-protected
- CORS middleware for VPS deployment
- `.env.example` + docker-compose env wiring

Out of scope: Nginx/SSL config, multi-user management UI.

---

## Breaking Changes

**YES.**

All `/api/*` endpoints go from open to requiring a valid session cookie.
Any existing direct API calls (curl, browser URL) will return 401 after this change.

Recovery: remove `Depends(get_current_user)` from routes and delete the
auth middleware — app is back to open access.

---

## Approval Table

| Approval | Status  | Date |
|----------|---------|------|
| Reviewer | pending | —    |
| Human    | pending | —    |

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

3. **Create `.env` file** in project root (see `.env.example` added in Step 9).

---

## UI Mockup

### Login Page (unauthenticated state)

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

### Login Page (not_approved error state)

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

### Header (authenticated state) — minimal addition to existing header

```
┌────────────────────────────────────────────────────────────┐
│  🛩 RC-Markt Scout    [ScrapeLog ...]    marco@gmail.com ╸ │
│                                               [Abmelden]   │
└────────────────────────────────────────────────────────────┘
```

---

## New Backend Dependencies

Add to `backend/requirements.txt`:
```
python-jose[cryptography]>=3.3.0
```

(`httpx` is already present for scraping — reused for Google userinfo call.)

---

## Steps

### Step 1 — User model (`backend/app/models.py`)

Add `User` class to the existing models file alongside `Listing`:

```python
from sqlalchemy import Boolean, DateTime, func, String
from sqlalchemy.orm import Mapped, mapped_column

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

`metadata.create_all()` in `init_db()` will auto-create the `users` table on startup
(existing pattern — no manual ALTER needed for a new table).

---

### Step 2 — Config (`backend/app/config.py`)

Add fields to `Settings`:

```python
GOOGLE_CLIENT_ID: str = ""
GOOGLE_CLIENT_SECRET: str = ""
JWT_SECRET: str = ""
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_DAYS: int = 30
FRONTEND_URL: str = "http://localhost:4200"
ALLOWED_ORIGINS: list[str] = ["http://localhost:4200"]
COOKIE_SECURE: bool = False  # Set True in production (HTTPS)
```

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `JWT_SECRET` are required in
production. Startup will fail with a clear Pydantic validation error if missing.

---

### Step 3 — Auth router (`backend/app/api/auth.py`)

New file. Four endpoints:

**`GET /api/auth/google`** — Initiate OAuth flow:
- Generate random `state` (16-byte hex), store in short-lived cookie
- Build Google auth URL with scopes `openid email profile`
- Redirect to Google

```python
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

@router.get("/auth/google")
async def auth_google(request: Request):
    state = secrets.token_hex(16)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{request.base_url}api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie("oauth_state", state, httponly=True, max_age=300,
                        samesite="lax", secure=settings.COOKIE_SECURE)
    return response
```

**`GET /api/auth/google/callback`** — Handle OAuth callback:
- Validate `state` cookie
- Exchange `code` for tokens (POST to Google)
- Fetch userinfo (GET to Google with access_token)
- Upsert user in DB (`ON CONFLICT (google_id) DO UPDATE SET email, name`)
- If `is_approved = false` → redirect to `FRONTEND_URL/login?error=not_approved&email=<email>`
- If `is_approved = true` → create JWT, set `session` httpOnly cookie, redirect to `FRONTEND_URL`

```python
@router.get("/auth/google/callback")
async def auth_google_callback(
    code: str, state: str, request: Request, session: AsyncSession = Depends(get_session)
):
    # 1. Validate state
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(400, "Invalid OAuth state")

    # 2. Exchange code for tokens
    redirect_uri = f"{request.base_url}api/auth/google/callback"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        # 3. Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()

    # 4. Upsert user
    google_id = userinfo["id"]
    email = userinfo["email"]
    name = userinfo.get("name")

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

    # 5. Redirect based on approval status
    response = RedirectResponse(settings.FRONTEND_URL)
    response.delete_cookie("oauth_state")

    if not is_approved:
        response = RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=not_approved&email={email}"
        )
        return response

    # 6. Set session cookie
    token = _create_jwt(user_id)
    response.set_cookie(
        "session", token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_DAYS * 86400,
    )
    return response
```

**`GET /api/auth/me`** — Return current user (used by frontend on load):
```python
@router.get("/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "name": user.name}
```

**`POST /api/auth/logout`** — Clear session cookie:
```python
@router.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response
```

**JWT helpers** (private, in `auth.py`):
```python
from jose import jwt, JWTError

def _create_jwt(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def _decode_jwt(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
```

---

### Step 4 — Auth dependency (`backend/app/api/deps.py`)

New file:

```python
from fastapi import Depends, HTTPException, Request
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_session
from app.models import User
from app.api.auth import _decode_jwt

async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = _decode_jwt(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid session")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_approved:
        raise HTTPException(401, "Not authorized")
    return user
```

---

### Step 5 — Protect all existing endpoints (`backend/app/api/routes.py`)

Add `_: User = Depends(get_current_user)` to every endpoint that is not auth-related.
The dependency is named `_` to signal it is used only for the side-effect (auth check).

Example:
```python
from app.api.deps import get_current_user
from app.models import User

@router.get("/listings")
async def list_listings(
    ...,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),  # auth guard
):
```

Endpoints to protect: all routes in `routes.py`.
Endpoints to leave open: `/api/auth/*`, `/health`.

---

### Step 6 — CORS + auth router registration (`backend/app/main.py`)

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
app.include_router(router)  # existing router
```

---

### Step 7 — Frontend: LoginPage (`frontend/src/pages/LoginPage.tsx`)

New file. Shows a centered card with:
- App logo + title
- "Mit Google anmelden" button → links to `/api/auth/google`
- Error banner if `?error=not_approved` in URL (shows email from `?email=` param)
- No state, no hooks — pure UI redirect

```tsx
export default function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get('error')
  const email = params.get('email')

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center">
      <div className="bg-white rounded-card shadow-card p-10 w-full max-w-sm text-center space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">RC-Markt Scout</h1>
          <p className="text-sm text-gray-500 mt-1">Dein persönlicher RC-Flohmarkt-Scout</p>
        </div>

        {error === 'not_approved' && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800 text-left">
            <strong>Kein Zugang.</strong>
            {email && <> Dein Account ({email}) wurde noch nicht freigeschaltet.</>}
          </div>
        )}

        <a
          href="/api/auth/google"
          className="flex items-center justify-center gap-3 w-full border border-gray-300 rounded-lg px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
        >
          <GoogleIcon />
          Mit Google anmelden
        </a>

        <p className="text-xs text-gray-400">
          Zugang nur für freigeschaltete Mitglieder.
        </p>
      </div>
    </div>
  )
}
```

`GoogleIcon` — inline SVG of the Google "G" logo (no external dependency).

---

### Step 8 — Frontend: useAuth hook (`frontend/src/hooks/useAuth.ts`)

New file. Calls `GET /api/auth/me` on mount. Returns `{ user, loading, logout }`.

```ts
type AuthUser = { id: number; email: string; name: string | null }

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(data => { setUser(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setUser(null)
    window.location.href = '/login'
  }

  return { user, loading, logout }
}
```

---

### Step 9 — Frontend: AuthGuard (`frontend/src/components/AuthGuard.tsx`)

New file. Wraps protected routes.

```tsx
export function AuthGuard({ children, logout }: { children: ReactNode; logout: () => void }) {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && !user) navigate('/login', { replace: true })
  }, [user, loading, navigate])

  if (loading) return <div className="min-h-screen bg-surface flex items-center justify-center">
    <span className="text-gray-400 text-sm">Lade…</span>
  </div>

  if (!user) return null

  return <>{children}</>
}
```

Wait — `AuthGuard` wraps layout. The logout function and user email need to reach the
header. Cleanest approach: lift `useAuth()` into `App.tsx`, pass `user` and `logout`
down as props to the layout/header.

---

### Step 10 — Frontend: App.tsx wiring

Changes to `frontend/src/App.tsx`:

1. Call `useAuth()` at app root level
2. Pass `logout` + `user.email` to the header
3. Add `/login` route (no guard)
4. Wrap all other routes in auth check:

```tsx
export default function App() {
  const { user, loading, logout } = useAuth()

  if (loading) return <LoadingScreen />

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            user
              ? <AuthenticatedLayout user={user} logout={logout} />
              : <Navigate to="/login" replace />
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
```

`AuthenticatedLayout` = existing layout (header + main routes) with `user.email` and
`logout` added to the header.

Add logout to header: small `Abmelden` link (text, not a button) aligned right.

---

### Step 11 — docker-compose.yml env wiring

Add to `backend` service `environment`:
```yaml
GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
JWT_SECRET: ${JWT_SECRET}
FRONTEND_URL: ${FRONTEND_URL:-http://localhost:4200}
ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost:4200}
COOKIE_SECURE: ${COOKIE_SECURE:-false}
```

These are read from a `.env` file in the project root (not committed to git).

---

### Step 12 — `.env.example`

New file in project root:

```dotenv
# Google OAuth2 — create at console.cloud.google.com
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret

# JWT — generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=change-me

# Deployment
FRONTEND_URL=http://localhost:4200
ALLOWED_ORIGINS=http://localhost:4200
COOKIE_SECURE=false
```

---

### Step 13 — Bootstrap (first login)

After deploying and logging in for the first time, the account exists but is not
approved. Run once:

```bash
docker compose exec db psql -U rcscout rcscout \
  -c "UPDATE users SET is_approved = true WHERE email = 'your@email.com';"
```

---

## Verification

```bash
# 1. Install new Python dependency
docker compose build backend

# 2. Start services
docker compose up -d

# 3. Confirm backend starts without errors
docker compose logs backend | tail -20

# 4. Run existing test suite (must stay green)
docker compose exec backend pytest tests/ -v

# 5. Unauthenticated request → 401
curl -s http://localhost:8002/api/listings | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail'))"
# Expected: "Not authenticated"

# 6. GET /api/auth/me without cookie → 401
curl -s http://localhost:8002/api/auth/me
# Expected: {"detail":"Not authenticated"}

# 7. Manual flow: visit http://localhost:4200 → redirected to /login
# 8. Click "Mit Google anmelden" → Google OAuth → callback → not_approved error
# 9. Approve own account:
docker compose exec db psql -U rcscout rcscout \
  -c "UPDATE users SET is_approved = true WHERE email = 'your@email.com';"
# 10. Login again → full app access
# 11. Click "Abmelden" → back to /login, cookie cleared
# 12. Verify cookie is httpOnly (DevTools → Application → Cookies → session)
```
