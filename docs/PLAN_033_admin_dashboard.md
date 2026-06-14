# Admin Dashboard — Metrics, Account Management & DSGVO Delete — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Extend the existing admin area with a metrics dashboard (snapshot KPIs + time-series graphs), full account management including a DSGVO-compliant hard-delete, and fix the stale "single-user / no-auth" docs.

**Architecture:** Backend adds one telemetry table (`login_events`), a FK-cascade fix on `saved_searches`, and three admin endpoints (metrics summary, metrics timeseries, user hard-delete) following the existing raw-SQL + `require_admin` pattern. Frontend adds a self-contained SVG chart component (no charting dependency), KPI tiles, and a range selector on the `/admin` dashboard; account management (approve + DSGVO hard-delete) moves to its own route `/admin/users`, linked from the dashboard. All mirror the existing glassmorphism panels. Auth stays Google-SSO; 2FA is enforced at the Google-account level (no app-side TOTP).

**Tech Stack:** FastAPI + async SQLAlchemy (raw SQL via `AsyncSessionLocal`), PostgreSQL (idempotent DDL in `db.init_db()`, no Alembic), React 19 + TypeScript + Tailwind, Vitest.

**Breaking Changes:** No API breaks. One DB change: `saved_searches.user_id` FK gains `ON DELETE CASCADE` (additive, enables user deletion). Hard-delete of a user is irreversible by design (DSGVO) — guarded against self-deletion and behind a confirm dialog.

**Open decision for Human approval (no BREAK):**
- **Charts** are implemented as lightweight in-house SVG (line/bar), **no new dependency**. Rationale: minimal frontend footprint (only react/router/workbox today), avoids React-19 peer-dep friction, fits "keep it simple". If the Human prefers `recharts` (tooltips/interactivity out of the box) this flips Task 5 to a dependency add (needs package approval, Hard Rule 9). Default = in-house SVG.
- **"Number of searches" metric** is interpreted as **executed search requests** is **OUT of scope** for this plan (would need request logging in `routes.py`). Only the gratis timestamp-derived series + logins are included. Confirm at approval or it ships without a search-request graph.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-06-14 (cycles 1+2) |
| Human | approved | 2026-06-14 |

---

## Context (verified facts — do not re-derive)

