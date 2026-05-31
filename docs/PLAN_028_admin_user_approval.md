# Admin User Approval Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Give the admin a profile card to list all users and toggle their `is_approved` flag (replacing today's manual DB `UPDATE`), with a mobile pull-to-refresh gesture to refetch the list.

**Architecture:** Two new endpoints in the existing `backend/app/api/admin.py` router (already mounted at `/api/admin` via `routes.py`, both behind `require_admin`). A new `UserApprovalPanel.tsx` card rendered in `ProfilePage` only for `user.role === 'admin'`, mirroring the existing `LLMAdminPanel` pattern. A new mobile-only `usePullToRefresh` hook lets the admin pull the list down (touch, container at `scrollTop === 0`) to re-run `GET /api/admin/users`; scope is strictly this panel — not the listings page, not the whole app. Purely additive — no schema change, no migration.

**Tech Stack:** FastAPI + raw SQLAlchemy `text()` (mirror `admin.py`), Pydantic v2 response models; React 19 + TypeScript, bare `fetch` + `handleResponse<T>`, existing `useConfirm` + `role="switch"` toggle conventions; custom touch-event hook (`touchstart`/`touchmove`/`touchend`, no library).

**Breaking Changes:** No — additive endpoints + additive UI card. No existing contract changes.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-05-31 |
| Human | approved | 2026-05-31 |

---

## Context (verified, not from memory)

### Backend

- **`backend/app/api/admin.py`** — `router = APIRouter(prefix="/admin", tags=["admin"])` (line 14). Imports `from app.api.deps import require_admin` (line 9), `from app.db import AsyncSessionLocal` (line 10), `from app.models import User` (line 11), `from sqlalchemy import text` (line 12). Endpoint pattern (`list_llm_models`, lines 72-75):
  ```python
  @router.get("/llm-models", response_model=list[LLMModelRow])
  async def list_llm_models(_: User = Depends(require_admin)) -> list[LLMModelRow]:
      """..."""
      return await _fetch_all_rows()
  ```
  Helpers open their own session: `async with AsyncSessionLocal() as session:` then `await session.execute(text(...))` (lines 33-49). Pydantic response models are `BaseModel` subclasses defined in the same file (lines 17-28).

- **`backend/app/api/deps.py`** — signatures:
  - `async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User` (line 12). Rejects unapproved users with 401.
  - `async def require_admin(user: User = Depends(get_current_user)) -> User` (line 32) — raises `HTTPException(403, "Admin role required")` if `user.role != "admin"`, else returns the user. **This is how the PATCH gets `current_admin.id`: declare the param as `current_admin: User = Depends(require_admin)`.**

- **`backend/app/models.py`** — `User` (lines 82-94), confirmed fields:
  - `id: int` (PK), `google_id: str`, `email: str`, `name: str | None`, `is_approved: bool` (server_default `"false"`), `role: str` (server_default `"member"`), `created_at: datetime` (tz-aware, server_default `now()`), `last_seen_at: datetime | None`.

- **`backend/app/main.py`** — admin router mount: **already mounted.** `main.py` does NOT import admin directly; instead `routes.py` does `from app.api.admin import router as admin_router` (line 11) and `router.include_router(admin_router)` (line 29), where `router = APIRouter(prefix="/api")` (line 28). `main.py:210` mounts that business router via `app.include_router(router)`. Net path = `/api` + `/admin` = **`/api/admin`**. No mount task needed.

- **`backend/app/api/auth.py`** — `/auth/me` (lines 133-149) returns `{ "id": user.id, "email": user.email, "name": user.name, "role": user.role }`. So `role` AND `id` are both already delivered to the frontend.

### Frontend

- **`frontend/src/hooks/useAuth.ts`** — `AuthUser` type (lines 3-8): `{ id: number; email: string; name: string | null; role: 'member' | 'admin' }`. Already has `id` and `role` — no change needed.

- **`frontend/src/pages/ProfilePage.tsx`** — admin cards rendered in the settings stack (lines 237-240):
  ```tsx
  <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
    <NotificationsPanel />
    {user.role === 'admin' && <LLMAdminPanel />}
  </div>
  ```
  `user` is the `AuthUser` prop (line 15). New panel slots in here behind the same `user.role === 'admin'` guard. `cardStyle` is defined inline (lines 76-82) but each panel defines its own — see below.

- **`frontend/src/components/LLMAdminPanel.tsx`** — canonical card shell. Card wrapper (lines 136-144): `className="w-full rounded-2xl p-4 sm:p-6"` + inline `style={{ background: 'rgba(15,15,35,0.6)', border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(20px)', boxShadow: '0 8px 32px rgba(0,0,0,0.3)' }}`. Header label (line 148): `<p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>`. Load/error/empty state pattern: lines 84-107 (`useEffect` fetch with `cancelled` guard, `loading`/`error` state), 202-214 (loading + error JSX), 287-293 (empty-table row). Table styling: lines 217-240.

