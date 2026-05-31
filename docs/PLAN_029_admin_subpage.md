# Admin Subpage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Move all admin-role-gated panels out of the profile onto a dedicated admin-only `/admin` page, and show a "last seen" date per user in the user list.

**Architecture:** Pure frontend, no backend change — all data/endpoints already exist. New `AdminPage` lives inside the already auth-gated `AuthenticatedAppInner` route block. Non-admins hitting `/admin` are redirected to `/` via `<Navigate to="/" replace />`. `LLMAdminPanel` + `UserApprovalPanel` relocate from `ProfilePage` to `AdminPage`; the profile gains a "Admin-Bereich" link shown only to admins. `UserApprovalPanel` additively displays `last_seen_at`.

**Tech Stack:** React 19, TypeScript, react-router-dom 7, Vite, Tailwind, Vitest.

**Breaking Changes:** No. Purely additive + relocation.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-05-31 |
| Human | approved | 2026-05-31 |

---

## Plan Weight: Thin

Per the writing-plans trigger table: pure frontend, no backend, no migration, ≤ 6 files modified, ≤ 4 tasks, relocation + one new admin-gated route + additive field display. No backend mutation, no new endpoint, no security-relevant server code, no cross-layer DTO change. Thin plan: one plan-review cycle, Codex parallel OFF, automated-checks-only Verification.

---

## Context (verified pre-write scans)

- **Routing** (`frontend/src/App.tsx`):
  - Imports already present (line 1): `import { Routes, Route, Link, Navigate, useNavigate, useLocation } from 'react-router-dom';`
  - `AuthenticatedAppInner({ user, logout, reloadUser })` (line 42) holds the inner `<Routes location={effectiveLocation}>` block (lines 166-184). `user: AuthUser` is in scope. `ProfilePage` is passed `user` here: line 182 `<Route path="/profile" element={<ProfilePage user={user} onLogout={logout} onUserReload={reloadUser} />} />`.
  - The new `/admin` route goes in this same `<Routes>` block (alongside lines 181-183).
- **ProfilePage** (`frontend/src/pages/ProfilePage.tsx`):
  - `Props` (line 15): `{ user: AuthUser; onLogout: () => void; onUserReload: () => void }`. Signature destructures only `{ user, onLogout }` (line 26).
  - Admin panels rendered at lines 241-242, both behind `user.role === 'admin'`:
    `{user.role === 'admin' && <LLMAdminPanel />}` / `{user.role === 'admin' && <UserApprovalPanel currentUserId={user.id} />}`
  - Settings stack container: `<div className="flex flex-col gap-4 sm:gap-6 min-w-0">` (line 239), currently holding `<NotificationsPanel />` + the two admin panels.
  - Logout button style to mirror (lines 208-227): `type="button"`, full-width, `className="w-full rounded-xl py-2.5 text-sm font-medium transition-all duration-150"`, inline `style` background `rgba(167, 139, 250, 0.08)`, border `1px solid rgba(167, 139, 250, 0.35)`, color `#A78BFA`, with `onPointerEnter`/`onPointerLeave` hover swap to `rgba(167, 139, 250, 0.16)`.
  - `cardStyle` object defined locally (lines 77-83) — reuse pattern for AdminPage shell.
- **UserApprovalPanel** (`frontend/src/components/UserApprovalPanel.tsx`):
  - Props: `{ currentUserId: number }` (line 15). Takes `currentUserId` — unchanged on relocation.
  - Per-row block lines 109-122; the existing "Registriert" line (lines 119-121) already uses an inline date format: `new Date(u.created_at).toLocaleDateString('de-DE')`. Insert the last-seen line directly after it.
- **LLMAdminPanel** (`frontend/src/components/LLMAdminPanel.tsx`): exported as `export function LLMAdminPanel()` — **takes no props**. Pure relocation, no prop wiring.
- **Type** (`frontend/src/types/api.ts:210-218`): `UserRow.last_seen_at: string | null;` confirmed (line 217).
- **Date helper** (`frontend/src/utils/format.ts:17-24`): `formatDate(iso: string | null): string` — returns `'–'` for null, else `toLocaleDateString('de-DE', { day:'2-digit', month:'2-digit', year:'numeric' })`. **Reuse this** for last_seen; it already handles the null case ("–"). No new helper needed.
- **Page structure vorlage**: `FavoritesPage.tsx` (flat page, no back-nav) and `ProfilePage.tsx` (`max-w-*` container + `cardStyle` glass cards + `h1` heading hidden on mobile). AdminPage mirrors ProfilePage's outer container + heading + card stack. Neither existing page has a back button; AdminPage gets reached/left via profile link + browser nav, so no back button required (matches existing convention).
- **Tests**:
  - `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`: `baseRow` (line 26-30) already includes `last_seen_at: null`. Adding the last_seen display does not break it; we extend it with a new assertion.
  - `frontend/src/__tests__/ModalRouting.test.tsx`: mocks `useAuth` with `role: 'member'` (line 38-43) and renders full `App`. Adding the `/admin` route does **not** break it (member never routes there; redirect is inert at `/`). No change needed.
  - **No `ProfilePage` test exists** — nothing to repair there; the new test in Task 4 is greenfield.