**Backend**
- Migrations: NO Alembic. Idempotent DDL blocks in `backend/app/db.py` → `async def init_db()` (runs every startup). Pattern: `await conn.execute(text("CREATE TABLE IF NOT EXISTS ..."))` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`. One statement per `execute()`. Example table block: `db.py:130-137` (`user_favorites`).
- Router mount: `backend/app/main.py:209-211`; business router `backend/app/api/routes.py:28` (`APIRouter(prefix="/api")`) mounts `admin_router` (`routes.py:29`). Admin prefix `/admin` (`admin.py:14`). Net: **`/api/admin/*`**.
- DB access: `AsyncSessionLocal` (`db.py:11-15`), `get_session` (`db.py:292`). Canonical usage: `async with AsyncSessionLocal() as session: await session.execute(text(...))` — see `admin.py:102`.
- Admin guard: `require_admin` (`backend/app/api/deps.py:32`).
- JWT: `create_jwt(user_id:int)->str` (`security.py:9`), `decode_jwt(token:str)->dict` (`security.py:17`).
- OAuth callback: `backend/app/api/auth.py:45-130`; success path: upsert+commit (l.97-107), approval gate (l.112-119), then `create_jwt` (l.120). **Login-event insert point: after l.119, before l.120.** `session` (AsyncSession) is in scope.
- FK to `users.id`: `saved_searches.user_id` → **NO cascade** (`models.py:101`); `user_favorites.user_id` (`models.py:149`) and `push_subscriptions.user_id` (`models.py:164`) → already `ON DELETE CASCADE`. `search_notifications` cascades via `saved_search_id` (`models.py:131`).
- Admin tests fixture: `admin_client` (`backend/tests/conftest.py:331-371`) yields `(client, admin_id)`, overrides `get_session` + `get_current_user`, seeds an admin user. Member fixture: `authenticated_client` (`conftest.py:375-417`). Canonical test: `backend/tests/test_admin_users.py:23-28`.

**Frontend**
- No chart lib installed (`frontend/package.json` deps: react, react-dom, react-router-dom, workbox-*). 
- API client: `frontend/src/api/client.ts`; pattern = `fetch('/api/...')` + `handleResponse<T>(res)` (`client.ts:19-30`), e.g. `getLLMModels` (`client.ts:151-155`), `setUserApproval` (`client.ts:167-174`). Same-site cookie auth (no explicit credentials).
- Types: `frontend/src/types/api.ts`; `UserRow` (`api.ts:210-218`), `ApiError` (`api.ts:143-150`). Co-located `export interface`.
- Panel convention (mirror reference): `frontend/src/components/UserApprovalPanel.tsx` — module-level `cardStyle` (l.8-14), fetch+loading+error pattern (l.30-45), `<section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>` shell (l.71+), `useConfirm` for destructive actions (l.52-58), optimistic update + rollback (l.60-68).
- Routing: `/admin` route in `frontend/src/App.tsx:166-186` (`<Route path="/admin" element={<AdminPage user={user} />} />`), guard `user.role !== 'admin'` → `<Navigate to="/" />` (`AdminPage.tsx:11-13`).
- Auth hook: `frontend/src/hooks/useAuth.ts`; `AuthUser = { id; email; name: string|null; role: 'member'|'admin' }`.
- Frontend tests (mirror reference): `frontend/src/components/__tests__/UserApprovalPanel.test.tsx` — explicit imports `import { describe, it, expect, vi, beforeEach } from 'vitest'` (globals NOT used), `vi.mock('../../api/client', ...)`, `vi.mock('../ConfirmDialog', ...)`, render under provider. **All new component tests mirror this.**
- Util: `formatDate(iso: string|null): string` (`frontend/src/utils/format.ts:17`) → `'–'` on null, German locale.

**Docs (stale — to fix in Task 8)**
- `docs/definition.md:3-4` and `docs/architektur.md:4-5` claim "single user, no auth, no multi-tenancy" — contradicted by the live Google-SSO multi-user + role-based admin code. `architektur.md:103-105` "No auth required — read-only public interface" likewise false.

---

## Task 1: Backend schema — login_events table + saved_searches FK cascade + login telemetry [IMPLEMENTED]

**Files:**
- Modify: `backend/app/db.py` (append two idempotent DDL blocks at the end of `init_db()`, after the last existing block ~`db.py:289`)
- Modify: `backend/app/models.py:101` (add `ondelete="CASCADE"` to keep ORM in sync with DB) + add `LoginEvent` model
- Modify: `backend/app/api/auth.py` (insert login-event row after approval gate, ~l.119)
- Test: `backend/tests/test_login_telemetry.py` (create)

**Step 1: Add `login_events` table + FK cascade DDL in `db.py`**

Append inside `init_db()`, after the last existing `await conn.execute(...)` block:

```python
        # PLAN-033: login telemetry (one row per successful, approved login)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS login_events (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                logged_in_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_login_events_logged_in_at "
            "ON login_events (logged_in_at)"
        ))
        # PostgreSQL does NOT auto-index FK columns. Needed for the per-user
        # stats COUNT (Task 8) and to keep the ON DELETE CASCADE delete fast.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_login_events_user_id "
            "ON login_events (user_id)"
        ))

        # PLAN-033: make saved_searches.user_id cascade on user delete (DSGVO hard-delete).
        # Do NOT assume the auto-generated constraint name — discover and drop whatever
        # FK currently sits on saved_searches.user_id, then re-add with ON DELETE CASCADE.
        # Idempotent: re-running drops the cascade FK we just added and recreates it.
        await conn.execute(text("""
            DO $$
            DECLARE cname text;
            BEGIN
                SELECT con.conname INTO cname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
                WHERE rel.relname = 'saved_searches'
                  AND con.contype = 'f'
                  AND att.attname = 'user_id';
                IF cname IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE saved_searches DROP CONSTRAINT %I', cname);
                END IF;
            END $$;
        """))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD CONSTRAINT saved_searches_user_id_fkey "
            "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
        ))
```

**Step 2: Sync ORM model in `models.py`**

Change line 101:

```python
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
```

Append a `LoginEvent` model after the `User` class (keeps ORM complete; endpoints use raw SQL):

```python
class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    logged_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

**Step 3: Record login in OAuth callback (`auth.py`)**

Insert directly after the approval gate (after the `if not is_approved:` block returns, before `token = create_jwt(user_id)`):

```python
    # PLAN-033: record successful, approved login for usage metrics
    await session.execute(
        text("INSERT INTO login_events (user_id) VALUES (:uid)"),
        {"uid": user_id},
    )
    await session.commit()
```

**Step 4: Write tests** (`backend/tests/test_login_telemetry.py`)

Mirror the async + raw-SQL fixture style of `test_admin_users.py`. Use `db_session` to assert rows.

```python
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_login_events_table_exists_and_cascades(db_session):
    # login_events row is removed when its user is deleted (ON DELETE CASCADE)
    await db_session.execute(text(
        "INSERT INTO users (google_id, email, name, is_approved, role) "
        "VALUES ('le-g', 'le@example.com', 'LE', TRUE, 'member')"
    ))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'le-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO login_events (user_id) VALUES (:u)"), {"u": uid}
    )
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM login_events WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 1

    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM login_events WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0


@pytest.mark.asyncio
async def test_saved_searches_cascade_on_user_delete(db_session):
    # deleting a user removes their saved_searches (FK cascade fix)
    await db_session.execute(text(
        "INSERT INTO users (google_id, email, name, is_approved, role) "
        "VALUES ('ss-g', 'ss@example.com', 'SS', TRUE, 'member')"
    ))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'ss-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'x')"), {"u": uid}
    )
    await db_session.commit()
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM saved_searches WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0
```

**Step 5: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/app/api/auth.py backend/tests/test_login_telemetry.py
git commit -m "feat(admin): login telemetry table + saved_searches FK cascade"
```

---

## Task 2: Backend metrics endpoints — summary + timeseries [IMPLEMENTED]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/api/admin.py` (add two GET endpoints + Pydantic models, mirroring existing admin handlers)
- Test: `backend/tests/test_admin_metrics.py` (create)

**Reuse check:** Mirrors the `require_admin` + `AsyncSessionLocal()` + Pydantic-response shape already in `admin.py:99-120` (`list_users`). No new convention.

**Step 1: Add response models + endpoints in `admin.py`**

```python
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
    day: str   # ISO date (YYYY-MM-DD)
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
```

Add `from datetime import timedelta` to the existing `datetime` import line at the top of `admin.py`.

**Step 2: Write tests** (`backend/tests/test_admin_metrics.py`)

```python
import pytest


@pytest.mark.asyncio
async def test_metrics_summary_counts(admin_client, db_session):
    client, _ = admin_client
    resp = await client.get("/api/admin/metrics/summary")
    assert resp.status_code == 200
    body = resp.json()
    # admin_client seeds exactly one approved admin user
    assert body["users_total"] >= 1
    assert body["users_approved"] >= 1
    assert set(body) >= {"users_pending", "users_active_7d", "listings_total",
                         "favorites_total", "saved_searches_total"}


@pytest.mark.asyncio
async def test_metrics_timeseries_zero_filled_and_clamped(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/metrics/timeseries?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["logins"]) == 7          # zero-filled continuous window
    assert len(body["listings_new"]) == 7


@pytest.mark.asyncio
async def test_metrics_requires_admin(authenticated_client):
    client = authenticated_client          # role=member
    resp = await client.get("/api/admin/metrics/summary")
    assert resp.status_code == 403
```

> Coder note: confirm the `authenticated_client` fixture's return shape (client vs tuple) against `conftest.py:375-417` before writing the member-403 test; adapt the unpacking to match.

**Step 3: Commit**

```bash
git add backend/app/api/admin.py backend/tests/test_admin_metrics.py
git commit -m "feat(admin): metrics summary + timeseries endpoints"
```

---

## Task 3: Backend user hard-delete (DSGVO) [IMPLEMENTED]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/api/admin.py` (add `DELETE /admin/users/{user_id}`)
- Test: `backend/tests/test_admin_users.py` (append tests)

**Reuse check:** Mirrors `set_user_approval` (`admin.py:123-160`) — same `require_admin`, `current_admin` self-guard, `AsyncSessionLocal()` raw SQL.

**Step 1: Add endpoint in `admin.py`**

```python
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
```

**Step 2: Append tests** (`backend/tests/test_admin_users.py`)

```python
@pytest.mark.asyncio
async def test_delete_user_hard_deletes_and_cascades(admin_client, db_session):
    client, _admin_id = admin_client
    await _seed_user(db_session, "del-g", "del@example.com", is_approved=True)
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'del-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'x')"), {"u": uid}
    )
    await db_session.commit()

    resp = await client.delete(f"/api/admin/users/{uid}")
    assert resp.status_code == 204
    assert (await db_session.execute(
        text("SELECT count(*) FROM users WHERE id = :u"), {"u": uid}
    )).scalar_one() == 0
    assert (await db_session.execute(
        text("SELECT count(*) FROM saved_searches WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0


@pytest.mark.asyncio
async def test_delete_self_is_blocked(admin_client):
    client, admin_id = admin_client
    resp = await client.delete(f"/api/admin/users/{admin_id}")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_missing_user_404(admin_client):
    client, _ = admin_client
    resp = await client.delete("/api/admin/users/999999")
    assert resp.status_code == 404
```

> Coder note: reuse the existing `_seed_user(...)` helper already present in `test_admin_users.py`; match its exact signature. Ensure `from sqlalchemy import text` is imported in the test module.

**Step 3: Commit**

```bash
git add backend/app/api/admin.py backend/tests/test_admin_users.py
git commit -m "feat(admin): DSGVO hard-delete user endpoint"
```

---

## Task 4: Frontend API client + types [ ]

**Depends on:** Task 2, Task 3

**Files:**
- Modify: `frontend/src/types/api.ts` (add metrics types)
- Modify: `frontend/src/api/client.ts` (add 3 functions)

**Reuse check:** Mirrors `getLLMModels` (`client.ts:151-155`) and `setUserApproval` (`client.ts:167-174`). Identical shape; deviations: new URLs/methods only.

**Step 1: Add types (`types/api.ts`)**

```typescript
export interface MetricsSummary {
  users_total: number;
  users_approved: number;
  users_pending: number;
  users_active_7d: number;
  users_active_30d: number;
  listings_total: number;
  favorites_total: number;
  saved_searches_total: number;
}

export interface TimeseriesPoint {
  day: string;   // YYYY-MM-DD
  value: number;
}

export interface MetricsTimeseries {
  days: number;
  listings_new: TimeseriesPoint[];
  listings_closed: TimeseriesPoint[];
  users_new: TimeseriesPoint[];
  logins: TimeseriesPoint[];
  notifications: TimeseriesPoint[];
}
```

**Step 2: Add client functions (`client.ts`)**

```typescript
export async function getMetricsSummary(): Promise<MetricsSummary> {
  const res = await fetch('/api/admin/metrics/summary');
  return handleResponse<MetricsSummary>(res);
}

export async function getMetricsTimeseries(days: number): Promise<MetricsTimeseries> {
  const res = await fetch(`/api/admin/metrics/timeseries?days=${days}`);
  return handleResponse<MetricsTimeseries>(res);
}

export async function deleteUser(userId: number): Promise<void> {
  const res = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
  if (!res.ok) {
    // mirror handleResponse error extraction without expecting a JSON body (204)
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }
}
```

> Add the new type names to the existing import from `../types/api` at the top of `client.ts`, and confirm `ApiError` is imported there.

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat(admin): metrics + delete API client functions"
```

---

## Task 5: Frontend SVG chart component (no dependency) [ ]

**Depends on:** Task 4

**Files:**
- Create: `frontend/src/components/MiniChart.tsx`
- Test: `frontend/src/components/__tests__/MiniChart.test.tsx`

**Reuse check:** No existing chart pattern (grep confirmed). New component, designed extractable; line + bar in one component.

**Design (synthesized from ui-ux-pro-max rules §10):** subtle gridlines (`stroke rgba(255,255,255,0.06)`), data ≥3:1 contrast (accent color per series), `role="img"` + `aria-label` summary (chart-not-only / screen-reader-summary), per-point `<title>` for exact values (tooltip-on-interact), tabular date labels first/mid/last only on mobile (axis-readability), empty-data state (no blank axis frame), responsive via `viewBox` + `width:100%`, `preserveAspectRatio="none"` on the plot area only.

**Step 1: Implement `MiniChart.tsx`**

```tsx
import type { TimeseriesPoint } from '../types/api';

interface Props {
  title: string;
  data: TimeseriesPoint[];
  type: 'line' | 'bar';
  accent: string;       // e.g. '#A78BFA'
  height?: number;      // px, default 96
}

const W = 320;          // viewBox width (scales to container)
const PAD = 4;

function fmtDay(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${d}.${m}`;
}

export function MiniChart({ title, data, type, accent, height = 96 }: Props) {
  const total = data.reduce((s, p) => s + p.value, 0);
  const max = Math.max(1, ...data.map((p) => p.value));
  const H = height;
  const innerH = H - PAD * 2;
  const stepX = data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0;
  const x = (i: number) => PAD + i * stepX;
  const y = (v: number) => PAD + innerH * (1 - v / max);

  const empty = total === 0;
  const label = `${title}: ${total} insgesamt über ${data.length} Tage`;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <p className="text-xs font-semibold" style={{ color: accent }}>{title}</p>
        <p className="text-xs tabular-nums" style={{ color: 'rgba(248,250,252,0.55)' }}>{total}</p>
      </div>

      {empty ? (
        <div className="flex items-center justify-center text-[11px]"
             style={{ height: H, color: 'rgba(248,250,252,0.3)' }}>
          Keine Daten im Zeitraum
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
             aria-label={label} preserveAspectRatio="none">
          {/* baseline + one mid gridline */}
          {[0.5, 1].map((g) => (
            <line key={g} x1={PAD} x2={W - PAD} y1={PAD + innerH * g} y2={PAD + innerH * g}
                  stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
          ))}

          {type === 'line' ? (
            <>
              <polyline fill="none" stroke={accent} strokeWidth={2}
                        strokeLinejoin="round" strokeLinecap="round"
                        points={data.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')} />
              {data.map((p, i) => (
                <circle key={i} cx={x(i)} cy={y(p.value)} r={2} fill={accent}>
                  <title>{`${fmtDay(p.day)}: ${p.value}`}</title>
                </circle>
              ))}
            </>
          ) : (
            data.map((p, i) => {
              const bw = Math.max(1, stepX * 0.6);
              const bh = innerH * (p.value / max);
              return (
                <rect key={i} x={x(i) - bw / 2} y={PAD + innerH - bh} width={bw} height={bh}
                      rx={1} fill={accent} opacity={0.85}>
                  <title>{`${fmtDay(p.day)}: ${p.value}`}</title>
                </rect>
              );
            })
          )}
        </svg>
      )}

      {!empty && (
        <div className="flex justify-between mt-1 text-[10px] tabular-nums"
             style={{ color: 'rgba(248,250,252,0.35)' }}>
          <span>{fmtDay(data[0].day)}</span>
          <span>{fmtDay(data[data.length - 1].day)}</span>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Write tests** (mirror `UserApprovalPanel.test.tsx` import style — explicit vitest imports, no globals)

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MiniChart } from '../MiniChart';
import type { TimeseriesPoint } from '../../types/api';

const series: TimeseriesPoint[] = [
  { day: '2026-06-01', value: 2 },
  { day: '2026-06-02', value: 0 },
  { day: '2026-06-03', value: 5 },
];

describe('MiniChart', () => {
  it('renders a line chart with an accessible summary label', () => {
    render(<MiniChart title="Logins" data={series} type="line" accent="#A78BFA" />);
    expect(screen.getByRole('img', { name: /Logins: 7 insgesamt/ })).toBeInTheDocument();
  });

  it('shows an empty state when all values are zero', () => {
    const zero = series.map((p) => ({ ...p, value: 0 }));
    render(<MiniChart title="Logins" data={zero} type="bar" accent="#A78BFA" />);
    expect(screen.getByText('Keine Daten im Zeitraum')).toBeInTheDocument();
  });
});
```

> Coder note (avoid distortion): the root `<svg>` stretches horizontally (`width:100%` over a fixed `viewBox`). `<circle>` dot markers would scale non-uniformly into ellipses. So: add `vectorEffect="non-scaling-stroke"` to the `<polyline>`, and render the per-point data markers + tooltip hit-areas as `<rect>` (not `<circle>`) — a thin full-height transparent `<rect>` per point carrying the `<title>` gives a uniform, undistorted tap/hover target for both line and bar charts. Adjust the test's accessible-label assertion only if the role/aria-label wording changes (it should not).

**Step 3: Commit**

```bash
git add frontend/src/components/MiniChart.tsx frontend/src/components/__tests__/MiniChart.test.tsx
git commit -m "feat(admin): self-contained SVG MiniChart (line/bar)"
```

---

## Task 6: Frontend metrics panel — KPI tiles + charts + range selector [ ]

**Depends on:** Task 5

**Files:**
- Create: `frontend/src/components/MetricsPanel.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx` (mount `MetricsPanel` at the top of the panel stack)
- Test: `frontend/src/components/__tests__/MetricsPanel.test.tsx`

**Reuse check:** Mirrors `UserApprovalPanel` card shell + `cardStyle` (l.8-14) + fetch/loading/error pattern (l.30-45). Imports `MiniChart` (Task 5). Deviations: two fetches (summary + timeseries), range selector state.

**Design:** glass `<section>` shell. KPI tiles grid `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3`, each tile a sub-card (`rounded-xl p-3` with `cardStyle`-lite) showing label (`text-[11px]` muted) + value (`text-2xl font-bold tabular-nums`). Range selector = segmented control (7/30/90 Tage), `role="group"`, buttons ≥44px tall on mobile, active = accent gradient. Charts grid `grid grid-cols-1 sm:grid-cols-2 gap-4`. Loading = skeleton text; error = `role="alert"`.

**Step 1: Implement `MetricsPanel.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react';
import type { MetricsSummary, MetricsTimeseries } from '../types/api';
import { getMetricsSummary, getMetricsTimeseries } from '../api/client';
import { MiniChart } from './MiniChart';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

const RANGES = [7, 30, 90] as const;

function Tile({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <p className="text-[11px]" style={{ color: 'rgba(248,250,252,0.5)' }}>{label}</p>
      <p className="text-2xl font-bold tabular-nums" style={{ color: '#F8FAFC' }}>{value}</p>
      {sub && <p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.4)' }}>{sub}</p>}
    </div>
  );
}

export function MetricsPanel() {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<MetricsTimeseries | null>(null);
  const [days, setDays] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (range: number) => {
    setLoading(true);
    setError(null);
    try {
      const [s, t] = await Promise.all([getMetricsSummary(), getMetricsTimeseries(range)]);
      setSummary(s);
      setSeries(t);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(days); }, [load, days]);

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Nutzungs-Metriken</p>
        <div role="group" aria-label="Zeitraum" className="flex gap-1">
          {RANGES.map((r) => (
            <button key={r} type="button" onClick={() => setDays(r)}
              aria-pressed={days === r}
              className="px-3 py-2 rounded-lg text-xs font-medium transition-colors"
              style={days === r
                ? { background: 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))', color: '#fff' }
                : { background: 'rgba(255,255,255,0.06)', color: 'rgba(248,250,252,0.6)' }}>
              {r} Tage
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm py-6 text-center" style={{ color: 'rgba(248,250,252,0.35)' }}>Lade Metriken…</p>}
      {!loading && error && <p role="alert" className="text-sm py-6 text-center" style={{ color: '#EC4899' }}>Fehler: {error}</p>}

      {!loading && !error && summary && series && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-6">
            <Tile label="Nutzer gesamt" value={summary.users_total} sub={`${summary.users_pending} wartend`} />
            <Tile label="Freigeschaltet" value={summary.users_approved} />
            <Tile label="Aktiv (7 T)" value={summary.users_active_7d} sub={`${summary.users_active_30d} in 30 T`} />
            <Tile label="Annoncen gesamt" value={summary.listings_total} />
            <Tile label="Favoriten" value={summary.favorites_total} />
            <Tile label="Gespeicherte Suchen" value={summary.saved_searches_total} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <MiniChart title="Neue Annoncen / Tag" data={series.listings_new} type="bar" accent="#6366F1" />
            <MiniChart title="Verkauft / Tag" data={series.listings_closed} type="bar" accent="#EC4899" />
            <MiniChart title="Neue Nutzer / Tag" data={series.users_new} type="bar" accent="#A78BFA" />
            <MiniChart title="Logins / Tag" data={series.logins} type="line" accent="#34D399" />
            <MiniChart title="Benachrichtigungen / Tag" data={series.notifications} type="line" accent="#FBBF24" />
          </div>
        </>
      )}
    </section>
  );
}
```

**Step 2: Restructure `AdminPage.tsx` into a dashboard + link to the users page**

`/admin` becomes the dashboard (metrics + LLM). The user list moves to `/admin/users` (Task 7). Add `import { MetricsPanel } from '../components/MetricsPanel';`, `import { Link } from 'react-router-dom';`, **remove** the `UserApprovalPanel` import, and replace the panel stack:

```tsx
      <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
        <MetricsPanel />
        <LLMAdminPanel />
        <Link
          to="/admin/users"
          className="w-full rounded-2xl p-4 sm:p-6 flex items-center justify-between transition-colors"
          style={{
            background: 'rgba(15, 15, 35, 0.6)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
          }}
        >
          <span className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Benutzer-Verwaltung</span>
          <span aria-hidden="true" style={{ color: 'rgba(248,250,252,0.6)' }}>→</span>
        </Link>
      </div>
```

**Step 3: Write tests** (mirror import style; mock client)

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getMetricsSummary = vi.fn();
const getMetricsTimeseries = vi.fn();
vi.mock('../../api/client', () => ({
  getMetricsSummary: (...a: unknown[]) => getMetricsSummary(...a),
  getMetricsTimeseries: (...a: unknown[]) => getMetricsTimeseries(...a),
}));

import { MetricsPanel } from '../MetricsPanel';

const summary = {
  users_total: 4, users_approved: 3, users_pending: 1,
  users_active_7d: 2, users_active_30d: 3,
  listings_total: 120, favorites_total: 8, saved_searches_total: 5,
};
const emptySeries = (days: number) => Array.from({ length: days }, (_, i) => ({ day: `2026-06-${String(i + 1).padStart(2, '0')}`, value: 0 }));
const ts = { days: 30, listings_new: emptySeries(30), listings_closed: emptySeries(30), users_new: emptySeries(30), logins: emptySeries(30), notifications: emptySeries(30) };

describe('MetricsPanel', () => {
  beforeEach(() => {
    getMetricsSummary.mockResolvedValue(summary);
    getMetricsTimeseries.mockResolvedValue(ts);
  });

  it('renders KPI tiles from the summary', async () => {
    render(<MetricsPanel />);
    expect(await screen.findByText('Nutzer gesamt')).toBeInTheDocument();
    expect(screen.getByText('1 wartend')).toBeInTheDocument();
  });

  it('refetches the timeseries when the range changes', async () => {
    render(<MetricsPanel />);
    await screen.findByText('Nutzer gesamt');
    fireEvent.click(screen.getByRole('button', { name: '7 Tage' }));
    // initial 30 + the 7-day refetch (await React 19's async scheduler)
    await waitFor(() => expect(getMetricsTimeseries).toHaveBeenCalledWith(7));
  });
});
```

**Step 4: Commit**

```bash
git add frontend/src/components/MetricsPanel.tsx frontend/src/pages/AdminPage.tsx frontend/src/components/__tests__/MetricsPanel.test.tsx
git commit -m "feat(admin): metrics dashboard panel (KPIs + charts + range)"
```

---

## Task 7: Frontend — dedicated account-management page (/admin/users) with hard-delete [ ]

**Depends on:** Task 4

**Files:**
- Create: `frontend/src/pages/AdminUsersPage.tsx`
- Modify: `frontend/src/App.tsx` (add `/admin/users` route)
- Modify: `frontend/src/components/UserApprovalPanel.tsx` (add a delete action per row)
- Modify: `frontend/src/components/__tests__/UserApprovalPanel.test.tsx` (add delete tests)

**Reuse check:** `AdminUsersPage` mirrors `AdminPage.tsx` (`AdminPage.tsx:1-32`) — same role guard + container shell. `UserApprovalPanel` reuses the existing `useConfirm` destructive pattern in-file (l.52-58) and optimistic list state. Imports `deleteUser` (Task 4). Deviation: row removal instead of field toggle.

**Step 1: Create `AdminUsersPage.tsx` + route**

```tsx
import { Navigate, Link } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { UserApprovalPanel } from '../components/UserApprovalPanel';

interface Props {
  user: AuthUser;
}

export function AdminUsersPage({ user }: Props) {
  // Admin-only — mirror AdminPage guard.
  if (user.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-8 pb-12"
      style={{ color: '#F8FAFC' }}
    >
      <Link to="/admin" className="inline-block text-sm mb-4 sm:mb-6"
            style={{ color: 'rgba(248,250,252,0.6)' }}>
        ← Dashboard
      </Link>
      <h1 className="hidden sm:block text-2xl font-bold mb-8" style={{ color: '#F8FAFC' }}>
        Benutzer-Verwaltung
      </h1>
      <UserApprovalPanel currentUserId={user.id} />
    </div>
  );
}
```

In `frontend/src/App.tsx`, add `import { AdminUsersPage } from './pages/AdminUsersPage';` and a route directly after the existing `/admin` route (inside the same `<Routes>` block, `App.tsx:166-186`):

```tsx
        <Route path="/admin/users" element={<AdminUsersPage user={user} />} />
```

**Step 2: Add delete handler + button (`UserApprovalPanel.tsx`)**

Import `deleteUser` alongside the existing client imports. Add the handler next to `handleToggle`:

```tsx
  const handleDelete = useCallback(async (u: UserRow) => {
    const ok = await confirm({
      title: 'Konto endgültig löschen?',
      message: `„${u.email}" und alle zugehörigen Daten (Suchen, Favoriten, Geräte) werden unwiderruflich gelöscht (DSGVO).`,
      confirmLabel: 'Endgültig löschen',
      destructive: true,
    });
    if (!ok) return;
    const prev = rows;
    setRows((rs) => rs?.filter((r) => r.id !== u.id) ?? rs);  // optimistic removal
    try {
      await deleteUser(u.id);
    } catch (err: unknown) {
      setRows(prev ?? null);  // rollback
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen');
    }
  }, [confirm, rows]);