- **`frontend/src/components/NotificationsPanel.tsx`** — **canonical toggle (`role="switch"`)** at lines 144-162. Mirror this exact switch markup. Also the optimistic-toggle pattern with rollback (lines 43-51): set local state, fire API, `.catch` rolls back to `previous`. Card shell uses module-level `const cardStyle` (lines 7-13) — `<section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>`.

- **`frontend/src/components/ConfirmDialog.tsx`** — `useConfirm(): (opts: ConfirmOptions) => Promise<boolean>` (line 263). `ConfirmOptions` (lines 12-19): `{ title: string; message?: string; confirmLabel?: string; cancelLabel?: string; destructive?: boolean }`. Provider already wraps the app in `main.tsx` — just `const confirm = useConfirm();` and `await confirm({...})`.
  - **Canonical confirm callsite to mirror:** `DetailPage.tsx:332-337`:
    ```tsx
    const ok = await confirm({
      title: 'Als verkauft markieren?',
      message: `„${listing!.title}" wird als verkauft gekennzeichnet.`,
      confirmLabel: 'Verkauft',
    });
    if (!ok) return;
    ```

- **`frontend/src/api/client.ts`** — `handleResponse<T>(res)` (lines 18-30) reads `body.detail` on non-ok and throws `ApiError`. Existing admin calls (lines 151-159): `getLLMModels` does bare `await fetch('/api/admin/llm-models')` → `handleResponse<LLMModelRow[]>(res)`. A PATCH-with-JSON-body example is `updateNotificationPrefs` (lines 171-178): `method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(partial)`. Import `ApiError` from `'../types/api'` (line 16).

- **`frontend/src/types/api.ts`** — DTOs live here as `export interface`. `LLMModelRow` at lines 196-208. `ApiError` class at line 143.

- **`frontend/src/hooks/`** (Pull-to-refresh reuse scan) — existing hooks: `useAuth.ts`, `useInfiniteListings.ts`, `useListings.ts`, `useListingsScrollPreservation.ts`, `useSavedSearches.ts`. **No existing pull-to-refresh hook.** Grep for `touchstart`/`touchmove`/`touchend`/`overscroll`/`scrollTop`/`PullToRefresh` found only:
  - **Swipe-to-dismiss** (NOT a PTR pattern, not reusable): `FilterPanel.tsx:85-91` and `ComparablesModal.tsx:120` — bare JSX `onTouchStart`/`onTouchEnd` storing `clientY` in a ref and comparing a single end-delta to dismiss a bottom sheet. No `touchmove`, no live pull distance, no top-of-scroll guard.
  - **`overscroll-behavior: contain`**: `ListingDetailModal.tsx:68` inline style on the modal wrapper — precedent for taming native scroll, but unrelated to PTR.
  - Hook convention: hooks are plain functions returning a typed result object (see `useInfiniteListings.ts:15-28` `UseInfiniteListingsResult` interface + `export function`). Cleanup via `useEffect` return removing listeners (`useListingsScrollPreservation.ts:85-89`). → `usePullToRefresh` is a NEW hook with a NEW convention (no reusable PTR/touchmove pattern exists); write it in full.

- **`frontend/vite.config.ts:48-51`** — Vitest config has `globals: true` and `setupFiles: ['./src/test-setup.ts']`. Despite `globals: true`, project convention (CLAUDE.md + every existing test) is to import Vitest globals EXPLICITLY. Hook tests use `renderHook` + `waitFor` from `@testing-library/react` (canonical: `useInfiniteListings.test.tsx:11-12`). Header convention: `import { describe, it, expect, vi, beforeEach } from 'vitest';`.

### Tests

- **Backend** — `backend/tests/conftest.py`. Fixtures: `db_session` (line 98), `authenticated_client` (line 330) — authenticates as a fresh **member** user (role defaults to `'member'`, inserted via raw SQL, `get_current_user` overridden). `clean_listings` (line 161, autouse) truncates `users` + `listings` before each test. **No admin fixture or admin-endpoint test exists** (`require_admin` is never overridden anywhere) → Task 4 adds an `admin_client` fixture. The `_fake_user` in `authenticated_client` (lines 359-366) selects `role` from the DB, so seeding `role='admin'` flows through `require_admin` naturally.
- **Frontend** — co-located `__tests__/`. Vitest globals NOT enabled → every test imports `import { describe, it, expect, vi } from 'vitest'`. `frontend/src/pages/__tests__/DetailPage.test.tsx:22-25` mocks `ConfirmDialog` (`useConfirm: () => vi.fn().mockResolvedValue(false)`). `NotificationsPanel.test.tsx` exists as a component-test reference.

### Cross-Layer DTO Contract (must be identical on both sides)

`UserRow` — backend Pydantic (Task 1) AND frontend TS interface (Task 2):

| Field | Backend (Pydantic) | Frontend (TS) |
|---|---|---|
| `id` | `int` | `number` |
| `email` | `str` | `string` |
| `name` | `str \| None` | `string \| null` |
| `is_approved` | `bool` | `boolean` |
| `role` | `str` | `string` |
| `created_at` | `datetime` | `string` (ISO) |
| `last_seen_at` | `datetime \| None` | `string \| null` (ISO) |

---

## Task 1: Backend endpoints (list + approval PATCH) [IMPLEMENTED]

**Files:**
- Modify: `backend/app/api/admin.py`

**Step 1: Add the `UserRow` response model**

Add after the existing `LLMModelRow` model (i.e. after line 28). Mirror the `BaseModel` style already in the file.

```python
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
```

**Step 2: Add the list endpoint**

`HTTPException` is not yet imported in `admin.py` — extend the FastAPI import line (currently `from fastapi import APIRouter, Depends`) to `from fastapi import APIRouter, Depends, HTTPException`.

Append these endpoints to the end of the file. Mirror the `_fetch_all_rows` session pattern (own `AsyncSessionLocal()` context). Sort: not-approved first, then `created_at DESC`.

```python
@router.get("/users", response_model=list[UserRow])
async def list_users(_: User = Depends(require_admin)) -> list[UserRow]:
    """Return all users, not-yet-approved first, then newest-registered first."""
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
```

**Step 3: Add the approval PATCH endpoint**

Self-lockout guard: reject when an admin tries to un-approve themselves.

```python
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
        await session.commit()

    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    return UserRow(
        id=row.id,
        email=row.email,
        name=row.name,
        is_approved=row.is_approved,
        role=row.role,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )
```

**Step 4: Commit**

```bash
git add backend/app/api/admin.py
git commit -m "feat(admin): add user list + approval endpoints"
```

---

## Task 2: Frontend types + API client [ ]

**Depends on:** Task 1

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`

**Step 1: Add the `UserRow` interface**

Add to `frontend/src/types/api.ts` (place near `LLMModelRow`, ~line 208). Fields MUST match the backend Pydantic model exactly (see Cross-Layer table).

```typescript
export interface UserRow {
  id: number;
  email: string;
  name: string | null;
  is_approved: boolean;
  role: string;
  created_at: string;        // ISO timestamp
  last_seen_at: string | null; // ISO timestamp
}
```

**Step 2: Add API client functions**

Add to `frontend/src/api/client.ts`. Add `UserRow` to the type-import block (lines 1-15). Mirror `getLLMModels` (bare fetch + `handleResponse`) and `updateNotificationPrefs` (JSON-body PATCH) — append after `refreshLLMModels` (line 159).

```typescript
export async function getUsers(): Promise<UserRow[]> {
  const res = await fetch('/api/admin/users');
  return handleResponse<UserRow[]>(res);
}

export async function setUserApproval(userId: number, isApproved: boolean): Promise<UserRow> {
  const res = await fetch(`/api/admin/users/${userId}/approval`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_approved: isApproved }),
  });
  return handleResponse<UserRow>(res);
}
```

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat(admin): add UserRow type + user-approval API client"
```

---

## Task 3: UserApprovalPanel component + ProfilePage wiring [ ]

**Depends on:** Task 2

**Files:**
- Create: `frontend/src/components/UserApprovalPanel.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`

**Reuse check:** Reuses existing conventions — no new shared component extracted.
- Card shell: mirror `NotificationsPanel.tsx:7-13` module-level `cardStyle` + `<section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>`.
- Toggle: mirror the `role="switch"` button at `NotificationsPanel.tsx:144-162` verbatim (same classes/styles), bound per-row to `u.is_approved`.
- Confirm: mirror `DetailPage.tsx:332-337` via `useConfirm()`.
- Fetch/loading/error/empty: mirror `LLMAdminPanel.tsx:84-107, 202-214, 287-293`.

**Behaviors (4 — at the Agent-Context limit, do not add a 5th):**
1. Load user list on mount (cancelled-guard effect).
2. Toggle false→true: optimistic, no confirm.
3. Toggle true→false: `await confirm({ destructive: true })` first; skip if cancelled.
4. Own row (`u.id === user.id`) toggle is `disabled`.

> **Note (forward-compat with Task 5):** the fetch is extracted into a `useCallback`-wrapped `loadUsers` so Task 5's pull-to-refresh `onRefresh` can call the exact same refetch. Keep this shape.

**Step 1: Implement the component**

The panel takes the current admin's id to disable the own-row toggle. Pass `currentUserId` as a prop (ProfilePage already has `user.id`).

```tsx
import { useCallback, useEffect, useState } from 'react';
import type { UserRow } from '../types/api';
import { getUsers, setUserApproval } from '../api/client';
import { useConfirm } from './ConfirmDialog';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

interface Props {
  currentUserId: number;
}