- **Test conventions**: co-located `__tests__/`, Vitest globals imported **explicitly** (`import { describe, it, expect, vi } from 'vitest'`). Router-dependent components render under `MemoryRouter` (see ModalRouting test). `vi.mock('../../api/client', …)` + `vi.mock('../ConfirmDialog', …)` + `vi.mock('../../hooks/usePullToRefresh', …)` pattern at `UserApprovalPanel.test.tsx:9-24`.
- **Scripts** (`frontend/package.json`): `test` = `vitest`, `build` = `tsc -b && vite build`. No standalone `test --run` script; invoke `vitest run` via `npm test -- --run`.

---

### Task 1: AdminPage + `/admin` route with admin guard [IMPLEMENTED]

**Files:**
- Create: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/App.tsx` (add import + route in the `AuthenticatedAppInner` `<Routes>` block near lines 181-183)

**Reuse check:** Reuses `LLMAdminPanel` (`frontend/src/components/LLMAdminPanel.tsx`, no props) and `UserApprovalPanel` (`frontend/src/components/UserApprovalPanel.tsx`, `currentUserId: number`). Mirrors page-shell convention from `ProfilePage.tsx` (`max-w-*` container, `h1` heading hidden on mobile, glass `cardStyle` card stack). No new shared component — AdminPage is a leaf page.

**Step 1: Create `AdminPage.tsx`**

Mirror the ProfilePage outer container + heading + settings-stack idiom. Guard: non-admins get `<Navigate to="/" replace />`. `AuthUser` type from `../hooks/useAuth`.

```tsx
import { Navigate } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { LLMAdminPanel } from '../components/LLMAdminPanel';
import { UserApprovalPanel } from '../components/UserApprovalPanel';

interface Props {
  user: AuthUser;
}

export function AdminPage({ user }: Props) {
  // Admin-only: members and unauthenticated-but-approved users are redirected home.
  if (user.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-8 pb-12"
      style={{ color: '#F8FAFC' }}
    >
      {/* Page heading — hidden on mobile (bottom nav already indicates context) */}
      <h1 className="hidden sm:block text-2xl font-bold mb-8" style={{ color: '#F8FAFC' }}>
        Admin-Bereich
      </h1>

      <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
        <LLMAdminPanel />
        <UserApprovalPanel currentUserId={user.id} />
      </div>
    </div>
  );
}
```

**Step 2: Wire the route in `App.tsx`**

Add the import next to the other page imports (after line 9 `import { FavoritesPage } from './pages/FavoritesPage';`):

```tsx
import { AdminPage } from './pages/AdminPage';
```

Add the route inside the `<Routes location={effectiveLocation}>` block, directly after the `/profile` route (line 182):

```tsx
<Route path="/admin" element={<AdminPage user={user} />} />
```

**Step 3: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx frontend/src/App.tsx
git commit -m "feat: add admin-only /admin page hosting admin panels"
```

---

### Task 2: Relocate panels out of ProfilePage + add admin link [IMPLEMENTED]