```

Add a delete button in each `<li>`, after the approve toggle, hidden for the current admin (`isSelf`):

```tsx
                  {!isSelf && (
                    <button type="button" onClick={() => { void handleDelete(u); }}
                      aria-label={`Konto ${u.email} löschen`}
                      className="shrink-0 rounded-lg px-2 py-2 text-xs font-medium transition-colors"
                      style={{ color: '#EC4899', background: 'rgba(236,72,153,0.08)', border: '1px solid rgba(236,72,153,0.25)' }}>
                      Löschen
                    </button>
                  )}
```

> The row `<li>` flex container already holds the label + toggle; ensure the new button sits in the same right-aligned action group (wrap the toggle + delete button in a `flex items-center gap-2` div if needed to avoid layout cramping; keep touch targets ≥44px and ≥8px apart per ux rules).

**Step 3: Add tests** (append to existing file; mock `deleteUser` in the existing `vi.mock('../../api/client', ...)` block and the `useConfirm` mock)

```tsx
  it('hard-deletes a user after confirmation and removes the row', async () => {
    getUsers.mockResolvedValue([baseRow]);          // baseRow.id !== currentUserId
    confirmMock.mockResolvedValue(true);
    deleteUser.mockResolvedValue(undefined);
    render(<UserApprovalPanel currentUserId={1} />);
    const btn = await screen.findByRole('button', { name: /Konto .* löschen/ });
    fireEvent.click(btn);
    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith(baseRow.id));
    await waitFor(() => expect(screen.queryByText(baseRow.email)).not.toBeInTheDocument());
  });

  it('does not render a delete button for the current admin', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, id: 1 }]);  // id === currentUserId
    render(<UserApprovalPanel currentUserId={1} />);
    await screen.findByText(baseRow.email);
    expect(screen.queryByRole('button', { name: /löschen/ })).not.toBeInTheDocument();
  });