export function UserApprovalPanel({ currentUserId }: Props) {
  const confirm = useConfirm();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Single refetch codepath: used by the mount effect AND by Task 5's
  // pull-to-refresh onRefresh callback. Manages loading + clears prior error so
  // both entry points behave identically (loading indicator shows on PTR too).
  // Resolves so PTR can await it.
  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setRows(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function handleToggle(u: UserRow) {
    const next = !u.is_approved;
    if (!next) {
      const ok = await confirm({
        title: 'Freischaltung entziehen?',
        message: `„${u.email}" verliert den Zugang zur App.`,
        confirmLabel: 'Entziehen',
        destructive: true,
      });
      if (!ok) return;
    }
    // Optimistic update with rollback on failure
    setRows((rs) => rs?.map((r) => (r.id === u.id ? { ...r, is_approved: next } : r)) ?? rs);
    try {
      const updated = await setUserApproval(u.id, next);
      setRows((rs) => rs?.map((r) => (r.id === updated.id ? updated : r)) ?? rs);
    } catch (err: unknown) {
      setRows((rs) => rs?.map((r) => (r.id === u.id ? { ...r, is_approved: u.is_approved } : r)) ?? rs);
      setError(err instanceof Error ? err.message : 'Aktualisierung fehlgeschlagen');
    }
  }

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <p className="text-sm font-semibold mb-4" style={{ color: '#A78BFA' }}>
        Benutzer-Freischaltung
      </p>

      {loading && (
        <p className="text-sm text-center py-6" style={{ color: 'rgba(248,250,252,0.35)' }}>
          Lade Benutzer…
        </p>
      )}

      {!loading && error && (
        <p role="alert" className="text-sm text-center py-6" style={{ color: '#EC4899' }}>
          Fehler: {error}
        </p>
      )}

      {!loading && !error && rows && (
        <ul className="flex flex-col gap-3">
          {rows.map((u) => {
            const isSelf = u.id === currentUserId;
            return (
              <li key={u.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm truncate" style={{ color: 'rgba(248,250,252,0.85)' }}>
                    {u.email}{isSelf ? ' (du)' : ''}
                  </p>
                  {u.name && (
                    <p className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.45)' }}>
                      {u.name}
                    </p>
                  )}
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                    Registriert: {new Date(u.created_at).toLocaleDateString('de-DE')}
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={u.is_approved}
                  aria-label={`Freischaltung für ${u.email}`}
                  disabled={isSelf}
                  onClick={() => { void handleToggle(u); }}
                  className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    background: u.is_approved
                      ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                      : 'rgba(255,255,255,0.1)',
                    border: u.is_approved
                      ? '1px solid rgba(139,92,246,0.5)'
                      : '1px solid rgba(255,255,255,0.15)',
                  }}
                >
                  <span className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
                    style={{
                      background: '#fff',
                      transform: u.is_approved ? 'translateX(18px)' : 'translateX(2px)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                    }}
                    aria-hidden="true" />
                </button>
              </li>
            );
          })}
          {rows.length === 0 && (
            <li className="py-6 text-center text-xs" style={{ color: 'rgba(248,250,252,0.3)' }}>
              Keine Benutzer
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
```

**Step 2: Wire into ProfilePage**

In `frontend/src/pages/ProfilePage.tsx`:
- Add import alongside the existing panel imports (after line 6):
  ```tsx
  import { UserApprovalPanel } from '../components/UserApprovalPanel';
  ```
- Add the panel to the admin-only stack (after line 239, `{user.role === 'admin' && <LLMAdminPanel />}`):
  ```tsx
  {user.role === 'admin' && <UserApprovalPanel currentUserId={user.id} />}
  ```

**Step 3: Commit**

```bash
git add frontend/src/components/UserApprovalPanel.tsx frontend/src/pages/ProfilePage.tsx
git commit -m "feat(admin): add UserApprovalPanel to profile"
```

---

## Task 4: Tests (backend admin endpoints + frontend panel) [IMPLEMENTED backend]

**Depends on:** Task 3

**Files:**
- Modify: `backend/tests/conftest.py` (add `admin_client` fixture)
- Create: `backend/tests/test_admin_users.py`
- Create: `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`

**Step 1: Add the `admin_client` fixture**

Append to `backend/tests/conftest.py`. Mirror `authenticated_client` (lines 330-373) exactly, with two deviations: (a) seed `role = 'admin'`, (b) different `google_id`/`email` to avoid collisions. `require_admin` is satisfied because `_fake_user` reads `role` from the DB and `get_current_user` is overridden, so `require_admin`'s `user.role != "admin"` check passes.

```python
@pytest_asyncio.fixture()
async def admin_client(test_engine, db_session: AsyncSession) -> AsyncGenerator[tuple[AsyncClient, int], None]:
    """AsyncClient authenticated as an admin user (role='admin'). Yields (client, admin_id)."""
    from sqlalchemy import text as _text  # noqa: PLC0415
    from app.api.deps import get_current_user  # noqa: PLC0415
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved, role)
            VALUES ('admin-client-google', 'admin_client@example.com', 'Admin Client', TRUE, 'admin')
            ON CONFLICT (google_id) DO NOTHING
        """)
    )
    await db_session.commit()
    admin_id = (
        await db_session.execute(_text("SELECT id FROM users WHERE google_id = 'admin-client-google'"))
    ).scalar_one()

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _fake_user() -> User:
        async with factory() as session:
            r = await session.execute(
                _text("SELECT id, google_id, email, name, is_approved, role FROM users WHERE id = :uid"),
                {"uid": admin_id},
            )
            row = r.one()
            return User(id=row[0], google_id=row[1], email=row[2], name=row[3], is_approved=row[4], role=row[5])

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, admin_id
    app.dependency_overrides.clear()
```

**Step 2: Backend tests**

Create `backend/tests/test_admin_users.py`. Mirror the async-test style of `test_notifications_api.py` (uses `authenticated_client` / db_session, `pytest.mark.asyncio` via `pytest_asyncio` auto mode). One assertion-focused test per behavior:

```python
"""Tests for admin user-approval endpoints."""
import pytest
from sqlalchemy import text


async def _seed_user(db_session, google_id, email, *, is_approved, role="member"):
    await db_session.execute(
        text("""
            INSERT INTO users (google_id, email, name, is_approved, role)
            VALUES (:g, :e, :n, :a, :r)
        """),
        {"g": google_id, "e": email, "n": None, "a": is_approved, "r": role},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM users WHERE google_id = :g"), {"g": google_id})
    ).scalar_one()


@pytest.mark.asyncio
async def test_list_users_returns_all_pending_first(admin_client, db_session):
    client, _admin_id = admin_client
    await _seed_user(db_session, "u-approved", "approved@example.com", is_approved=True)
    await _seed_user(db_session, "u-pending", "pending@example.com", is_approved=False)

    resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    rows = resp.json()
    emails = [r["email"] for r in rows]
    # Admin (approved) + 2 seeded; pending must come before any approved user
    assert "pending@example.com" in emails
    assert emails.index("pending@example.com") == 0
    # DTO shape
    sample = next(r for r in rows if r["email"] == "pending@example.com")
    assert set(sample) == {"id", "email", "name", "is_approved", "role", "created_at", "last_seen_at"}


@pytest.mark.asyncio
async def test_approve_user_sets_flag(admin_client, db_session):
    client, _admin_id = admin_client
    uid = await _seed_user(db_session, "u-x", "x@example.com", is_approved=False)

    resp = await client.patch(f"/api/admin/users/{uid}/approval", json={"is_approved": True})
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is True

    row = await db_session.execute(text("SELECT is_approved FROM users WHERE id = :id"), {"id": uid})
    assert row.scalar_one() is True


@pytest.mark.asyncio
async def test_revoke_other_user_succeeds(admin_client, db_session):
    client, _admin_id = admin_client
    uid = await _seed_user(db_session, "u-y", "y@example.com", is_approved=True)

    resp = await client.patch(f"/api/admin/users/{uid}/approval", json={"is_approved": False})
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is False


@pytest.mark.asyncio
async def test_admin_cannot_revoke_own_approval(admin_client):
    client, admin_id = admin_client
    resp = await client.patch(f"/api/admin/users/{admin_id}/approval", json={"is_approved": False})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_unknown_user_returns_404(admin_client):
    client, _admin_id = admin_client
    resp = await client.patch("/api/admin/users/999999/approval", json={"is_approved": True})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_forbidden(authenticated_client):
    # authenticated_client authenticates as a member (role defaults to 'member')
    resp = await authenticated_client.get("/api/admin/users")
    assert resp.status_code == 403
```

> Before writing, Read `backend/tests/test_notifications_api.py` top ~30 lines to confirm the `pytest.mark.asyncio` / import header convention and copy it verbatim if it differs from the above.

**Step 3: Frontend tests**

Create `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`. Vitest globals are NOT enabled → import them explicitly. Mock `../../api/client` and `../ConfirmDialog` (mirror `DetailPage.test.tsx:22-25`). One `it(...)` per behavior:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { UserApprovalPanel } from '../UserApprovalPanel';

const getUsers = vi.fn();
const setUserApproval = vi.fn();
const confirmMock = vi.fn();

vi.mock('../../api/client', () => ({
  getUsers: (...a: unknown[]) => getUsers(...a),
  setUserApproval: (...a: unknown[]) => setUserApproval(...a),
}));
vi.mock('../ConfirmDialog', () => ({
  useConfirm: () => confirmMock,
  ConfirmProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const baseRow = {
  id: 2, email: 'pending@example.com', name: null,
  is_approved: false, role: 'member',
  created_at: '2026-05-01T10:00:00Z', last_seen_at: null,
};

describe('UserApprovalPanel', () => {
  beforeEach(() => {
    getUsers.mockReset();
    setUserApproval.mockReset();
    confirmMock.mockReset();
  });

  it('renders the fetched user list', async () => {
    getUsers.mockResolvedValue([baseRow]);
    render(<UserApprovalPanel currentUserId={1} />);
    expect(await screen.findByText('pending@example.com')).toBeInTheDocument();
  });

  it('approves without confirm when toggling false→true', async () => {
    getUsers.mockResolvedValue([baseRow]);
    setUserApproval.mockResolvedValue({ ...baseRow, is_approved: true });
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /pending@example.com/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(setUserApproval).toHaveBeenCalledWith(2, true));
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('asks for confirmation when revoking true→false and skips on cancel', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, is_approved: true }]);
    confirmMock.mockResolvedValue(false);
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /pending@example.com/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(setUserApproval).not.toHaveBeenCalled();
  });

  it('disables the toggle for the current user own row', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, id: 1, email: 'me@example.com' }]);
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /me@example.com/ });
    expect(toggle).toBeDisabled();
  });
});
```

**Step 4: Commit**

```bash
git add backend/tests/conftest.py backend/tests/test_admin_users.py frontend/src/components/__tests__/UserApprovalPanel.test.tsx
git commit -m "test(admin): cover user-approval endpoints + panel"
```

---

## Task 5: Pull-to-refresh for the user list (mobile) [ ]

**Depends on:** Task 4 (sequential, not parallel — Task 5 extends `UserApprovalPanel.test.tsx` which Task 4 creates, and re-wires `UserApprovalPanel.tsx` whose loading/error/list JSX must already be in place). Logically it builds on Task 3's `loadUsers` callback.

**Files:**
- Create: `frontend/src/hooks/usePullToRefresh.ts`
- Create: `frontend/src/hooks/__tests__/usePullToRefresh.test.ts`
- Modify: `frontend/src/components/UserApprovalPanel.tsx`
- Modify: `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`

**Reuse check:** No existing pull-to-refresh / `touchmove` pattern exists (verified by grep, see Context → `frontend/src/hooks/`). The two `onTouchStart`/`onTouchEnd` swipe-to-dismiss callsites (`FilterPanel.tsx:85-91`, `ComparablesModal.tsx:120`) only compare a single end-delta to close a sheet — no live pull distance, no `scrollTop===0` guard, no refreshing state — so they are NOT reusable here. This task introduces a NEW hook convention; the full hook is written out below (Convention Mirror Rule: new convention → write in full). `overscroll-behavior: contain` precedent: `ListingDetailModal.tsx:68`.

**Scope guard:** The gesture is wired ONLY into `UserApprovalPanel` (admin-only card). It does NOT touch the listings page, `useInfiniteListings`, or any global scroll handler. Desktop is unaffected — touch events only, no mouse-drag logic, no desktop refresh button.

**Behaviors (3):**
1. Pull only engages when the scroll container is at the top (`scrollTop === 0`) at `touchstart`; otherwise the gesture is ignored (native scroll wins).
2. While pulling past the threshold (~70px) and releasing, `onRefresh()` is awaited; `refreshing` is `true` for the duration. Pull distance is dampened and exposed as `pullDistance` for a visible indicator.
3. Releasing below the threshold (or never reaching the top) does nothing — no `onRefresh` call, `pullDistance` resets to 0.

**Step 1: Implement the hook**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';

const THRESHOLD = 70;          // px the user must pull before a release triggers refresh
const MAX_PULL = 110;          // px hard cap on the rendered indicator travel
const RESISTANCE = 0.5;        // dampening factor applied to raw finger travel

export interface UsePullToRefreshResult {
  /** Attach to the scrollable container that hosts the list. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Current (dampened, capped) pull distance in px — drive the indicator with this. */
  pullDistance: number;
  /** True while the onRefresh promise is in flight. */
  refreshing: boolean;
}

/**
 * Mobile-only pull-to-refresh for a scrollable container.
 *
 * Touch-only by design (no mouse-drag), so desktop is unaffected. The gesture
 * engages ONLY when the container is scrolled to the very top at touchstart, so
 * it never steals a normal upward scroll. On release past THRESHOLD it awaits
 * onRefresh() and shows a refreshing state until the promise settles.
 */
export function usePullToRefresh(onRefresh: () => Promise<void>): UsePullToRefreshResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const startYRef = useRef<number | null>(null); // non-null only while a valid pull is active
  const pullRef = useRef(0);                      // mirrors pullDistance for the touchend handler
  const refreshingRef = useRef(false);            // mirrors `refreshing` so the touch handlers read it without re-binding
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  // Single source of truth for the refreshing flag: write the ref AND the state
  // together so the touch handlers (which read the ref) and the JSX (which reads
  // state) never diverge. The ref lets onTouchStart see the live value without
  // putting `refreshing` in the effect dep-array (which would churn listeners).
  const setRefreshingBoth = useCallback((value: boolean) => {
    refreshingRef.current = value;
    setRefreshing(value);
  }, []);

  const reset = useCallback(() => {
    startYRef.current = null;
    pullRef.current = 0;
    setPullDistance(0);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (el == null) return;

    const onTouchStart = (e: TouchEvent) => {
      // Engage only when already at the top; otherwise let native scroll run.
      // Read refreshingRef (not the `refreshing` state) so this handler stays
      // valid without re-binding the effect on every refreshing flip.
      if (el.scrollTop <= 0 && !refreshingRef.current) {
        startYRef.current = e.touches[0].clientY;
      } else {
        startYRef.current = null;
      }
    };

    const onTouchMove = (e: TouchEvent) => {
      if (startYRef.current === null) return;
      const raw = e.touches[0].clientY - startYRef.current;
      if (raw <= 0) {
        // Pulling up / no downward travel — abandon, let native scroll resume.
        pullRef.current = 0;
        setPullDistance(0);
        return;
      }
      // Downward pull from the top: dampen, cap, and suppress native overscroll.
      const dist = Math.min(raw * RESISTANCE, MAX_PULL);
      pullRef.current = dist;
      setPullDistance(dist);
      e.preventDefault();
    };

    const onTouchEnd = () => {
      if (startYRef.current === null) return;
      const shouldRefresh = pullRef.current >= THRESHOLD;
      if (shouldRefresh) {
        setRefreshingBoth(true);
        setPullDistance(THRESHOLD); // hold indicator at threshold while refreshing
        startYRef.current = null;
        void onRefresh().finally(() => {
          setRefreshingBoth(false);
          pullRef.current = 0;
          setPullDistance(0);
        });
      } else {
        reset();
      }
    };

    // touchmove must be non-passive so preventDefault() can tame native pull-to-refresh.
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: false });
    el.addEventListener('touchend', onTouchEnd);
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
    };
    // `refreshing` deliberately omitted — read via refreshingRef inside the
    // handlers so the listeners are bound once and never churn.
  }, [onRefresh, reset, setRefreshingBoth]);

  return { containerRef, pullDistance, refreshing };
}
```

**Step 2: Wire into `UserApprovalPanel`**

In `frontend/src/components/UserApprovalPanel.tsx`:

- Extend the React import to include the hook import:
  ```tsx
  import { usePullToRefresh } from '../hooks/usePullToRefresh';
  ```
- Inside the component, after `loadUsers` is defined, wire the gesture to the existing refetch:
  ```tsx
  const { containerRef, pullDistance, refreshing } = usePullToRefresh(loadUsers);
  ```
- Wrap the list in a scrollable container that owns the ref and tames native overscroll, and render an indicator above it. Replace the current `<section>` body so the ref-bearing div hosts the scrollable list (mirror the `overscroll-behavior: contain` precedent at `ListingDetailModal.tsx:68`):
  ```tsx
  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <p className="text-sm font-semibold mb-4" style={{ color: '#A78BFA' }}>
        Benutzer-Freischaltung
      </p>

      {/* Pull-to-refresh indicator (mobile). pullDistance > 0 only on touch devices mid-pull. */}
      {(pullDistance > 0 || refreshing) && (
        <p
          className="text-xs text-center transition-opacity"
          style={{ color: 'rgba(248,250,252,0.45)', height: pullDistance, lineHeight: `${pullDistance}px`, overflow: 'hidden' }}
          aria-live="polite"
        >
          {refreshing ? 'Aktualisiere…' : pullDistance >= 70 ? 'Loslassen zum Aktualisieren' : 'Zum Aktualisieren ziehen'}
        </p>
      )}

      <div
        ref={containerRef}
        className="max-h-[60vh] overflow-y-auto"
        style={{ overscrollBehavior: 'contain', WebkitOverflowScrolling: 'touch' }}
      >
        {loading && ( /* …existing loading <p>… */ )}
        {!loading && error && ( /* …existing error <p>… */ )}
        {!loading && !error && rows && ( /* …existing <ul> list, unchanged… */ )}
      </div>
    </section>
  );
  ```
  Keep the loading / error / list JSX from Task 3 verbatim inside the new `<div>` — only the wrapping container + indicator are added.

**Step 3: Write the hook tests**

Create `frontend/src/hooks/__tests__/usePullToRefresh.test.ts` (`.ts` — the test body uses no JSX). Vitest globals NOT enabled by convention → import explicitly. Use `renderHook` + `act` from `@testing-library/react` (mirror header at `useInfiniteListings.test.tsx:11-12`). Drive the hook through a real DOM element assigned to `containerRef`, dispatching `TouchEvent`s. One `it(...)` per behavior:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePullToRefresh } from '../usePullToRefresh';

// jsdom lacks TouchEvent with touches[]; build a minimal Event carrying clientY.
function touch(type: string, clientY: number): Event {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'touches', { value: [{ clientY }] });
  Object.defineProperty(e, 'changedTouches', { value: [{ clientY }] });
  return e;
}

function makeContainer(scrollTop: number): HTMLDivElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true });
  document.body.appendChild(el);
  return el;
}

describe('usePullToRefresh', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('calls onRefresh when pulled past the threshold from the top', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(0);
    const { result } = renderHook(() => usePullToRefresh(onRefresh));
    act(() => { (result.current.containerRef as { current: HTMLDivElement }).current = el; });
    // Re-render so the effect re-binds listeners to the assigned element:
    // (the plan's executing agent: trigger a re-render via a state-free rerender() call)
    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 300)); // 300 * 0.5 = 150 → capped to MAX_PULL, well past 70
      el.dispatchEvent(touch('touchend', 300));
    });
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  });

  it('does nothing when the container is not at the top (scrollTop > 0)', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(50);
    const { result } = renderHook(() => usePullToRefresh(onRefresh));
    act(() => { (result.current.containerRef as { current: HTMLDivElement }).current = el; });
    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 300));
      el.dispatchEvent(touch('touchend', 300));
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('does nothing when released below the threshold', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(0);
    const { result } = renderHook(() => usePullToRefresh(onRefresh));
    act(() => { (result.current.containerRef as { current: HTMLDivElement }).current = el; });
    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 40)); // 40 * 0.5 = 20 < 70
      el.dispatchEvent(touch('touchend', 40));
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
```

> **Ref-binding caveat for the executing agent:** because the hook binds listeners in a `useEffect` keyed on `containerRef.current`, assigning `containerRef.current` after the first render will not re-run the effect by itself. If a test needs the listeners bound to a freshly-created element, render the hook a second time (`rerender()`) after assigning the ref, or render a tiny harness component that mounts a real `<div ref={containerRef}>` so React assigns the ref before the effect runs. Prefer the harness-component approach if the raw-assignment approach proves flaky — both are acceptable; the assertion (onRefresh called / not called) is what matters.

**Step 4: Extend the panel test — pull triggers refetch**

Add one `it(...)` to `frontend/src/components/__tests__/UserApprovalPanel.test.tsx` proving a pull re-runs `getUsers`. Mirror the existing mock setup in that file (Task 4). Mock the hook so the test can invoke `onRefresh` directly without synthesizing touch events:

```tsx
// Add alongside the existing vi.mock blocks:
let capturedOnRefresh: (() => Promise<void>) | null = null;
vi.mock('../../hooks/usePullToRefresh', () => ({
  usePullToRefresh: (onRefresh: () => Promise<void>) => {
    capturedOnRefresh = onRefresh;
    return { containerRef: { current: null }, pullDistance: 0, refreshing: false };
  },
}));

it('refetches the user list when pull-to-refresh fires', async () => {
  getUsers.mockResolvedValue([baseRow]);
  render(<UserApprovalPanel currentUserId={1} />);
  await screen.findByText('pending@example.com');
  expect(getUsers).toHaveBeenCalledTimes(1);
  await act(async () => { await capturedOnRefresh?.(); });
  expect(getUsers).toHaveBeenCalledTimes(2);
});
```

> Import `act` from `@testing-library/react` in the panel test if not already imported. `capturedOnRefresh` must be the hook arg — the panel passes `loadUsers`, so calling it re-runs `getUsers`.

**Step 5: Commit**

```bash
git add frontend/src/hooks/usePullToRefresh.ts frontend/src/hooks/__tests__/usePullToRefresh.test.ts frontend/src/components/UserApprovalPanel.tsx frontend/src/components/__tests__/UserApprovalPanel.test.tsx
git commit -m "feat(admin): pull-to-refresh for user-approval list (mobile)"
```

---

## Verification

Run after all tasks are `[IMPLEMENTED]` (commands verified against `frontend/package.json` and project `CLAUDE.md`):

**Backend** (DB-backed, no live HTTP — uses test Postgres):
```bash
docker compose run --rm backend pytest tests/test_admin_users.py -q
docker compose run --rm backend pytest tests/ -q
```

**Frontend** (`test` script = `vitest`; `--run` for one-shot; `build` = `tsc -b && vite build` catches type drift):
```bash
cd frontend; npm run test -- --run
cd frontend; npm run build
```

Expected:
- All new backend tests pass; full backend suite stays green.
- All four `UserApprovalPanel` tests + the new "pull triggers refetch" test pass; full frontend suite stays green.
- The three `usePullToRefresh` hook tests pass (refresh past threshold; no-op when not at top; no-op below threshold).
- `npm run build` succeeds (confirms backend↔frontend `UserRow` DTO type alignment).

Manual smoke (optional, single admin): log in as admin → Einstellungen → "Benutzer-Freischaltung" card lists users (pending first), own toggle disabled, approving is instant, revoking shows the confirm dialog. On a touch device: at the top of the list, pull down → indicator appears, releasing past the threshold refetches the list (spinner/"Aktualisiere…" state).

---

## Out of Scope (backlog candidates)

- User deletion.
- Role management (promote/demote member↔admin).
- Pagination / search of the user list (single-user hobby project — list is tiny).

---

_Plan review closed 2026-05-31 (cycle 2): 3 blocking addressed, 7 non-blocking incorporated/dismissed._