**Depends on:** Task 1

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx` (remove panel renders + imports at lines 6, 8, 241-242; add admin link)

**Reuse check:** No new component. "Admin-Bereich" link mirrors the existing Logout button style at `ProfilePage.tsx:208-227` (`type="button"`, full-width, same glass background/border/color + pointer hover swap). Navigation via `<Link to="/admin">` from react-router-dom — but to keep the mirrored button styling and `type="button"` semantics, use `useNavigate()` inside the button's `onClick` rather than wrapping in a Link.

**Step 1: Remove relocated imports**

Delete the now-unused imports:
- Line 6: `import { LLMAdminPanel } from '../components/LLMAdminPanel';`
- Line 8: `import { UserApprovalPanel } from '../components/UserApprovalPanel';`

(`NotificationsPanel` import on line 7 stays.)

**Step 2: Add `useNavigate` import**

Add at the top of the file (react-router-dom):

```tsx
import { useNavigate } from 'react-router-dom';
```

**Step 3: Remove the two admin panels from the settings stack**

In the settings-stack `<div>` (lines 239-243), delete lines 241-242:

```tsx
{user.role === 'admin' && <LLMAdminPanel />}
{user.role === 'admin' && <UserApprovalPanel currentUserId={user.id} />}
```

The stack now holds only `<NotificationsPanel />`.

**Step 4: Add `navigate` in the component body**

At the top of `ProfilePage`'s body (e.g. right after line 26 `export function ProfilePage({ user, onLogout }: Props) {`):

```tsx
const navigate = useNavigate();
```

**Step 5: Add the "Admin-Bereich" button**

Place it in the profile card (column 1), directly above the Logout button (before line 208), admin-only. Mirror the Logout button's full-width glass style; add `mb-3` to separate it from the Logout button below.

```tsx
{user.role === 'admin' && (
  <button
    type="button"
    onClick={() => navigate('/admin')}
    className="w-full rounded-xl py-2.5 mb-3 text-sm font-medium transition-all duration-150"
    style={{
      background: 'rgba(167, 139, 250, 0.08)',
      border: '1px solid rgba(167, 139, 250, 0.35)',
      color: '#A78BFA',
    }}
    onPointerEnter={(e) => {
      (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167, 139, 250, 0.16)';
    }}
    onPointerLeave={(e) => {
      (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167, 139, 250, 0.08)';
    }}
  >
    Admin-Bereich
  </button>
)}
```

**Step 6: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "refactor: move admin panels to /admin, add admin link in profile"
```

---

### Task 3: Show "last seen" in UserApprovalPanel [IMPLEMENTED]

**Depends on:** Task 1 (relocation does not block this, but keeps commits ordered)

**Files:**
- Modify: `frontend/src/components/UserApprovalPanel.tsx` (add import + one line per row)

**Reuse check:** Reuses `formatDate` from `frontend/src/utils/format.ts:17-24` — already returns `'–'` for null. No inline date logic, no new helper.

**Step 1: Import the helper**

Add after the existing imports (top of file):

```tsx
import { formatDate } from '../utils/format';
```

**Step 2: Add the last-seen line per row**

Directly after the existing "Registriert" line (currently `UserApprovalPanel.tsx:119-121`), add a sibling line. `formatDate(null)` yields `–`, satisfying the "nie/—" requirement:

```tsx
<p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
  Zuletzt gesehen: {formatDate(u.last_seen_at)}
</p>
```

**Step 3: Commit**

```bash
git add frontend/src/components/UserApprovalPanel.tsx
git commit -m "feat: show last-seen date in user approval list"
```

---

### Task 4: Tests [IMPLEMENTED]

**Depends on:** Task 1, Task 2, Task 3

**Files:**
- Create: `frontend/src/pages/__tests__/AdminPage.test.tsx`
- Create: `frontend/src/pages/__tests__/ProfilePage.test.tsx`
- Modify: `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`

**Reuse check:** Mirror Vitest setup conventions: globals imported explicitly; render router-dependent pages under `MemoryRouter`; mirror the `vi.mock('../../api/client', …)` + `vi.mock('../ConfirmDialog', …)` + `vi.mock('../../hooks/usePullToRefresh', …)` shape at `UserApprovalPanel.test.tsx:9-24`. AdminPage hosts `LLMAdminPanel` + `UserApprovalPanel`, both of which fetch via `../api/client` — mock the client module to avoid live calls.

**Step 1: AdminPage test**

`AdminPage.test.tsx`. Mock `../../api/client` (both panels' fetchers: `getLLMModels`, `getUsers` — return resolved empties) and `../../components/ConfirmDialog` (UserApprovalPanel's `useConfirm`). Render under `MemoryRouter`.

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AdminPage } from '../AdminPage';
import type { AuthUser } from '../../hooks/useAuth';