```

> Coder note: add `deleteUser: (...a) => deleteUser(...)` to the existing client `vi.mock`, declare the `const deleteUser = vi.fn()`, and confirm `baseRow`'s id vs `currentUserId` so the self/non-self branches are exercised correctly. Reuse the existing `confirmMock`.

**Step 4: Commit**

```bash
git add frontend/src/pages/AdminUsersPage.tsx frontend/src/App.tsx frontend/src/components/UserApprovalPanel.tsx frontend/src/components/__tests__/UserApprovalPanel.test.tsx
git commit -m "feat(admin): dedicated /admin/users page + DSGVO hard-delete action"
```

---

## Task 8: Backend — per-user activity stats endpoint [IMPLEMENTED]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/api/admin.py` (add `UserStats` model + `GET /admin/users/{user_id}/stats`)
- Test: `backend/tests/test_admin_users.py` (append stats tests)

**Reuse check:** Mirrors the scalar-subquery shape of `metrics_summary` (Task 2) and the `require_admin` + `AsyncSessionLocal()` pattern. No new convention.

**Step 1: Add model + endpoint in `admin.py`**

```python
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
```

**Step 2: Append tests** (`backend/tests/test_admin_users.py`)

```python
@pytest.mark.asyncio
async def test_user_stats_counts(admin_client, db_session):
    client, _ = admin_client
    await _seed_user(db_session, "st-g", "st@example.com", is_approved=True)
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'st-g'")
    )).scalar_one()
    await db_session.execute(text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'a')"), {"u": uid})
    await db_session.execute(text("INSERT INTO login_events (user_id) VALUES (:u)"), {"u": uid})
    await db_session.commit()

    resp = await client.get(f"/api/admin/users/{uid}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved_searches"] == 1
    assert body["logins_total"] == 1
    assert set(body) >= {"favorites", "push_devices", "logins_30d", "created_at", "last_seen_at"}


@pytest.mark.asyncio
async def test_user_stats_404(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/users/999999/stats")
    assert resp.status_code == 404
```

**Step 3: Commit**

```bash
git add backend/app/api/admin.py backend/tests/test_admin_users.py
git commit -m "feat(admin): per-user activity stats endpoint"
```

---

## Task 9: Frontend — per-user analysis dialog [ ]

**Depends on:** Task 7, Task 8

**Files:**
- Modify: `frontend/src/types/api.ts` (add `UserStats`)
- Modify: `frontend/src/api/client.ts` (add `getUserStats`)
- Create: `frontend/src/components/UserStatsDialog.tsx`
- Modify: `frontend/src/components/UserApprovalPanel.tsx` (add "Analyse" button per row + dialog state)
- Test: `frontend/src/components/__tests__/UserStatsDialog.test.tsx` (create)