vi.mock('../../api/client', () => ({
  getLLMModels: vi.fn().mockResolvedValue([]),
  refreshLLMModels: vi.fn().mockResolvedValue([]),
  getUsers: vi.fn().mockResolvedValue([]),
  setUserApproval: vi.fn(),
}));
vi.mock('../../components/ConfirmDialog', () => ({
  useConfirm: () => vi.fn(),
  ConfirmProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('../../hooks/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ containerRef: { current: null }, pullDistance: 0, refreshing: false }),
}));

const adminUser: AuthUser = { id: 1, email: 'admin@example.com', name: 'A', role: 'admin' };
const memberUser: AuthUser = { id: 2, email: 'member@example.com', name: 'M', role: 'member' };

describe('AdminPage', () => {
  it('renders admin panels for an admin user', async () => {
    render(<MemoryRouter><AdminPage user={adminUser} /></MemoryRouter>);
    expect(await screen.findByText('Benutzer-Freischaltung')).toBeInTheDocument();
  });

  it('redirects a non-admin user to home', () => {
    render(
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route path="/admin" element={<AdminPage user={memberUser} />} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('HOME')).toBeInTheDocument();
  });
});
```

(Confirm the exact `AuthUser` shape from `frontend/src/hooks/useAuth.ts` before finalizing the literal — adjust fields if it differs from `{ id, email, name, role }`.)

**Step 2: ProfilePage test**

`ProfilePage.test.tsx`. Greenfield. Mock `../../api/client` (ProfilePage imports `resolvePlz`) and `../../components/NotificationsPanel` (avoid its fetches). Render under `MemoryRouter`.

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProfilePage } from '../ProfilePage';
import type { AuthUser } from '../../hooks/useAuth';

vi.mock('../../api/client', () => ({
  resolvePlz: vi.fn().mockResolvedValue({ plz: '12345', city: 'Berlin', lat: 52.5, lon: 13.4 }),
}));
vi.mock('../../components/NotificationsPanel', () => ({
  NotificationsPanel: () => <div>NotificationsPanel</div>,
}));

const noop = () => {};
const adminUser: AuthUser = { id: 1, email: 'admin@example.com', name: 'A', role: 'admin' };
const memberUser: AuthUser = { id: 2, email: 'member@example.com', name: 'M', role: 'member' };

function renderProfile(user: AuthUser) {
  return render(
    <MemoryRouter>
      <ProfilePage user={user} onLogout={noop} onUserReload={noop} />
    </MemoryRouter>,
  );
}

describe('ProfilePage', () => {
  it('shows the Admin-Bereich button for an admin', () => {
    renderProfile(adminUser);
    expect(screen.getByRole('button', { name: 'Admin-Bereich' })).toBeInTheDocument();
  });

  it('hides the Admin-Bereich button for a non-admin', () => {
    renderProfile(memberUser);
    expect(screen.queryByRole('button', { name: 'Admin-Bereich' })).not.toBeInTheDocument();
  });

  it('no longer renders the admin panels inline', () => {
    renderProfile(adminUser);
    expect(screen.queryByText('Benutzer-Freischaltung')).not.toBeInTheDocument();
  });
});
```

**Step 3: Extend UserApprovalPanel test for last-seen**

Add to the existing `describe('UserApprovalPanel', …)` block in `UserApprovalPanel.test.tsx`. `baseRow` already has `last_seen_at: null`.

```tsx
it('shows "–" for last-seen when last_seen_at is null', async () => {
  getUsers.mockResolvedValue([baseRow]);
  render(<UserApprovalPanel currentUserId={1} />);
  await screen.findByText('pending@example.com');
  expect(screen.getByText(/Zuletzt gesehen:\s*–/)).toBeInTheDocument();
});

it('shows a formatted date for last-seen when present', async () => {
  getUsers.mockResolvedValue([{ ...baseRow, last_seen_at: '2026-05-20T08:00:00Z' }]);
  render(<UserApprovalPanel currentUserId={1} />);
  await screen.findByText('pending@example.com');
  expect(screen.getByText(/Zuletzt gesehen:\s*20\.05\.2026/)).toBeInTheDocument();
});
```

**Step 4: Commit**

```bash
git add frontend/src/pages/__tests__/AdminPage.test.tsx frontend/src/pages/__tests__/ProfilePage.test.tsx frontend/src/components/__tests__/UserApprovalPanel.test.tsx
git commit -m "test: cover admin page guard, profile relocation, last-seen display"
```

---

_Code review closed 2026-05-31 (frontend, cycle 1): CLEAN — 0 blocking; 1 low (pre-existing dead `onUserReload` prop) → backlog._

## Verification

Automated checks only (thin plan; no manual E2E — change is intra-frontend, no cross-state flow).

Frontend (primary focus):

```bash
cd frontend
npm test -- --run
npm run build
```

- `npm test -- --run` runs the full Vitest suite once. Expect: new AdminPage (2) + ProfilePage (3) + extended UserApprovalPanel (2 new) tests pass; existing `ModalRouting.test.tsx` and `LLMAdminPanel.test.tsx` remain green (no changes touch them).
- `npm run build` (`tsc -b && vite build`) confirms no type errors from the relocated imports / new page / `AuthUser` literals.

Backend (for completeness — no backend change in this plan; run only if a full-repo gate is desired):

```bash
docker compose exec backend pytest tests/ -v
```

---

_Plan review closed 2026-05-31 (thin, cycle 1): APPROVED — 0 blocking, 4 non-blocking (cosmetic/informational, no iteration). Executor note: place the "Admin-Bereich" button above Logout using the existing `borderTop` divider pattern, not bare `mb-3`._