**Reuse check:** No existing reusable modal fits (ConfirmDialog is confirm-only; ListingDetailModal is route-bound). New lightweight glass dialog, designed extractable. Reuses `formatDate` (`utils/format.ts:17`) and `handleResponse` client pattern.

**Step 1: Types + client**

`types/api.ts`:
```typescript
export interface UserStats {
  user_id: number;
  saved_searches: number;
  favorites: number;
  push_devices: number;
  logins_total: number;
  logins_30d: number;
  created_at: string;
  last_seen_at: string | null;
}
```

`client.ts` (mirror `getMetricsSummary`):
```typescript
export async function getUserStats(userId: number): Promise<UserStats> {
  const res = await fetch(`/api/admin/users/${userId}/stats`);
  return handleResponse<UserStats>(res);
}
```

**Step 2: Create `UserStatsDialog.tsx`**

```tsx
import { useEffect, useState } from 'react';
import type { UserStats } from '../types/api';
import { getUserStats } from '../api/client';
import { formatDate } from '../utils/format';

interface Props {
  userId: number;
  email: string;
  onClose: () => void;
}

export function UserStatsDialog({ userId, email, onClose }: Props) {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getUserStats(userId)
      .then((s) => { if (active) setStats(s); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Fehler'); });
    return () => { active = false; };
  }, [userId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const rows: [string, string][] = stats ? [
    ['Gespeicherte Suchen', String(stats.saved_searches)],
    ['Favoriten', String(stats.favorites)],
    ['Push-Geräte', String(stats.push_devices)],
    ['Logins gesamt', String(stats.logins_total)],
    ['Logins (30 T)', String(stats.logins_30d)],
    ['Registriert', formatDate(stats.created_at)],
    ['Zuletzt gesehen', formatDate(stats.last_seen_at)],
  ] : [];

  return (
    <div role="dialog" aria-modal="true" aria-label={`Analyse ${email}`}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)' }} onClick={onClose}>
      <div className="w-full max-w-sm rounded-2xl p-6" onClick={(e) => e.stopPropagation()}
        style={{ background: 'rgba(15,15,35,0.85)', border: '1px solid rgba(255,255,255,0.1)',
                 backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)' }}>
        <div className="flex items-start justify-between mb-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Nutzer-Analyse</p>
            <p className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.5)' }}>{email}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Schließen" autoFocus
            className="text-lg leading-none px-2" style={{ color: 'rgba(248,250,252,0.6)' }}>×</button>
        </div>
        {error && <p role="alert" className="text-sm" style={{ color: '#EC4899' }}>Fehler: {error}</p>}
        {!error && !stats && <p className="text-sm" style={{ color: 'rgba(248,250,252,0.35)' }}>Lade…</p>}
        {stats && (
          <dl className="flex flex-col gap-2">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <dt className="text-sm" style={{ color: 'rgba(248,250,252,0.6)' }}>{k}</dt>
                <dd className="text-sm font-semibold tabular-nums" style={{ color: '#F8FAFC' }}>{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
```

**Step 3: Wire "Analyse" button into `UserApprovalPanel.tsx`**

Import `UserStatsDialog`, add a `statsUser` state (`useState<UserRow | null>(null)`), add an "Analyse" button in each row's action group, and render the dialog when set:

```tsx
                  <button type="button" onClick={() => setStatsUser(u)}
                    aria-label={`Analyse ${u.email}`}
                    className="shrink-0 rounded-lg px-2 py-2 text-xs font-medium transition-colors"
                    style={{ color: '#A78BFA', background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.25)' }}>
                    Analyse
                  </button>
```

After the `<ul>` (still inside the `<section>`):
```tsx
      {statsUser && (
        <UserStatsDialog userId={statsUser.id} email={statsUser.email} onClose={() => setStatsUser(null)} />
      )}
```

**Canonical action-group order** — replace the existing single-toggle action area in each `<li>` (currently the toggle is rendered bare after the `<div className="min-w-0">` info block, `UserApprovalPanel.tsx:127-151`) with this exact wrapper. Order is fixed: **Analyse → Toggle → Löschen**. Self row: only the disabled toggle (no Analyse, no Löschen).

```tsx
                  <div className="flex items-center gap-2 shrink-0">
                    {!isSelf && (
                      <button type="button" onClick={() => setStatsUser(u)}
                        aria-label={`Analyse ${u.email}`}
                        className="rounded-lg px-2 py-2 text-xs font-medium transition-colors"
                        style={{ color: '#A78BFA', background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.25)' }}>
                        Analyse
                      </button>
                    )}
                    {/* existing approve toggle (unchanged markup) goes here */}
                    {!isSelf && (
                      <button type="button" onClick={() => { void handleDelete(u); }}
                        aria-label={`Konto ${u.email} löschen`}
                        className="rounded-lg px-2 py-2 text-xs font-medium transition-colors"
                        style={{ color: '#EC4899', background: 'rgba(236,72,153,0.08)', border: '1px solid rgba(236,72,153,0.25)' }}>
                        Löschen
                      </button>
                    )}
                  </div>
```

This supersedes the standalone "Analyse" button snippet (Step 3 above) and the standalone delete-button snippet (Task 7 Step 2) — both are folded into this one ordered group. Keep targets ≥44px with ≥8px gaps (ux rule `touch-spacing`); the dedicated `/admin/users` page has the horizontal room.

**Step 4: Write tests** (`UserStatsDialog.test.tsx`, mirror explicit-vitest-import style)

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getUserStats = vi.fn();
vi.mock('../../api/client', () => ({
  getUserStats: (...a: unknown[]) => getUserStats(...a),
}));

import { UserStatsDialog } from '../UserStatsDialog';

const stats = {
  user_id: 5, saved_searches: 3, favorites: 7, push_devices: 2,
  logins_total: 19, logins_30d: 4, created_at: '2026-02-01T00:00:00Z', last_seen_at: null,
};

describe('UserStatsDialog', () => {
  beforeEach(() => { getUserStats.mockResolvedValue(stats); });

  it('loads and shows the per-user activity counts', async () => {
    render(<UserStatsDialog userId={5} email="x@example.com" onClose={() => {}} />);
    expect(await screen.findByText('Gespeicherte Suchen')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();      // logins_total
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(<UserStatsDialog userId={5} email="x@example.com" onClose={onClose} />);
    await screen.findByText('Gespeicherte Suchen');
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
```

> Coder note: add a render-the-dialog test to `UserApprovalPanel.test.tsx` only if the existing mock block is extended to include `getUserStats`; otherwise keep dialog coverage isolated in `UserStatsDialog.test.tsx` to avoid coupling.

**Step 5: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/components/UserStatsDialog.tsx frontend/src/components/UserApprovalPanel.tsx frontend/src/components/__tests__/UserStatsDialog.test.tsx
git commit -m "feat(admin): per-user analysis dialog"
```

---

## Task 10: Docs — fix stale single-user/no-auth claims, document admin dashboard [ ]

**Depends on:** Task 6, Task 7, Task 9

**Files:**
- Modify: `docs/definition.md` (replace single-user/no-auth narrative)
- Modify: `docs/architektur.md` (auth model, admin endpoints, telemetry, frontend-auth, test strategy)

**Step 1: Correct `definition.md`**

Replace the "single user / no auth" lines (`definition.md:3-4`) with the multi-user reality:

```markdown
> **Personal hobby project, invite-only.** Access is gated by Google SSO with an
> admin approval whitelist — multiple authenticated users, but no public signup.
> Roles: `member` (read-only browsing + saved searches/favorites) and `admin`
> (user approval, hard-delete, metrics dashboard, LLM cascade management).
> Keep it simple — no enterprise concerns beyond this auth/approval gate.
```

**Step 2: Correct `architektur.md`**

- Replace the scope lines (`architektur.md:4-5`) analogously to Step 1.
- Replace `architektur.md:103-105` "No auth required — read-only public interface" with: `Auth-gated SPA — unauthenticated users hit /login (Google SSO redirect); useAuth gates all routes; /admin requires role=admin.`
- Under an "Auth & Admin" subsection, document: Google OAuth2 callback `/api/auth/google/callback` with `is_approved` gate; JWT session cookie; `require_admin` for `/api/admin/*`; endpoints `GET /admin/users`, `PATCH /admin/users/{id}/approval`, `DELETE /admin/users/{id}` (DSGVO hard-delete, cascades), `GET /admin/metrics/summary`, `GET /admin/metrics/timeseries`; `login_events` telemetry (backend-only, no external analytics); 2FA enforced at Google-account level (no app-side TOTP).
- Expand the Test Strategy section to name the admin fixtures (`admin_client`, `authenticated_client`) and the explicit-vitest-import convention.
- Add one sentence clarifying metric semantics: `last_seen_at` is updated on every authenticated API call (`/api/auth/me`), so the "Aktiv (7/30 T)" tiles approximate users who made API requests in the window — not raw login counts (those are the separate `login_events` series).
- Coder note: read `architektur.md` in full and anchor edits by current content (search-and-replace), not by the line numbers cited above — doc line numbers drift.

**Step 3: Commit**

```bash
git add docs/definition.md docs/architektur.md
git commit -m "docs: reflect Google-SSO multi-user auth + admin dashboard (PLAN-033)"
```

_Code review closed 2026-06-14 (python, cycle 1): MINOR — 0 critical, 0 high, 3 medium, 2 low, 1 suggestion. Medium-1 (missing type hint on _series session) and Medium-3 (silent clamp → Query validator) fixed in follow-up commit a22b9d5; Medium-2 (ADD CONSTRAINT not idempotent under concurrent starts) deferred to backlog (single-container hobby project). No blocking issues._

---

## Verification

Run once, after all tasks are `[IMPLEMENTED]` (per dglabs.executing-plans Step 5):

**Backend** (Docker, per project `CLAUDE.md`):
```bash
docker compose up --build -d
docker compose exec backend pytest tests/ -v
```
Expected: all tests pass, incl. `test_login_telemetry.py`, `test_admin_metrics.py`, and the new cases in `test_admin_users.py`. The `db.init_db()` DDL runs on container start. The cascade is already asserted behaviorally by `test_login_telemetry.py::test_saved_searches_cascade_on_user_delete`; for a direct DDL spot-check that the FK is `ON DELETE CASCADE` (`confdeltype = 'c'`):
```bash
docker compose exec db psql -U postgres -d rcscout -c \
  "SELECT conname, confdeltype FROM pg_constraint WHERE conrelid = 'saved_searches'::regclass AND contype='f';"
# expect confdeltype = 'c' for the user_id FK
```
> Coder note: confirm the `db` service name + DB user/name against `docker-compose.yml` before running; adjust `-U`/`-d` to match.

**Frontend:**
```bash
cd frontend && npx tsc --noEmit && npm test
```
`tsc --noEmit` must pass first (catches contract drift between the Pydantic models and the TS interfaces, and any `ApiError`/type-import regressions). Then expected: `MiniChart.test.tsx`, `MetricsPanel.test.tsx`, `UserStatsDialog.test.tsx`, and updated `UserApprovalPanel.test.tsx` pass; no globals leakage (all tests import from 'vitest' explicitly).

> Coder note: if `frontend/package.json` already defines a typecheck script (e.g. `npm run typecheck` or a `tsc -b` in `build`), use that exact script instead of the raw `npx tsc --noEmit`.

**Manual smoke (single pass, not per-task):**
1. Log in via Google as the admin → `/admin` shows the Metrics panel first, then the LLM panel, then a "Benutzer-Verwaltung →" link card.
2. Range selector 7/30/90 switches the charts; empty series render "Keine Daten im Zeitraum". KPI tiles show non-zero `users_total`.
3. Click "Benutzer-Verwaltung →" → lands on `/admin/users`; "← Dashboard" link returns. A non-admin hitting `/admin/users` directly is redirected home.
4. Click "Analyse" on a user row → dialog shows that user's saved-searches / favorites / push-devices / login counts; Esc, the × button, and clicking the scrim all close it.
5. Delete a throwaway non-admin user → confirm dialog → row disappears; the user's saved searches are gone (DB check). Self-delete + delete button absent for own row.
6. Confirm a second login created a `login_events` row (logins/day chart increments next day; the user's analysis dialog `logins_total` reflects it).

---

## Plan Review
<!-- dglabs.agent.review-plan — 2026-06-14 -->

### Self-Review Gate (Pass 0)
- [x] 1. Placeholder scan — 0 matches (the `_To be completed` stub is in this section; body is clean)
- [x] 2. Dropped-field orphan scan — no renamed/dropped identifiers in the plan body
- [x] 3. Line-anchor freshness — all verified: `auth.py:45-130` ✓, `admin.py:99-120` ✓, `admin.py:123-160` ✓, `client.ts:151-155` ✓, `client.ts:167-174` ✓, `conftest.py:331-371` ✓, `conftest.py:375-417` ✓, `db.py:289` (last DDL block) ✓, `models.py:101` ✓. Minor: plan states "after l.119, before l.120" for the login-event insert; actual approval-gate return is at l.118 and `create_jwt` is at l.120 — the prose intent is correct (insert between those two lines) but the line reference is one off.
- [x] 4. Test-count consistency — no explicit "X tests" numeric claims; fixture shapes confirmed
- [x] 5. Deleted-class caller check — no deletions
- [x] 6. Mirror-reference verification — `UserApprovalPanel.tsx:8-14` (cardStyle) ✓, `UserApprovalPanel.tsx:30-45` (fetch/loading/error) ✓, `UserApprovalPanel.test.tsx` (import style) ✓
- [x] 7. Convention contradictions — `authenticated_client` yields a bare `AsyncClient` (conftest.py:375/416); Task 2 test code uses `client = authenticated_client` — correct, no contradiction

### Structural Checklist (Pass 1.A)
- [x] Required sections present (Context & Goal, Steps, Verification)
- [x] Step status markers present (`[ ]` on all tasks)
- [x] Step granularity suitable for a fresh AI instance (8 tasks, each scoped)
- [x] Test files named per step
- [x] Breaking changes marked (explicitly "No API breaks; one DB change")
- [x] BREAK markers — zero BREAKs, appropriate for this plan

### 🔴 Blocking

1. **[Agent] `backend/app/db.py` — FK constraint name `saved_searches_user_id_fkey` not guaranteed.**
   The plan's `DROP CONSTRAINT IF EXISTS saved_searches_user_id_fkey` relies on PostgreSQL's auto-naming convention (`{table}_{col}_fkey`). This name is only generated when the FK is created via bare `REFERENCES` DDL. SQLAlchemy's `Base.metadata.create_all` uses `CREATE TABLE ... REFERENCES ...` which does produce the standard PostgreSQL auto-name — so the name is likely correct. However, SQLAlchemy does NOT set an explicit naming convention here (no `MetaData(naming_convention=...)` in `db.py`), so the ORM-level name and the DB-level name are independent. The safe fix is to query the actual constraint name first:
   ```sql
   -- Idempotent, safe regardless of naming:
   DO $$ BEGIN
     IF EXISTS (
       SELECT 1 FROM information_schema.table_constraints
       WHERE table_name = 'saved_searches' AND constraint_type = 'FOREIGN KEY'
         AND constraint_name = 'saved_searches_user_id_fkey'
     ) THEN
       ALTER TABLE saved_searches DROP CONSTRAINT saved_searches_user_id_fkey;
     END IF;
   END $$;
   ALTER TABLE saved_searches ADD CONSTRAINT saved_searches_user_id_fkey
     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
   ```
   Or simpler: add `ADD CONSTRAINT IF NOT EXISTS` pattern using a unique probe. The plan must either (a) use the DO-block guard shown above, or (b) add a verification step that runs `\d saved_searches` in Docker before merging. Without this fix, a constraint name mismatch silently skips the DROP but then the ADD fails with "constraint already exists" or, worse, creates a second FK with the new name while the old cascadeless FK remains active. **Risk: DSGVO delete silently does NOT cascade.**

2. **[Agent] `frontend/src/components/__tests__/MetricsPanel.test.tsx` — direct `.click()` without `await waitFor(...)` makes the range-change test non-deterministic.**
   The test:
   ```tsx
   screen.getByRole('button', { name: '7 Tage' }).click();
   expect(getMetricsTimeseries).toHaveBeenCalledWith(7);
   ```
   Calling `.click()` directly (not `fireEvent.click`) dispatches a native DOM event. React 19 in concurrent mode may batch the resulting `setDays(7)` state update and the subsequent `useEffect` re-run asynchronously. The assertion fires synchronously after `.click()` before the effect executes. This will intermittently pass in jsdom (depending on React's scheduler flushing) but is structurally unreliable. Fix: use `fireEvent.click(...)` + `await waitFor(() => expect(getMetricsTimeseries).toHaveBeenCalledWith(7))`. Both calls to `getMetricsTimeseries` (initial 30 + the 7-day re-fetch) must be awaited; the test comment says "initial 30 + the 7-day refetch" but the assertion does not wait for the second call to settle.

3. **[AI-Review] `frontend/src/api/client.ts` — `deleteUser` uses `new ApiError(res.status, ...)` — investigate constructor compatibility.**
   Codex flagged this as a compile failure (treating `ApiError` as an interface). **Actual finding:** `ApiError` IS a class (`export class ApiError extends Error` at `types/api.ts:143`), so instantiation is valid. However, the plan's `deleteUser` does NOT import `ApiError` from `../types/api` — `client.ts` currently only imports named types (interfaces + the class re-exported as a value). The plan says "confirm `ApiError` is imported there" — but it is only imported as a type-shape reference in the existing import block (`import { ApiError } from '../types/api'` at line 17 of client.ts shows it IS imported as a value). Verify the existing import line before implementation; if the import uses `import type { ApiError }` it will not be available as a runtime value. The plan must explicitly state: "ensure `ApiError` is imported as a value (not `import type`), which it already is at `client.ts:17`." The risk is that a future refactor could introduce `import type` and silently break this. Low risk but needs an explicit coder note. **Severity: blocking because the plan's verification step does not include a TypeScript build check (`tsc --noEmit`) and this is the exact failure mode Codex found.**

### 🟡 Non-Blocking

1. **[Agent] `backend/app/api/admin.py` — `_series` helper uses 2 queries per series × 5 series = 10 round-trips inside one session.**
   The zero-fill base date is computed via SQL (`now()::date - make_interval(...)`) but this is a pure computation that could be done in Python: `base = date.today() - timedelta(days=days - 1)`. Removing the second query per series halves the DB round-trips (10→5). This is an admin-only endpoint so impact is negligible, but it would simplify the code.

2. **[Agent] `backend/app/api/auth.py` — login-event insert happens before the response is fully committed/returned.**
   The `session.commit()` in the plan's patch (after the INSERT INTO login_events) commits the login record before the JWT cookie response is sent. If a network error or middleware exception prevents the redirect response from reaching the client, the login_event row is already persisted. For a personal hobby app this is acceptable telemetry fidelity, but it means `logins/day` counts approved OAuth callbacks rather than confirmed client-side sessions. Documented for transparency; [AI-Review] raised this as well.

3. **[Agent] `backend/tests/test_admin_metrics.py` — `test_metrics_timeseries_zero_filled_and_clamped` does not assert `logins` length matches `days`.**
   The test asserts `len(body["logins"]) == 7` and `len(body["listings_new"]) == 7` but omits `listings_closed`, `users_new`, and `notifications`. These may diverge if the zero-fill loop has a bug. Asserting all 5 series have length == `days` would be more complete coverage.

4. **[Agent] `frontend/src/components/MiniChart.tsx` — `preserveAspectRatio="none"` on the root SVG distorts the line chart's circular dot markers.**
   Setting `preserveAspectRatio="none"` on the root `<svg>` means the entire plot (including `<circle r={2}>` dots) gets non-uniform scaling. Circles become ellipses. The design note says "on the plot area only" — but the implementation puts it on the root `<svg>`. Consider using `preserveAspectRatio="xMidYMid meet"` on the root SVG and `preserveAspectRatio="none"` only on an inner `<g>` using a `<clipPath>`. For a minimalist dashboard tile this is a low-priority visual note.

5. **[Agent] `docs/architektur.md` Task 8 — plan instructs replacing `architektur.md:4-5` and `architektur.md:103-105` without reading their current content first.**
   Line numbers in docs drift over time. The coder agent must read the actual current content before searching for the replacement text. The plan should add: "Read `architektur.md` in full before editing; do not use line numbers as anchors — search by content." Consider adding the exact current text as `old_string` anchors in the task description for Edit-tool safety.

6. **[Agent] `backend/tests/test_login_telemetry.py` — test lacks `@pytest.mark.asyncio` on the second test function label in the plan body.**
   Both functions in the plan have `@pytest.mark.asyncio` — this is correct. Just confirming no issue here. ✓ (Listed for completeness of the check.)

7. **[Agent] `backend/app/api/admin.py` metrics SQL — `users_active_7d` / `users_active_30d` depend on `last_seen_at` being populated.**
   `last_seen_at` is only updated by `/api/auth/me` (auth.py:139-142), not by the OAuth callback. A user who logs in but never triggers `/api/auth/me` (e.g., a direct SPA hydration failure) will have `last_seen_at = NULL`. This means `active_7d` undercounts real sessions. Not introduced by this plan — pre-existing gap — but documenting since the metrics tile claims "Aktiv (7 T)." Consider adding a note in the docs task (Task 8) that `last_seen_at` is updated on every authenticated API call, so the "active" metric approximates users who make API requests (not logins).

8. **[Agent] Task 6 — `MetricsPanel` test imports `MetricsPanel` AFTER the `vi.mock` calls.**
   The test puts `vi.mock(...)` before the `import { MetricsPanel }` line. This is the correct pattern in Vitest (hoisted mocks), so it works. No issue, but it differs visually from the UserApprovalPanel test (which has imports first, then mock setup inside `beforeEach`). Coder should be aware this is intentional — Vitest hoists `vi.mock` calls regardless of textual position.

### Verdict
REVISE — Three blocking issues (see above).

_Plan review closed 2026-06-14 (cycle 1): all 3 blocking findings incorporated — (1) FK drop now uses a name-agnostic DO-block guard in `db.py`; (2) MetricsPanel test switched to `fireEvent.click` + `await waitFor`; (3) `tsc --noEmit` added to Verification + value-import coder note. Non-blocking NB4 (SVG distortion) and NB7 (`last_seen_at` semantics) folded in as coder notes; remaining non-blocking items deferred to `docs/backlog.md`._

---

### Cycle-2 Review (delta: Tasks 6–10 restructure + new Tasks 8 & 9)
<!-- dglabs.agent.review-plan — 2026-06-14 -->

#### Pass 0: Self-Review Gate (cycle-2 delta only)

- [x] 1. Placeholder scan — 0 matches in body; plan review section exempt.
- [x] 2. Dropped-field orphan scan — `UserApprovalPanel` import removed from `AdminPage`; plan body correctly has no surviving reference to `UserApprovalPanel` in `AdminPage.tsx` context (Task 6 Step 2 describes the removal). Task 6 Context header still notes "`Docs task renumbered to Task 10`" in the orchestrator prompt — confirmed Task 10 is the docs task; renumber is clean.
- [x] 3. Line-anchor freshness (new/changed anchors) — `App.tsx:166-186` verified: actual `<Route path="/admin">` is at line 185 inside `<Routes>` starting at line 167 (close enough; the plan's range is correct). `UserApprovalPanel.tsx:8-14` (cardStyle) ✓ verified live. `utils/format.ts:17` (`formatDate`) ✓ verified live. `client.ts:17` (`ApiError` value import) ✓ verified live (`import { ApiError } from '../types/api'` — not `import type`). Context section still cites `admin.py:99-120` / `admin.py:123-160` — those are cycle-1 anchors; admin.py currently only has 30 lines (LLM endpoints); the plan's new endpoints don't exist yet, so these references are forward-looking descriptions, not stale anchors. Acceptable.
- [x] 4. Test-count consistency — no explicit "X tests" claims added in cycle-2 delta. The Task 7 test snippet names 2 new `it(...)` blocks; the Task 9 test snippet names 2 `it(...)` blocks. No numeric claim drifts.
- [x] 5. Deleted-class caller check — Task 6 removes `UserApprovalPanel` import from `AdminPage.tsx`. Verified `AdminPage.tsx:4` currently imports `UserApprovalPanel`. No other caller of `UserApprovalPanel` in `AdminPage` context (the component continues to exist in `UserApprovalPanel.tsx` and is used in the new `AdminUsersPage.tsx`). Dangling import will be removed by Task 6 as instructed. Clean.
- [x] 6. Mirror-reference verification — Task 9 claims "No existing reusable modal fits (ConfirmDialog is confirm-only; ListingDetailModal is route-bound)". Verified: `ConfirmDialog` is a confirm-action pattern; `ListingDetailModal` wraps React Router modal state. Claim is accurate. `formatDate(iso: string|null): string` at `utils/format.ts:17` ✓ — signature matches plan description. `getUserStats` client mirror: plan correctly models `handleResponse<UserStats>(res)` shape matching `getMetricsSummary`. ✓
- [x] 7. Convention contradictions — `UserStats` Pydantic (Task 8) vs TS `UserStats` interface (Task 9): field-by-field comparison:
  - Pydantic: `user_id`, `saved_searches`, `favorites`, `push_devices`, `logins_total`, `logins_30d`, `created_at: datetime`, `last_seen_at: datetime | None`
  - TS: `user_id`, `saved_searches`, `favorites`, `push_devices`, `logins_total`, `logins_30d`, `created_at: string`, `last_seen_at: string | null`
  - All 8 fields match exactly (datetime→string mapping is correct for JSON serialization). ✓
  - Task 7 adds `handleDelete` taking `u: UserRow`; Task 9 adds `handleStats` button opening dialog. Both share the row `<li>` action group. The plan correctly notes wrapping toggles in a `flex items-center gap-2` container. No contradiction.
  - Task 7 test selector `{ name: /Konto .* löschen/ }` matches the button `aria-label={`Konto ${u.email} löschen`}`. Task 9 test uses `{ name: 'Schließen' }` matching `aria-label="Schließen"`. No overlap/ambiguity.

#### Pass 1: Structural & Content Review (cycle-2 delta)

**A. Structural Checklist (delta tasks 6–10)**
- [x] All new tasks have `[ ]` status markers
- [x] Task 9 dependency on Task 7 + 8 is explicit (`Depends on: Task 7, Task 8`)
- [x] Task 10 dependency on Tasks 6, 7, 9 is explicit
- [x] Test files named for Tasks 7, 8, 9 ✓
- [x] Task count updated in structural checklist header to "8 tasks" — actually plan now has 10 tasks; structural note still says 8. Minor; not a plan body error.

**B. Codebase Consistency (new tasks)**

Route placement (Task 7): `App.tsx:185` has `<Route path="/admin" element={<AdminPage user={user} />} />`. Adding `/admin/users` directly after it (as a sibling `<Route>`) inside the same `<Routes>` block is correct React Router v6 — both routes are non-wildcard, no ordering conflict. The import of `AdminUsersPage` must be added to `App.tsx`; the plan specifies this. ✓

`AdminPage.tsx` import cleanup (Task 6): `UserApprovalPanel` is currently imported at line 4 and used at line 28. Task 6 removes the import and removes the usage, replacing it with `<Link to="/admin/users">`. The plan's Task 6 Step 2 shows the replacement JSX for the panel stack; it correctly drops `UserApprovalPanel`. ✓ No dangling import will remain.

Task 8 SQL correctness: all 4 tables counted (`saved_searches`, `user_favorites`, `push_subscriptions`, `login_events`) have `user_id` columns confirmed in `models.py`. `search_notifications` does NOT have `user_id` — the plan correctly does not count it. The `one_or_none()` call on a single-row result from a `WHERE u.id = :uid` primary-key lookup is safe. `interval '30 days'` syntax is valid PostgreSQL. ✓

Task 9 `UserStatsDialog`: `formatDate(iso: string | null): string` signature verified at `utils/format.ts:17` — matches the plan's `formatDate(stats.last_seen_at)` call where `last_seen_at: string | null`. ✓ The `getUserStats` client function mirrors `getMetricsSummary` pattern exactly. ✓

**C. Step Granularity — Task 9 row-action group complexity flag**

Task 9 adds a third button ("Analyse") to each row in `UserApprovalPanel`. The row now has: Analyse button + toggle switch + (conditional) delete button. The plan's layout note says to wrap them in `flex items-center gap-2`. However, the plan does NOT show the complete updated `<li>` JSX with all three elements in their final arrangement — it only shows the Analyse button snippet and the dialog mount point. A coder agent must reconstruct the final `<li>` layout mentally from three separate task snippets (Task 7 Step 2 + Task 9 Step 3), which is ambiguous about ordering (Analyse | Toggle | Delete vs. Delete | Toggle | Analyse). This is a non-blocking ambiguity — the plan gives layout guidance and the three snippets are clear individually — but a coder note stating the explicit button order would remove any uncertainty.

**D. Best Practices**

`login_events` table created in Task 1 with only one index (`idx_login_events_logged_in_at`). The `user_id` FK column has no index. PostgreSQL does NOT automatically create indexes on FK referencing columns. The Task 8 per-user stats query `SELECT count(*) FROM login_events WHERE user_id = u.id` and the ON DELETE CASCADE scan will both hit an unindexed `user_id` column. For a personal app with low cardinality this is operationally fine, but it is a structural omission. [AI-Review] flagged this.

The Verification section's DDL smoke command (`python -c "... asyncio.run((lambda: None)())"`) does not actually test that `init_db()` ran or that the cascade FK exists. [AI-Review] correctly flagged this as a non-verifying verification step.

#### Pass 2: AI-Review (codex, no fallback)

Provider: `codex` (gpt-5.4), duration 78 750 ms. Three findings:

1. `[AI-Review]` **recommended / correctness** — Task 1 tests only the `login_events` schema/cascade; a broken OAuth callback insert path (Step 3 of Task 1) would pass the test suite and silently ship empty login metrics. Suggestion: add an auth-flow test asserting one `login_events` row per successful approved callback, zero for unapproved.

2. `[AI-Review]` **recommended / performance** — `login_events` DDL indexes only `logged_in_at`; queries and CASCADE DELETEs by `user_id` will force full scans. Suggestion: add `CREATE INDEX IF NOT EXISTS idx_login_events_user_id ON login_events (user_id)` (or a composite `(user_id, logged_in_at)`) in the Task 1 DDL block.

3. `[AI-Review]` **recommended / correctness** — Verification smoke command `python -c "... asyncio.run((lambda: None)())"` imports `app.db` but exits without calling `init_db()`, so a broken migration does not fail CI. Suggestion: replace with a real DDL assertion (SQL query on `pg_constraint`/`pg_indexes`) or fold the check into a dedicated pytest.

#### 🔴 Blocking (cycle-2)

1. **[AI-Review] `backend/app/db.py` Task 1 DDL — missing `user_id` index on `login_events`.**
   `login_events(user_id)` is a FK column with no index. PostgreSQL does not create indexes on referencing FK columns automatically. The Task 8 endpoint runs `SELECT count(*) FROM login_events WHERE user_id = u.id` (a filter, not a PK lookup) and ON DELETE CASCADE from `users` also scans by `user_id`. With a growing login table this degrades to a sequential scan for every per-user stats call and for every user deletion. Fix: add `CREATE INDEX IF NOT EXISTS idx_login_events_user_id ON login_events (user_id)` immediately after the `login_events` table DDL block in Task 1 Step 1. This is straightforward and must be done before the table ships.

2. **[Agent] `frontend/src/components/UserApprovalPanel.tsx` Task 9 — final button order in the row action group is ambiguous across task snippets.**
   Task 7 Step 2 adds a delete button after the existing toggle. Task 9 Step 3 adds an Analyse button. The plan never shows the complete resolved `<li>` with all three controls in final order. A coder constructing the JSX must guess: is it [Analyse | Toggle | Delete] or [Toggle | Analyse | Delete]? The plan's Task 9 layout note says "Analyse + toggle (+ delete for non-self)" — this implies Analyse comes first, but the Task 7 snippet places Delete after Toggle, and the Analyse button snippet in Task 9 does not reference its position relative to Delete. The test selectors use `aria-label` patterns and are unambiguous, but the visual layout is underspecified. Fix: the plan must include a final resolved `<li>` JSX comment showing button order — e.g., `[Analyse] [Toggle] [Delete?]` — so the agent produces a consistent layout without guessing.

#### 🟡 Non-Blocking (cycle-2)

1. **[AI-Review] `backend/tests/test_login_telemetry.py` — OAuth callback insert path untested.** The `test_login_events_table_exists_and_cascades` test proves the DB schema, but does not exercise `auth.py`'s INSERT path. A separate `test_oauth_callback_records_login_event` test (using `admin_client` fixture + mock OAuth state) would prevent regressions in the actual telemetry path. Low priority for a personal app but worthwhile coverage.

2. **[AI-Review] Verification — DDL smoke command is non-verifying.** The `python -c "import asyncio; from app.db import engine; asyncio.run((lambda: None)())"` command exits 0 whether or not `init_db()` ran. Replace with a real assertion: `docker compose exec backend python -c "import asyncio; from app.db import init_db, engine; asyncio.run(init_db())"` (safe — idempotent DDL) or add a pytest fixture that queries `pg_constraint WHERE conname = 'saved_searches_user_id_fkey' AND confdeltype = 'c'` to confirm cascade. This is already guarded by `test_login_telemetry.py:test_saved_searches_cascade_on_user_delete`, so the smoke command is redundant and misleading — the plan should either remove it or replace it with a meaningful assertion.

3. **[Agent] Task 9 `UserStatsDialog` — missing `aria-modal` focus trap.** The dialog renders with `role="dialog" aria-modal="true"` but has no focus trap. On open, focus remains on the triggering "Analyse" button outside the dialog. Screen readers will announce the dialog but keyboard users (Tab key) will tab through the rest of the page. For a personal admin tool this is low priority, but since the plan explicitly applies `aria-modal="true"` it creates a false accessibility contract. Either add a focus trap (e.g., `autoFocus` on the close button) or remove `aria-modal` and use `role="alertdialog"` for a simpler accessible pattern.

4. **[Agent] Task 10 structural note — step count in Pass 1 checklist says "8 tasks" but plan has 10.** The cycle-1 structural checklist entry reads "8 tasks, each scoped". After the restructure the plan has 10 tasks. The cycle-2 checklist above corrects this; the plan body itself is fine.

#### Verdict (cycle-2)
REVISE — 2 new blocking issues (see above).

_Plan review closed 2026-06-14 (cycle 2): both blocking incorporated — (1) `idx_login_events_user_id` index added to Task 1 DDL; (2) canonical resolved `<li>` action group with fixed order Analyse → Toggle → Löschen added to Task 9. Cycle-2 NB2 (misleading smoke command → real `pg_constraint` check) and NB3 (`autoFocus` on dialog close) folded in; NB1 (OAuth-callback insert test) deferred to backlog. Plan ready for Human approval._
