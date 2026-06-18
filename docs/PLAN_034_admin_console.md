# Standalone Admin Console ("RC-Scout Ops") Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Extract the entire PWA `/admin` area (metrics, LLM cascade, user approval) into a standalone, desktop-first Vite/React app on its own subdomain (`admin.rcn-scout.d2x-labs.de`), running against the same backend, styled 1:1 per `docs/admin_console_styleguide.md` (Coinza dark dashboard).

**Architecture:** New top-level `admin/` Vite app with its own nginx that proxies `/api` to the existing backend container (same-origin → no CORS). Reuses the existing Google-OAuth/session-cookie flow with a single new mechanism: a session **cookie domain** so the cookie is valid across `rcn-scout.d2x-labs.de` and its `admin.` subdomain, plus a validated **post-login return target** so login initiated from the admin app returns there. The PWA loses `/admin` + `/admin/users` entirely (breaking change). UI built on shadcn/ui (Radix + Tailwind) + Recharts + lucide-react — **not Mantine**. Auth + API access live behind a thin adapter (`useAuth` hook + `api/client.ts`) so the same shell can later be copied to the ToDoList project.

**Tech Stack:** React 19, Vite 8, TypeScript, Tailwind CSS 3, shadcn/ui, Recharts, lucide-react, @fontsource/inter; nginx (alpine) static + `/api` proxy; FastAPI backend (auth changes); Traefik (subdomain router); GitHub Actions (third image).

**Breaking Changes:** **Yes.**
1. PWA `/admin` and `/admin/users` routes are **removed**. Anyone navigating there in the user-facing app hits the SPA fallback → listings. No redirect/migration code. Admin functions live only on the new subdomain.
2. The session cookie gains a `domain` attribute in prod (`COOKIE_DOMAIN=.rcn-scout.d2x-labs.de`). On first deploy, existing PWA sessions (host-only cookie) are **invalidated once** — users (the single operator) re-login via Google. Recovery: just log in again.
3. New subdomain requires a **DNS A-record** `admin.rcn-scout.d2x-labs.de` → VPS IP (ops prerequisite, see Task 8).

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-06-18 |
| Human | approved | 2026-06-18 |

---

## Context (verified signatures)

**Backend auth — `backend/app/api/auth.py`:**
- `GET /api/auth/google` (`auth.py:24`) → builds Google consent redirect; sets `oauth_state` cookie (`set_cookie` `auth.py:37-41`, `httponly, max_age=300, samesite="lax", secure=settings.COOKIE_SECURE`); `redirect_uri = f"{settings.PUBLIC_BASE_URL}/api/auth/google/callback"` (`auth.py:30`).
- `GET /api/auth/google/callback` (`auth.py:45`) → validates `oauth_state`, exchanges code, upserts user, on not-approved redirects `f"{settings.FRONTEND_URL}/login?error=not_approved&email=..."` (`auth.py:115`), on success sets `session` cookie (`auth.py:130-136`, same flags, `max_age=JWT_EXPIRE_DAYS*86400`) and redirects to `settings.FRONTEND_URL` (`auth.py:128`). Denied/error paths redirect to `f"{settings.FRONTEND_URL}/login?error=denied"`.
- `GET /api/auth/me` (`auth.py:140`) → returns `{id, email, name, role}`; updates `last_seen_at`.
- `POST /api/auth/logout` (`auth.py:159`) → `response.delete_cookie("session")`.
- `create_jwt(user_id)` — `backend/app/security.py:9`.
- `get_current_user` reads `request.cookies.get("session")` — `backend/app/api/deps.py:16`; `require_admin` raises 403 if `user.role != "admin"` — `deps.py:32`.

**Backend config — `backend/app/config.py:29`** (`Settings`): `PUBLIC_BASE_URL` (`:45`), `FRONTEND_URL` (`:46`), `ALLOWED_ORIGINS` (`:47`), `COOKIE_SECURE` (`:48`), `JWT_EXPIRE_DAYS` (`:44`). `allowed_origins_list` property `:102`.

**Admin endpoints (all live, mounted under `/api`, admin-gated):** `GET /api/admin/metrics/summary`, `GET /api/admin/metrics/timeseries?days=`, `GET /api/admin/llm-models`, `POST /api/admin/llm-models/refresh`, `GET /api/admin/users`, `PATCH /api/admin/users/{id}/approval` (body `{is_approved}`), `DELETE /api/admin/users/{id}`, `GET /api/admin/users/{id}/stats`. Verified in `frontend/src/api/client.ts:155-218`. Router registration: `routes.py:28-29` (`router = APIRouter(prefix="/api")`; `router.include_router(admin_router)`), mounted `main.py:210`. **No backend endpoint changes needed — admin app calls the same routes.**

**Response/DTO shapes (port verbatim into admin app):** `MetricsSummary`, `TimeseriesPoint`, `MetricsTimeseries`, `LLMModelRow`, `UserRow`, `UserStats` — `frontend/src/types/api.ts:196-296`. `ApiError` class `:143`.

**PWA components to relocate (port + re-theme) then delete from PWA:**
- `frontend/src/pages/AdminPage.tsx`, `frontend/src/pages/AdminUsersPage.tsx`
- `frontend/src/components/MetricsPanel.tsx` (KPI tiles + 5× `MiniChart`)
- `frontend/src/components/LLMAdminPanel.tsx` (cascade table; helpers `isCurrentlyDisabled`, `formatCountdown`, `latestRefreshAt`, `ActiveBadge`)
- `frontend/src/components/UserApprovalPanel.tsx` (approval toggle + delete + stats; deps: `ConfirmDialog` `useConfirm`, `usePullToRefresh`, `UserStatsDialog`, `utils/format.formatDate`)
- `frontend/src/components/MiniChart.tsx` (replaced by Recharts in the console)
- Tests: `frontend/src/pages/__tests__/AdminPage.test.tsx`, `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`

**PWA wiring — `frontend/src/App.tsx`:** imports `AdminPage` (`:10`), `AdminUsersPage` (`:11`); routes `:186-187`. `useAuth` (`frontend/src/hooks/useAuth.ts`) → `AuthUser {id,email,name,role:'member'|'admin'}`, fetches `/api/auth/me`, `logout` POSTs `/api/auth/logout`.

**Deployment — `docker-compose.prod.yml`:** services `db`, `backend` (env incl. `PUBLIC_BASE_URL/FRONTEND_URL/ALLOWED_ORIGINS/COOKIE_SECURE`), `nginx` (built from `frontend/`, Traefik router `rcn-scout` Host rule `:49`, network `web` external). CI `.github/workflows/deploy.yml` builds backend (`./backend/Dockerfile.prod`) + nginx (`./frontend/Dockerfile`) → ghcr, deploys on `release: published` via `docker compose pull nginx backend && up -d`.

**Reference files for scaffolding (mirror, do not invent):** `frontend/vite.config.ts`, `frontend/tailwind.config.js`, `frontend/nginx.conf`, `frontend/Dockerfile`, `frontend/tsconfig*.json`, `frontend/postcss.config.js`, `frontend/eslint.config.js`, `frontend/src/test-setup.ts`.

**Design source of truth:** `docs/admin_console_styleguide.md` (all color/geometry/spacing/typography tokens + component specs + panel mapping). Every UI task references it.

---

## Dependency Approval Gate

The admin app introduces these npm packages (Human must approve before `npm ci`/install runs — Hard Rule 9):

| Package | Purpose |
|---|---|
| `recharts` | Area/line/bar charts + sparklines |
| `lucide-react` | Icon set (matches reference) |
| `@fontsource/inter` | Self-hosted Inter font |
| `tailwindcss-animate` | shadcn/ui animation utilities |
| `class-variance-authority`, `clsx`, `tailwind-merge` | shadcn/ui `cn()` helper + variants |
| `@radix-ui/react-*` (dialog, dropdown-menu, avatar, tooltip, slot) | pulled in per shadcn component |

shadcn/ui components are **copied into the repo** (`admin/src/components/ui/`), not a runtime dependency. **Not Mantine.**

---

## Task 1: Scaffold `admin/` Vite app + theme + serving [DONE]

**Files:**
- Create: `admin/package.json`, `admin/vite.config.ts`, `admin/tsconfig.json`, `admin/tsconfig.app.json`, `admin/tsconfig.node.json`, `admin/postcss.config.js`, `admin/eslint.config.js`, `admin/tailwind.config.js`, `admin/index.html`, `admin/nginx.conf`, `admin/Dockerfile`, `admin/.dockerignore`
- Create: `admin/src/main.tsx`, `admin/src/index.css`, `admin/src/lib/utils.ts`, `admin/src/test-setup.ts`

**Step 1: package.json** — mirror `frontend/package.json` scripts (`dev/build/lint/preview/test`), React 19 + react-router-dom 7 + vite 8 + vitest 4 + tailwind 3 toolchain. **Deviations from frontend:** no `workbox-*`/`vite-plugin-pwa` (admin is not a PWA); add the Dependency-Approval-Gate packages. Set `"name": "admin"`, `"version": "0.1.0"`.

**Step 2: vite.config.ts** — mirror `frontend/vite.config.ts` **except**: remove the entire `VitePWA(...)` plugin (keep only `react()`); keep the `server.proxy['/api']` block (dev proxy to backend) with `target: process.env.API_PROXY_TARGET ?? 'http://localhost:8002'`; change dev server `port` to `4300`; keep `test: { globals: true, environment: 'jsdom', setupFiles: ['./src/test-setup.ts'] }`. Add path alias `@` → `/src` (shadcn convention).

**Step 3: tsconfig*.json, postcss.config.js, eslint.config.js, test-setup.ts** — copy from `frontend/` verbatim; add `paths: { "@/*": ["./src/*"] }` to `tsconfig.app.json` `compilerOptions`.

**Step 4: tailwind.config.js** — define the styleguide tokens as the theme. Use CSS-variable-backed semantic colors (shadcn pattern). Full base:

```js
import tailwindcssAnimate from 'tailwindcss-animate';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        // Surfaces (docs/admin_console_styleguide.md → Color Tokens)
        'bg-app': '#0D0D0D',
        'bg-sidebar': '#0A0A0A',
        surface: '#161616',
        'surface-2': '#1C1C1C',
        'surface-active': '#242424',
        border: '#262626',
        // Text
        'text-primary': '#FAFAFA',
        'text-secondary': '#A1A1AA',
        'text-tertiary': '#6B6B70',
        // Accents
        primary: '#2E6BFF',
        success: '#3FD984',
        danger: '#F75555',
        warning: '#F5B544',
      },
      borderRadius: { shell: '24px', card: '16px', control: '12px', pill: '8px', icon: '10px' },
    },
  },
  plugins: [tailwindcssAnimate],
};
```

(ESM only — `frontend/postcss.config.js` and the project are `"type": "module"`; never `require()` here.)

**Step 5: index.css** — `@tailwind base/components/utilities`; `@import '@fontsource/inter/...'` weights 400/500/600/700; set `body { @apply bg-bg-app text-text-primary font-sans; }`; add `*` `tabular-nums` only on a `.tnum` utility (apply per-number, not globally). Mirror nothing from PWA `index.css` (different design).

**Step 6: nginx.conf** — copy `frontend/nginx.conf` verbatim **except** remove the `location = /sw.js` block (no service worker). Keep security headers, `/health` and `/api/` proxy to `http://backend:8000`, `/index.html` no-cache, SPA fallback.

**Step 7: Dockerfile + .dockerignore** — copy `frontend/Dockerfile` verbatim (node:22-alpine build → nginx:alpine serve). `.dockerignore`: `node_modules`, `dist`.

**Step 8: main.tsx, index.html, lib/utils.ts** — `index.html` title "RC-Scout Ops", root div, mount `src/main.tsx`. `main.tsx`: `createRoot` rendering `<BrowserRouter><App/></BrowserRouter>` (App created in Task 2). `lib/utils.ts`: shadcn `cn()` helper:

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

**Step 9: Commit**

```bash
git add admin/
git commit -m "feat(admin): scaffold standalone admin console app (PLAN-034)"
```

---

## Task 2: Auth adapter, API client, login screen, role gate [DONE]

**Depends on:** Task 1

**Reuse check:** No existing pattern in `admin/`. Auth model mirrors `frontend/src/hooks/useAuth.ts`; API client mirrors `frontend/src/api/client.ts` (admin subset only).

**Files:**
- Create: `admin/src/hooks/useAuth.ts`, `admin/src/types/api.ts`, `admin/src/api/client.ts`
- Create: `admin/src/pages/LoginPage.tsx`, `admin/src/routes/RequireAdmin.tsx`, `admin/src/App.tsx`
- Test: `admin/src/routes/__tests__/RequireAdmin.test.tsx`

**Step 1: types/api.ts** — copy only the admin-relevant interfaces from `frontend/src/types/api.ts:196-296` + `ApiError` (`:143-150`): `LLMModelRow`, `UserRow`, `UserStats`, `MetricsSummary`, `TimeseriesPoint`, `MetricsTimeseries`, plus `AuthUser` (from useAuth). Identical shape; mirror as-is.

**Step 2: api/client.ts** — mirror the `handleResponse<T>` helper from `frontend/src/api/client.ts:22-34` verbatim. Include only these functions (copy verbatim from `client.ts:155-218`): `getLLMModels`, `refreshLLMModels`, `getUsers`, `setUserApproval`, `deleteUser`, `getUserStats`, `getMetricsSummary`, `getMetricsTimeseries`. All hit the same `/api/admin/*` paths (proxied same-origin).

**Step 3: hooks/useAuth.ts** — mirror `frontend/src/hooks/useAuth.ts` verbatim (fetch `/api/auth/me`, `logout` POSTs `/api/auth/logout` then `window.location.href = '/login'`, `reloadUser`). **Deviation:** `AuthUser.role` union unchanged (`'member' | 'admin'`).

**Step 4: routes/RequireAdmin.tsx** — guard: while `loading` (or while no `user` and the login redirect is in flight) show a centered "Lade…" placeholder; the redirect to Google login (`/api/auth/google?return_to=<admin origin>`) fires from a `useEffect` (never during render — Strict-Mode safe); if `user.role !== 'admin'` → render a "Kein Zugriff" full-screen panel (no app access for members); else render `children`.

```tsx
import { useEffect, type ReactNode } from 'react';
import { useAuth } from '../hooks/useAuth';

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  // Redirect to Google login as a side-effect, never during render (Strict-Mode safe).
  useEffect(() => {
    if (!loading && !user) {
      window.location.href = '/api/auth/google?return_to=' + encodeURIComponent(window.location.origin);
    }
  }, [loading, user]);
  if (loading || !user) {
    return <div className="min-h-dvh grid place-items-center text-text-tertiary">Lade…</div>;
  }
  if (user.role !== 'admin') {
    return (
      <div className="min-h-dvh grid place-items-center p-6 text-center">
        <div>
          <p className="text-lg font-semibold text-text-primary">Kein Zugriff</p>
          <p className="mt-2 text-sm text-text-secondary">Dieser Bereich ist Administratoren vorbehalten.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
```

**Step 5: pages/LoginPage.tsx** — minimal centered card (styleguide surface tokens) with a "Mit Google anmelden" button → `window.location.href = '/api/auth/google?return_to=' + encodeURIComponent(window.location.origin)`. Reads `?error=` query (`denied`, `not_approved`) and shows the matching German message (mirror copy from `frontend/src/pages/LoginPage.tsx` if present — verify and reuse its wording).

**Step 6: App.tsx** — routes: `/login` → `LoginPage`; `/*` → `<RequireAdmin><AppShell/></RequireAdmin>` (AppShell stub for now, real in Task 3). Export default `App`.

**Step 7: Write tests** — `RequireAdmin.test.tsx` (mock `useAuth`):
- `it('shows loader while auth is loading')`
- `it('renders children for an admin user')`
- `it('renders "Kein Zugriff" for a member user')`
(The unauthenticated branch sets `window.location` — assert children/loader not rendered; do not assert on navigation side-effect.)

**Step 8: Commit**

```bash
git add admin/src/hooks admin/src/types admin/src/api admin/src/pages/LoginPage.tsx admin/src/routes admin/src/App.tsx
git commit -m "feat(admin): auth adapter, api client, login + admin role gate (PLAN-034)"
```

---

## Task 3: App shell — sidebar + top bar layout [DONE]

**Depends on:** Task 2

**Reuse check:** Extracts new `AppShell` + `Sidebar` + `TopBar`. No prior pattern (new app). shadcn primitives (`Avatar`, `Button`) added here.

**Files:**
- Create (shadcn copy-in): `admin/src/components/ui/button.tsx`, `admin/src/components/ui/avatar.tsx`, `admin/src/components/ui/card.tsx`, `admin/components.json`
- Create: `admin/src/components/AppShell.tsx`, `admin/src/components/Sidebar.tsx`, `admin/src/components/TopBar.tsx`
- Modify: `admin/src/App.tsx` (wire shell + nested routes for the three views as stubs)

**Step 1: shadcn init + primitives** — add `admin/components.json` (style "new-york", base color "neutral", css vars, alias `@/components`, `@/lib/utils`). Copy `button.tsx`, `avatar.tsx`, `card.tsx` from shadcn (standard generated source). These read the Tailwind tokens from Task 1.

**Step 2: Sidebar.tsx** — per styleguide "Sidebar" + "Panel Mapping": fixed `w-[240px]`, `bg-bg-sidebar`, full `min-h-dvh`. Top: brand row (gradient diamond `#4F7BFF→#8B5CF6` + "RC-Scout Ops"). Grouped nav under uppercase `text-tertiary` section labels: **ALLGEMEIN** → Übersicht (`/`), Metriken (`/metrics`), LLM-Kaskade (`/llm`), Nutzer (`/users`); **SYSTEM** → (Abmelden action). Nav item: lucide icon (18px) + label, `h-10`, `rounded-control`; active (via `useLocation`) → `bg-surface-active` + `text-text-primary`, else `text-text-secondary hover:bg-surface-2`. Bottom: profile card (`Avatar` + name + email) on `surface`. Desktop ≥`lg` always visible; below `lg` it is a slide-in drawer toggled from TopBar (state lifted to `AppShell`). Icons: `LayoutDashboard`, `BarChart3`, `Cpu`, `Users`, `LogOut`, `Menu`.

**Step 3: TopBar.tsx** — breadcrumb (tertiary) + page title (24px/600) on the left (title passed as prop per route); right cluster: circular icon buttons (`Bell`, `Info`) on `surface`; on `<lg` a `Menu` button that opens the sidebar drawer. (Search/⌘K from the reference is **out of scope** — note in `docs/backlog.md`.)

**Step 4: AppShell.tsx** — flex layout: `Sidebar` + main column (`TopBar` + `<main className="p-6"><Outlet/></main>`), `bg-bg-app`. Holds drawer open/close state. Mobile-friendly: single column < `lg`, sidebar as overlay drawer with scrim (`bg-black/50`).

**Page-title wiring (no double shell):** `AppShell` is rendered **once** as the parent route element (`<Route element={<AppShell/>}>` with child routes inside). Pages do **not** wrap `AppShell`. The current page title reaches `TopBar` via React Router **outlet context**: `AppShell` derives the title from the active route (a `path→title` map: `/`→"Übersicht", `/metrics`→"Metriken", `/llm`→"LLM-Kaskade", `/users`→"Nutzer") using `useLocation`, and passes it to `TopBar`. Pages render only their own content via `<Outlet/>`.

**Step 5: Wire App.tsx** — nested routes inside the shell: `/` (Overview = redirect or metrics summary), `/metrics`, `/llm`, `/users` → stub components (`<div>…</div>`) replaced in Tasks 4–6.

**Step 6: Write tests** — `admin/src/components/__tests__/Sidebar.test.tsx`:
- `it('marks the active nav item based on the current route')`
- `it('renders the user email in the profile card')`

**Step 7: Commit**

```bash
git add admin/src/components admin/components.json admin/src/App.tsx
git commit -m "feat(admin): app shell with sidebar + top bar (PLAN-034)"
```

---

## Task 4: Metrics view (KPI tiles + Recharts) [DONE]

**Depends on:** Task 3

**Reuse check:** Ports logic from `frontend/src/components/MetricsPanel.tsx`; **replaces** `MiniChart` (SVG) with Recharts. No reuse of PWA component (different design + chart lib).

**Files:**
- Create: `admin/src/pages/MetricsPage.tsx`, `admin/src/components/KpiCard.tsx`, `admin/src/components/TrendChart.tsx`
- Modify: `admin/src/App.tsx` (`/` and `/metrics` → `MetricsPage`)
- Test: `admin/src/pages/__tests__/MetricsPage.test.tsx`

**Step 1: data fetching** — mirror the fetch/loading/error/`days` state machine from `MetricsPanel.tsx:26-51` (`Promise.all([getMetricsSummary(), getMetricsTimeseries(days)])`, range `[7,30,90]`, active default 30, `active` cleanup flag). Identical shape; deviation: render with the new components below.

**Step 2: KpiCard.tsx** — per styleguide "KPI card": `surface`, `rounded-card`, `p-5`; icon square (`rounded-icon`, lucide) + `text-text-secondary` label (12/500); value 28–30px/700 with `tabular-nums`; optional `sub` line (tertiary). Tiles (copy labels from `MetricsPanel.tsx:77-82`): Nutzer gesamt (sub `${pending} wartend`), Freigeschaltet, Aktiv 7T (sub `${active_30d} in 30 T`), Annoncen gesamt, Favoriten, Gespeicherte Suchen. Grid `grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4`.

**Step 3: TrendChart.tsx** — Recharts wrapper (styleguide "Chart card"). Props `{ title; data: TimeseriesPoint[]; type: 'line'|'bar'; accent: string }`. `ResponsiveContainer` height 220. Line → `AreaChart` with `<defs>` linear gradient `accent@0.25 → transparent`, `Area` stroke `accent` width 2, `dot=false`; Bar → `BarChart` with `Bar radius={[4,4,0,0]} fill=accent`. `CartesianGrid` stroke `#1C1C1C` vertical=false; `XAxis dataKey="day"` tickFormatter `dd.mm` (mirror `MiniChart.fmtDay` `MiniChart.tsx:14-17`), `YAxis` hidden or minimal, tick fill `#6B6B70` 11px; `Tooltip` with custom content on `surface-2` `rounded-pill`. Required states: **loading** skeleton (`animate-pulse` block at chart height), **empty** ("Keine Daten im Zeitraum") when all values 0. Charts — copy the **titles and `data` keys** from `MetricsPanel.tsx:86-90`, but use the styleguide accent tokens (NOT the PWA `#A78BFA`/`#34D399`/etc. hexes — the console has its own palette): Neue Annoncen/Tag (bar, `success`), Verkauft/Tag (bar, `danger`), Neue Nutzer/Tag (bar, `primary`), Logins/Tag (line, `success`), Benachrichtigungen/Tag (line, `warning`). Pass the resolved hex (e.g. `#3FD984` for `success`) as the `accent` prop. Grid `grid-cols-1 lg:grid-cols-2 gap-4`.

**Step 4: MetricsPage.tsx** — renders only its own content (range toggle row 7/30/90 with active pill `surface-active` per styleguide, KPI grid, chart grid). It does **not** wrap `AppShell`; the "Metriken" title comes from `AppShell`'s route→title map (Task 3 Step 4).

**Step 5: Write tests** (mock `../api/client`):
- `it('renders KPI values from the summary response')`
- `it('renders the configured trend charts')` (assert chart titles present; mock `ResponsiveContainer` width)
- `it('switches the time range and refetches')`
- `it('shows an error message when the metrics request fails')`

**Step 6: Commit**

```bash
git add admin/src/pages/MetricsPage.tsx admin/src/components/KpiCard.tsx admin/src/components/TrendChart.tsx admin/src/App.tsx admin/src/pages/__tests__/MetricsPage.test.tsx
git commit -m "feat(admin): metrics view with KPI tiles and Recharts trends (PLAN-034)"
```

---

## Task 5: LLM cascade view [DONE]

**Depends on:** Task 3

**Reuse check:** Ports `frontend/src/components/LLMAdminPanel.tsx` (logic + helpers) into a shadcn `Table`. Sparkline N/A here.

**Files:**
- Create (shadcn copy-in): `admin/src/components/ui/table.tsx`, `admin/src/components/ui/badge.tsx`
- Create: `admin/src/pages/LlmPage.tsx`, `admin/src/lib/format.ts`
- Modify: `admin/src/App.tsx` (`/llm` → `LlmPage`)
- Test: `admin/src/pages/__tests__/LlmPage.test.tsx`

**Step 1: lib/format.ts** — copy `formatRelativeTime` and `formatDate` from `frontend/src/utils/format.ts` (verify exact source; mirror verbatim).

**Step 2: helpers** — copy `isCurrentlyDisabled`, `formatCountdown`, `latestRefreshAt` verbatim from `LLMAdminPanel.tsx:11-42`. Copy the 30s countdown ticker effect (`LLMAdminPanel.tsx:109-118`) and the fetch/refresh state machine (`:85-133`). Identical shape.

**Step 3: LlmPage.tsx** — shadcn `Table`, columns (mirror `LLMAdminPanel.tsx:230` headers): Modell, Aktiv, Context, Fehler, Pausiert, Stand. Status as shadcn `Badge` variants mapped to styleguide tokens: active→`success`, paused→`warning` ("Pausiert bis HH:MM"), inactive→`danger` — **icon + text** (lucide `CircleCheck`/`PauseCircle`/`CircleX`). Numeric/countdown cells `tabular-nums`. "Aktualisieren" button (`Button`, lucide `RefreshCw`, spinner while refreshing) → `refreshLLMModels()`. Header shows "Letzte Aktualisierung: {formatRelativeTime(latestRefreshAt)}". Loading/error/empty states (mirror copy from `LLMAdminPanel.tsx`).

**Step 4: Write tests** (mock `../api/client`):
- `it('renders one row per model with id and context length')`
- `it('shows an Aktiv badge for an active model')`
- `it('shows a Pausiert badge with countdown for a disabled model')`
- `it('calls refreshLLMModels and updates rows on Aktualisieren')`

**Step 5: Commit**

```bash
git add admin/src/pages/LlmPage.tsx admin/src/lib/format.ts admin/src/components/ui/table.tsx admin/src/components/ui/badge.tsx admin/src/App.tsx admin/src/pages/__tests__/LlmPage.test.tsx
git commit -m "feat(admin): LLM cascade status view (PLAN-034)"
```

---

## Task 6: Users view (approval + delete + stats) [DONE]

**Depends on:** Task 3

**Reuse check:** Ports `frontend/src/components/UserApprovalPanel.tsx` + `UserStatsDialog.tsx`. Replaces custom `useConfirm`/`usePullToRefresh` with shadcn `AlertDialog` (no pull-to-refresh on desktop console — drop it; note in backlog if mobile PTR ever wanted).

**Files:**
- Create (shadcn copy-in): `admin/src/components/ui/alert-dialog.tsx`, `admin/src/components/ui/dialog.tsx`, `admin/src/components/ui/switch.tsx`
- Create: `admin/src/pages/UsersPage.tsx`, `admin/src/components/UserStatsDialog.tsx`
- Modify: `admin/src/App.tsx` (`/users` → `UsersPage`)
- Test: `admin/src/pages/__tests__/UsersPage.test.tsx`

**Step 1: UsersPage.tsx** — shadcn `Table`. Mirror the optimistic-update logic verbatim from `UserApprovalPanel.tsx`: `loadUsers` (`:32-43`), `handleToggle` optimistic + rollback (`:51-71`), `handleDelete` optimistic removal + functional rollback (`:73-91`). **Deviations:** (a) confirmation via shadcn `AlertDialog` instead of `useConfirm` — copy the German title/message strings verbatim from `:54-59` (entziehen) and `:74-79` (löschen, DSGVO); (b) drop `usePullToRefresh` + its indicator (`:99-108`); (c) approval control = shadcn `Switch` (disabled for self, `currentUserId` from `useAuth().user.id`); (d) layout = table rows, columns: E-Mail (+ "(du)"), Name, Registriert (`toLocaleDateString('de-DE')`), Zuletzt gesehen (`formatDate`), Aktionen (Analyse button → stats dialog; Switch; Löschen button danger). Self row: switch + delete disabled.

**Step 2: UserStatsDialog.tsx** — port `frontend/src/components/UserStatsDialog.tsx` (verify its content) into shadcn `Dialog`; fetch `getUserStats(userId)`; render the stats fields from `UserStats` (`types/api.ts:287-296`). Re-theme to styleguide tokens.

**Step 3: Write tests** (mock `../api/client`):
- `it('renders a row per user with email and approval switch')`
- `it('toggles approval optimistically and persists via setUserApproval')`
- `it('rolls back the toggle when setUserApproval rejects')`
- `it('confirms before deleting and calls deleteUser')`
- `it('disables approval and delete controls for the current user row')`

**Step 4: Commit**

```bash
git add admin/src/pages/UsersPage.tsx admin/src/components/UserStatsDialog.tsx admin/src/components/ui/alert-dialog.tsx admin/src/components/ui/dialog.tsx admin/src/components/ui/switch.tsx admin/src/App.tsx admin/src/pages/__tests__/UsersPage.test.tsx
git commit -m "feat(admin): user approval, delete and stats view (PLAN-034)"
```

---

## Task 7: Backend — session cookie domain + post-login return target [DONE]

**Depends on:** (none — independent of admin frontend; can run in parallel)

**Files:**
- Modify: `backend/app/config.py` (add settings)
- Modify: `backend/app/api/auth.py` (cookie domain helper, return_to handling)
- Test: `backend/tests/test_auth.py` (create or extend)

**Step 1: config.py** — add two settings near `COOKIE_SECURE` (`config.py:48`):

```python
COOKIE_DOMAIN: str = ""          # e.g. ".rcn-scout.d2x-labs.de" in prod; empty = host-only (dev)
ADMIN_URL: str = "http://localhost:4300"  # admin console origin (post-login return allowlist)
```

**Step 2: auth.py — cookie kwargs helper.** Add near the top of `auth.py` and use it for **every** `set_cookie`/`delete_cookie` of `oauth_state`, `session`, and the new `oauth_return` (so the cookies span the parent domain in prod):

```python
def _cookie_domain_kwargs() -> dict:
    return {"domain": settings.COOKIE_DOMAIN} if settings.COOKIE_DOMAIN else {}
```

Apply to: `oauth_state` set (`auth.py:37-41`) and its `delete_cookie` calls (`:89,:117,:129`); `session` set (`:130-136`); logout `delete_cookie("session")` (`:163`).

**Cookie clearing — attribute match required.** A browser only removes a cookie when the `delete_cookie` attributes match what was set. Starlette's `delete_cookie` does **not** inherit them, so every `delete_cookie` in this file must pass the same `path="/"`, `httponly=True`, `samesite="lax"`, `secure=settings.COOKIE_SECURE`, **and** `**_cookie_domain_kwargs()` as the corresponding `set_cookie`. Concretely, change logout (`:163`) from `response.delete_cookie("session")` to:

```python
response.delete_cookie(
    "session",
    httponly=True,
    samesite="lax",
    secure=settings.COOKIE_SECURE,
    **_cookie_domain_kwargs(),
)
```

Apply the same attribute set to the `oauth_state` / `oauth_return` `delete_cookie` calls.

**Step 3: auth.py — return_to allowlist + cookie.** `auth_google` (`:24`) currently takes only `request: Request`. A bare query string is **not** read unless declared as a parameter, so add an explicit FastAPI `Query` param — without this the whole return_to flow silently falls back to `FRONTEND_URL`. Update the signature and imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request  # add Query

@router.get("/auth/google")
async def auth_google(request: Request, return_to: str | None = Query(default=None)):
    ...
```

Validate `return_to`: allowed only if it equals `settings.FRONTEND_URL` or `settings.ADMIN_URL` (exact origin match) via `_resolve_return_base`; otherwise fall back to `settings.FRONTEND_URL`. Set a short-lived `oauth_return` cookie (httponly, `max_age=300`, `samesite="lax"`, `secure=settings.COOKIE_SECURE`, `**_cookie_domain_kwargs()`) holding the resolved base URL.

```python
def _resolve_return_base(return_to: str | None) -> str:
    allowed = {settings.FRONTEND_URL, settings.ADMIN_URL}
    return return_to if return_to in allowed else settings.FRONTEND_URL
```

**Step 4: auth.py — use return base in callback.** In `auth_google_callback` (`:45`) read `base = _resolve_return_base(request.cookies.get("oauth_return"))`. Replace the three hard-coded `settings.FRONTEND_URL` redirect targets:
- denied/error (`:56,:64,:88`) → `f"{base}/login?error=denied"`
- not_approved (`:115`) → `f"{base}/login?error=not_approved&email=..."`
- success (`:128`) → `base`
Delete the `oauth_return` cookie (with domain) on every exit path alongside `oauth_state`.

**Step 5: Write tests** — `backend/tests/test_auth.py` (mirror existing async test client setup in `backend/tests/`):
- `it: auth_google with return_to=ADMIN_URL sets oauth_return cookie to that origin`
- `it: auth_google with an unlisted return_to falls back to FRONTEND_URL`
- `it: _resolve_return_base returns FRONTEND_URL for None / unknown / matching origin`
- `it: _resolve_return_base rejects a trailing-slash variant of an allowed origin` (exact-match allowlist; the admin app sends `window.location.origin`, which has no trailing slash — assert the strict behavior so the contract is explicit)
- `it: cookie kwargs include domain when COOKIE_DOMAIN set, omit when empty`
(Use monkeypatch on `settings` for COOKIE_DOMAIN/ADMIN_URL.)

**Step 6: Commit**

```bash
git add backend/app/config.py backend/app/api/auth.py backend/tests/test_auth.py
git commit -m "feat(auth): session cookie domain + validated post-login return target (PLAN-034)"
```

---

## Task 8: Remove `/admin` from the PWA [ ]

**Depends on:** Task 4, Task 5, Task 6 (console must cover the functionality before the PWA drops it)

**Pre-write scan (run before editing — confirm no non-admin consumer):**

```bash
grep -rn "MetricsPanel\|LLMAdminPanel\|UserApprovalPanel\|MiniChart\|UserStatsDialog\|AdminPage\|AdminUsersPage" frontend/src
grep -rn "getUsers\|getLLMModels\|refreshLLMModels\|setUserApproval\|deleteUser\|getUserStats\|getMetricsSummary\|getMetricsTimeseries" frontend/src
```

Enumerate every hit. Delete only files/symbols whose **sole** consumers are the admin area. Reviewer-verified grep results: `useConfirm` is **shared** (consumers in `FavoritesPage.tsx`, `FavoritesModal.tsx`, `DetailPage.tsx`) → **keep**. `formatDate` (`utils/format`) is shared → **keep**. `MiniChart`, `UserStatsDialog`, and `usePullToRefresh` are **admin-only** (sole consumer was `UserApprovalPanel.tsx`) → **delete** them and their tests. Re-run the grep at implementation time to confirm before deleting (guards against new consumers added since planning).

**Files:**
- Delete: `frontend/src/pages/AdminPage.tsx`, `frontend/src/pages/AdminUsersPage.tsx`, `frontend/src/components/MetricsPanel.tsx`, `frontend/src/components/LLMAdminPanel.tsx`, `frontend/src/components/UserApprovalPanel.tsx`, `frontend/src/components/MiniChart.tsx`, `frontend/src/components/UserStatsDialog.tsx`, `frontend/src/hooks/usePullToRefresh.ts`
- Delete (orphaned hook test): `frontend/src/hooks/__tests__/usePullToRefresh.test.ts` (verify path via grep — admin-only after `UserApprovalPanel` removal)
- Delete (all six verified to exist): `frontend/src/pages/__tests__/AdminPage.test.tsx`, `frontend/src/components/__tests__/UserApprovalPanel.test.tsx`, `frontend/src/components/__tests__/MetricsPanel.test.tsx`, `frontend/src/components/__tests__/LLMAdminPanel.test.tsx`, `frontend/src/components/__tests__/MiniChart.test.tsx`, `frontend/src/components/__tests__/UserStatsDialog.test.tsx`
- Modify: `frontend/src/App.tsx` — remove imports `:10-11` and routes `:186-187`
- Modify: `frontend/src/api/client.ts` — remove the 8 admin functions (`:155-218`) **only if** the grep shows no remaining PWA consumer
- Modify: `frontend/src/types/api.ts` — remove `MetricsSummary`, `TimeseriesPoint`, `MetricsTimeseries`, `LLMModelRow`, `UserStats` (keep `UserRow` only if still referenced; grep decides)

**Step 1:** Apply deletions and `App.tsx` edits. **Step 2:** Apply `client.ts`/`types/api.ts` cleanup per grep results. **Step 3:** Boy-Scout — remove any now-dead imports the deletions orphan (e.g. `require_admin` stays in backend; this task is frontend-only).

**Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "refactor(pwa): remove /admin area — relocated to standalone console (PLAN-034)"
```

---

## Task 9: Deployment — image, compose service, Traefik router, CI, env [ ]

**Depends on:** Task 1, Task 7

**Files:**
- Modify: `docker-compose.prod.yml` (add `admin` service + Traefik router; add backend env `COOKIE_DOMAIN`, `ADMIN_URL`)
- Modify: `.github/workflows/deploy.yml` (build/push admin image; deploy pull)
- Modify: `docs/architektur.md` (document the admin subdomain + cookie-domain), `docs/definition.md` (admin console as a component)

**Step 1: compose — backend env.** Add to the `backend` service environment (`docker-compose.prod.yml:25-38`):

```yaml
      COOKIE_DOMAIN: .rcn-scout.d2x-labs.de
      ADMIN_URL: https://admin.rcn-scout.d2x-labs.de
```

**Step 2: compose — admin service.** Mirror the `nginx` service block (`:42-56`) as `admin`:

```yaml
  admin:
    image: ghcr.io/marcoroth1983/rc-network-scraper/admin:${IMAGE_TAG:-latest}
    restart: unless-stopped
    depends_on:
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.rcn-admin.rule=Host(`admin.rcn-scout.d2x-labs.de`)"
      - "traefik.http.routers.rcn-admin.entrypoints=websecure"
      - "traefik.http.routers.rcn-admin.tls.certresolver=letsencrypt"
      - "traefik.http.services.rcn-admin.loadbalancer.server.port=80"
      - "traefik.docker.network=web"
    networks:
      - default
      - web
```

(The admin nginx proxies `/api/` to `http://backend:8000` on the shared `default` network — same as the main nginx.)

**Step 3: CI — build/push admin image.** In `.github/workflows/deploy.yml`, add a build step mirroring the nginx step (`:39-47`):

```yaml
      - name: Build & push admin image
        uses: docker/build-push-action@v6
        with:
          context: ./admin
          file: ./admin/Dockerfile
          push: true
          tags: |
            ghcr.io/marcoroth1983/rc-network-scraper/admin:latest
            ghcr.io/marcoroth1983/rc-network-scraper/admin:${{ steps.tag.outputs.sha }}
```

And extend the deploy pull (`:64`): `docker compose -f docker-compose.prod.yml pull nginx backend admin`.

**Step 4: Docs.** `architektur.md`: add the admin console (standalone app, own subdomain, shared backend, cookie-domain auth, shadcn/Recharts stack, adapter boundary for ToDoList reuse). `definition.md`: list the admin console as a component and that PWA `/admin` was removed.

**Step 5: Ops prerequisite (note, not code).** Document in the plan commit message / `docs/architektur.md`: a DNS A-record `admin.rcn-scout.d2x-labs.de → 152.53.238.3` must exist before the Traefik cert can issue. Google OAuth: **no change** (redirect_uri stays `https://rcn-scout.d2x-labs.de/api/auth/google/callback`).

**Step 6: Commit**

```bash
git add docker-compose.prod.yml .github/workflows/deploy.yml docs/architektur.md docs/definition.md
git commit -m "build(admin): compose service, Traefik subdomain router, CI image, env (PLAN-034)"
```

_Code review closed 2026-06-18 (frontend, cycle 1, Tasks 2+3): 1 High fixed (`handleResponse` 204-guard for `deleteUser`); 3 Medium/Low fixed (AuthUser dedup, LoginPage hover stale-closure → Tailwind, IconButton `type="button"`); 1 test added (RequireAdmin redirect-URL assertion); dual-`useAuth` fetch deferred to backlog. Fix commit 4c53dde._

_Code review closed 2026-06-18 (python, cycle 1): 1 High fixed (`delete_cookie` missing `path="/"` → cookies now cleared correctly, deduped via `_cookie_kwargs`/`_clear_oauth_cookies`); 1 Medium fixed (return-type hints); 2 Medium deferred to backlog (callback-error-path tests, integration markers); subdomain cookie-scope tolerated (single-operator). Fix commit d0c1860._

_Code review closed 2026-06-18 (frontend, orchestrator cycle 2, Tasks 4+5+6): MINOR, 0 blocking. Fixed: German plural grammar in `formatRelativeTime`, `formatCountdown` Math.floor + dead-branch removal, `UserStatsDialog` `number|null` sentinel, `TrendChart` `useId` gradient ids. Deferred to backlog: rollback tail-reinsert, unmount-guard style unification, badge `<span>`-in-`<td>`, explicit delete-failure test. Fix commit ef6ee47._

---

_Code review closed 2026-06-18 (frontend, cycle 1): 0 Critical, 0 High; M2 fixed (deleteUser now routes through handleResponse); M1/M3/M4 tolerated per plan scope; 3 Low/3 Suggestion deferred._

_Code review closed 2026-06-18 (frontend, cycle 2 — Task 3): 0 Critical, 0 High; M1 fixed (AppShell named export); M3 fixed (@/ alias for useAuth); L1 fixed (Mock cast in Sidebar test); M2 deferred to backlog (dual useAuth fetch → context provider); L2/S1/S2 deferred._

_Code review closed 2026-06-18 (frontend, cycle 1 — Task 4): 0 Critical, 0 High; M2 fixed (clear stale series/summary before refetch); M3 fixed (guard placement comment); L1 fixed (gradient id includes title slug); L2 fixed (named export); L3 fixed (named colour constants); M1 retained per plan spec (all-zero = empty state)._

_Code review closed 2026-06-18 (frontend, cycle 1 — Task 5): 0 Critical, 0 High; M2 fixed (ticker comment); M3 fixed (mountedRef guard in handleRefresh); M1 tolerated (verbatim copy per plan spec — pre-existing source bug, scope of Task 8 removal); L1/L2/S1/S2/S3 deferred._

_Code review closed 2026-06-18 (frontend, cycle 1 — Task 6): 0 Critical, 0 High; M1 fixed (active flag in useEffect IIFE); M2 fixed (setError(null) in performToggle/performDelete); M3 fixed (optimistic-flip assertion in test 2); M4 fixed (named useCallback for onOpenChange); M5 fixed (UserStatsDialog mounted unconditionally); L1 fixed (user guard after all hooks); L3 fixed (makeUser typed as UserRow); L2/S1/S2/S3 deferred._

## Verification

Automated checks (run once, end-of-plan):

```bash
# Admin app — install (after Human approves new deps), lint, typecheck, build, tests
cd admin && npm ci && npm run lint && npm run build && npm run test -- --run

# PWA — still builds and tests green after /admin removal
cd frontend && npm run lint && npm run build && npm run test -- --run

# Backend — auth tests + suite
docker compose exec backend pytest tests/ -v
```

Manual smoke (single cross-state flow — login spans hosts):
1. `docker compose up --build -d`; open the admin dev app (`cd admin && npm run dev`, http://localhost:4300).
2. Unauthenticated visit → redirected through Google → returns to the admin origin (not the PWA).
3. As an admin user: sidebar nav reaches Metriken / LLM-Kaskade / Nutzer; KPI tiles + charts render; LLM table shows badges; user approval toggle + delete + stats work.
4. As a `member` user → "Kein Zugriff" screen.
5. PWA: navigating to `/admin` falls through to listings (no admin UI).

---

## Notes / Out of scope (→ docs/backlog.md)

- ⌘K command palette / search bar from the reference image.
- Mobile pull-to-refresh in the console (desktop-first; dropped from the ported approval panel).
- Porting the shell + adapters to the ToDoList project (separate plan; the adapter boundary — `useAuth` + `api/client.ts` — is built to enable it).
- CI health-check for the admin subdomain (deploy.yml `:68` only curls the PWA `/health`; admin self-heals via Traefik — add an explicit `curl admin.rcn-scout.d2x-labs.de/health` later).
- Deep-link return after login: an unauthenticated visit to e.g. `/users` returns to the admin root after Google OAuth, not the requested route (accepted MVP — sidebar nav is fast).

---

## Plan Review
<!-- dglabs.agent.review-plan — 2026-06-18 -->

### Self-Review Gate (Pass 0)

- [x] 1. Placeholder scan — no TODO/FIXME/TBD/XXX/placeholder in plan body.
- [x] 2. Dropped-field orphan scan — no renamed/dropped identifiers found with stale references.
- [x] 3. Line-anchor freshness — **partial failures noted below in Blocking section.** Several cited line numbers are off or reference content that has shifted. Details per finding.
- [x] 4. Test-count consistency — test counts implicit (no specific total claimed); each task lists individual `it()` names, counts are internally consistent.
- [x] 5. Deleted-class caller check — `useConfirm` is shared: confirmed consumers in `FavoritesPage.tsx`, `FavoritesModal.tsx`, `DetailPage.tsx`, `ConfirmDialog.tsx` beyond the admin area — the plan correctly instructs to keep it. `usePullToRefresh` confirmed consumers only in `UserApprovalPanel.tsx` and its test + `usePullToRefresh.ts` + its own test — the plan's instruction to "grep decides" is correct but the grep will reveal it is admin-only; see Non-Blocking note. `MiniChart` has its own test (`MiniChart.test.tsx`) — plan does not list it for deletion; see Blocking #4.
- [x] 6. Mirror-reference verification — `frontend/nginx.conf` checked: `/sw.js` block exists at line 14 and matches plan's description. Plan's "remove the `/sw.js` block" instruction is verified correct. `frontend/src/api/client.ts:155-218` verified: admin functions start at line 155 (`getLLMModels`) through line 218 (`getUserStats`). Accurate.
- [x] 7. Convention contradictions across tasks — no contract introduced in one task and violated in another found. `AuthUser` shape consistent throughout.

---

### Structural Checklist (Pass 1.A)

- [x] Required sections present (Context & Goal, Breaking Changes, Steps, Verification)
- [x] Step status markers present on every task header (`[ ]`)
- [x] Step granularity — generally appropriate; one concern noted (Task 4 AppShell/title wiring — see AI-Review finding)
- [x] Test files named per step — every task with tests names the target test file explicitly
- [x] Breaking changes marked Yes with recovery steps
- [x] BREAK markers — none present; appropriate (no external gate needed for a new standalone app; PWA removal waits on Tasks 4–6 per Depends-on chain)

---

### 🔴 Blocking

1. **[Agent] — `backend/app/api/auth.py:25` — `return_to` query parameter missing from function signature.** The plan (Task 7, Step 3) instructs adding `return_to: str | None = None` to `auth_google`. The actual signature at line 25 is `async def auth_google(request: Request)` with no query params declared. FastAPI does not auto-read query params from `request.query_params` via a bare `Request` argument — they must be declared as function parameters. The plan's instruction is correct in intent but must be explicit that the parameter is added as a FastAPI Query param: `return_to: str | None = Query(default=None)`. Without this, the `return_to` value is never bound and `_resolve_return_base` always receives `None`, silently falling back to `FRONTEND_URL` for all callers including the admin app. The plan also says to read `return_to` from the `oauth_return` cookie in the callback (Step 4), which is correct — but the `auth_google` handler must still accept `return_to` from the query string first to set that cookie. **Fix: add `from fastapi import Query` and declare `return_to: str | None = Query(default=None)` in `auth_google`.**

2. **[Agent] — `backend/app/api/auth.py:159,163` — `delete_cookie("session")` in logout will fail to clear the cookie in prod when `COOKIE_DOMAIN` is set.** The plan (Task 7, Step 2) correctly identifies this problem and mandates applying `_cookie_domain_kwargs()` to `delete_cookie` calls. However, the plan's prose at Step 2 lists `:163` as a target but calls the endpoint `logout` at line 159 and the `delete_cookie` at line 163 — confirmed correct by the actual file. The real risk is that the plan does NOT mention `httponly` and `samesite` parameters for `delete_cookie` calls. In Starlette/FastAPI, `response.delete_cookie` sets `max_age=0` and `expires=0`, but if the original cookie was set with `httponly=True` and `samesite="lax"`, the delete call must include those same attributes (some browsers enforce attribute matching for cookie deletion). The plan's `_cookie_domain_kwargs()` helper handles `domain` but the step must also document that `delete_cookie` calls for `oauth_state` and `session` need `httponly=True, samesite="lax"` mirrored. **Fix: expand Step 2 to specify `response.delete_cookie("session", httponly=True, samesite="lax", **_cookie_domain_kwargs())`.**

3. **[Agent] — `frontend/src/components/MetricsPanel.tsx:86-90` — Chart accent color mismatch in Task 4, Step 3.** The plan states to use `success` for "Neue Annoncen/Tag" and `danger` for "Verkauft/Tag", but the actual `MetricsPanel.tsx` uses `#6366F1` (indigo) for listings_new and `#EC4899` (pink) for listings_closed. More importantly, the plan says "(bar, success)" for "Neue Annoncen/Tag" and "(bar, danger)" for "Verkauft/Tag" — mapping `success=#3FD984` (green) and `danger=#F75555` (red). Green for "new listings per day" and red for "sold/closed" is a defensible design choice for the new admin console, but the comment "copy titles/accents from `MetricsPanel.tsx:86-90`" directly contradicts this — those lines use different colors. The implementer will encounter a contradiction and must guess which to follow. **Fix: remove the "copy titles/accents from MetricsPanel.tsx:86-90" directive; specify each chart's title and accent color explicitly in the plan step body, since the styleguide intentionally deviates from the PWA palette.**

4. **[Agent] — Task 8 — `frontend/src/components/__tests__/MiniChart.test.tsx` not listed for deletion.** The plan lists files to delete in Task 8 including `MiniChart.tsx` but does NOT list `frontend/src/components/__tests__/MiniChart.test.tsx` in the delete set. The test file exists (confirmed by glob). After `MiniChart.tsx` is deleted, `MiniChart.test.tsx` will fail to import it and break the PWA test suite. The plan's Task 8 scan grep enumerates test files found but only explicitly calls out `AdminPage.test.tsx` and `UserApprovalPanel.test.tsx`. **Fix: add `frontend/src/components/__tests__/MiniChart.test.tsx` to the Task 8 delete list.**

5. **[AI-Review] — Task 1, Step 4 — `tailwind.config.js` mixes ESM `export default` with CommonJS `require('tailwindcss-animate')`.** The config snippet uses `export default { plugins: [require('tailwindcss-animate')] }`. In a Vite 8 project with `"type": "module"` in `package.json`, `require()` is not available and this will throw at build time. The frontend's own `tailwind.config.js` (which the plan says to mirror) uses CommonJS syntax — but the admin app should not inherit that constraint if it is scaffolded as ESM. **Fix: replace `require('tailwindcss-animate')` with `import tailwindcssAnimate from 'tailwindcss-animate'` at the top of the file and use `plugins: [tailwindcssAnimate]`, then ensure `package.json` does NOT set `"type":"module"` if staying CommonJS, or convert the whole config to ESM consistently.**

6. **[AI-Review] — Task 2, Step 4 — `RequireAdmin` performs `window.location.href` assignment during render (synchronous render side effect).** The code block sets `window.location.href` in the function body of a React component when `!user`, which runs during rendering. Under React 18+ Strict Mode (double-invocation in dev), this triggers two navigation attempts. It also violates the React rendering purity contract. **Fix: wrap the redirect in `useEffect(() => { if (!loading && !user) window.location.href = ...; }, [loading, user])` and return a loading placeholder until the effect fires. Alternatively use `react-router-dom`'s `useNavigate` pointing to the backend OAuth endpoint through a redirect component.**

---

### 🟡 Non-Blocking

1. **[Agent] — Task 7, Step 3 — `oauth_return` cookie security: the `return_to` allowlist uses exact string equality (`return_to in allowed`).** This is correct and safe. However, the plan does not address URL normalization — e.g., `https://admin.rcn-scout.d2x-labs.de/` (with trailing slash) would not match `https://admin.rcn-scout.d2x-labs.de` (without). Low risk since the admin app sends `window.location.origin` which never has a trailing slash, but worth documenting in the test.

2. **[Agent] — Task 9, Step 3 — CI deploy step references line `:64` for the pull command, but the actual `deploy.yml` line 64 is `docker compose -f docker-compose.prod.yml pull nginx backend`.** The plan's fix extends this to add `admin` to the pull command. The line anchor `:64` is correct as a structural reference, but the deploy script runs a single `docker compose up -d` without specifying services — so the admin service will be started automatically once it is in `docker-compose.prod.yml`. The plan should note that the health-check `curl http://localhost/health` at line 68 only checks the PWA nginx; no admin health-check is wired in CI. Low risk (Traefik self-heals), but worth adding to backlog.

3. **[Agent] — Task 6, Step 1 — `UserStatsDialog` is listed as a file that `UserApprovalPanel.tsx` depends on.** The `UserStatsDialog` grep confirms it is only consumed by `UserApprovalPanel.tsx` (and its own test). The plan correctly marks it as admin-only and schedules it for deletion from PWA in Task 8. The `UserStatsDialog.test.tsx` file also exists but is not listed in Task 8's delete set. It is not a blocker (the test imports `UserStatsDialog` which will be deleted — the test will fail). **Recommend adding `frontend/src/components/__tests__/UserStatsDialog.test.tsx` to the Task 8 delete list.**

4. **[Agent] — `usePullToRefresh` — the plan says "grep decides" whether to keep or delete it.** Based on the actual grep: `usePullToRefresh` is consumed only by `UserApprovalPanel.tsx` and its own test file. Once `UserApprovalPanel.tsx` is deleted in Task 8, `usePullToRefresh.ts` and `frontend/src/hooks/__tests__/usePullToRefresh.test.ts` will have no consumers. The plan should either explicitly delete them in Task 8 or add a backlog note. Since the hook itself is self-contained and has its own tests, leaving orphaned test infrastructure is a Boy-Scout violation.

5. **[Agent] — Task 2, Step 3 — `useAuth.ts` mirror note says "Deviation: AuthUser.role union unchanged".** This is correct but the mirror instruction says "copy verbatim" while also noting a deviation. The actual `useAuth.ts` has `logout` doing `window.location.href = '/login'` which is fine for the PWA. For the admin app, post-logout should go to `/login` within the admin app (same origin), which the mirror gives correctly. No code change needed, but the plan should clarify this is intentional (not an oversight).

6. **[AI-Review] — Task 3/Task 4 ambiguity — `MetricsPage` is described as being "wrapped with AppShell title 'Metriken' (provided via route element)".** This phrasing is ambiguous: it suggests `MetricsPage` itself wraps `AppShell`, which would double-render the shell. The intent is that the title is passed from the route configuration into `AppShell` via outlet context or props. The plan should clarify the mechanism (e.g., outlet context, a `usePageTitle` hook, or route-level `element={<MetricsPage title="Metriken"/>}`). The AI-Review flagged this as blocking; treating as non-blocking because the implementer can resolve the ambiguity without plan revision — but a clarification note would prevent a wasted cycle.

7. **[AI-Review] — Return-to preserves only the origin, not the requested route.** An admin user landing on `https://admin.rcn-scout.d2x-labs.de/users` who is not yet authenticated gets sent through Google OAuth and returns to `https://admin.rcn-scout.d2x-labs.de` (root), not `/users`. For a single-operator tool this is acceptable UX — the sidebar navigation is fast. Noted as non-blocking since the plan already scopes this as an MVP.

---

### Verdict

REVISE — 6 blocking issues: missing FastAPI `Query` declaration for `return_to` (silent no-op at runtime), incomplete `delete_cookie` attribute spec (prod cookie not cleared), chart-color/source-of-truth contradiction in Task 4, missing `MiniChart.test.tsx` deletion, ESM/CJS `require()` mismatch in tailwind config, and render-phase `window.location.href` side effect in `RequireAdmin`.

---

## Plan Review — Cycle 2
<!-- dglabs.agent.review-plan — 2026-06-18 -->

### Self-Review Gate (Pass 0) — Cycle 2

- [x] 1. Placeholder scan — no TODO/FIXME/TBD/XXX/placeholder in plan body.
- [x] 2. Dropped-field orphan scan — cycle-1 fixes introduced no stale references. The old blocking descriptions inside the cycle-1 review block are exempt (Plan Review section). No renamed field leaks in plan body.
- [x] 3. Line-anchor freshness — `MiniChart.tsx:14-17` verified: `fmtDay` at lines 14-17 confirmed. `auth_google` `:24`, `auth.py:37-41`, `:130-136`, `:163` not re-verified (backend file unchanged since cycle-1 checks); plan instructs implementer to verify at implementation time. `api/client.ts:155-218` verified (cycle-1). No new anchors introduced.
- [x] 4. Test-count consistency — no global test-count claim anywhere in plan. Each task lists named `it()` blocks consistently. Task 7 Step 5 lists 5 tests; all enumerated by name; no drift found.
- [x] 5. Deleted-class caller check — cycle-1 fix: `MiniChart.test.tsx`, `UserStatsDialog.test.tsx`, and `usePullToRefresh.test.ts` now all listed in Task 8 delete set (lines 445-446). Confirmed files exist in repo. Pass.
- [x] 6. Mirror-reference verification — `MiniChart.tsx:14-17` (fmtDay) confirmed exact match. No new mirror references introduced by cycle-1 fixes.
- [x] 7. Convention contradictions across tasks — `useEffect` redirect pattern in `RequireAdmin` (Task 2 Step 4) is consistent with Task 2 Step 7 test instructions ("do not assert on navigation side-effect"). ESM tailwind config (Task 1 Step 4) is consistent with Step 4 note "ESM only — never `require()` here". No contradictions.

### Structural Checklist (Pass 1.A) — Cycle 2

- [x] Required sections present
- [x] Step status markers on every task header
- [x] Step granularity — all tasks within limits; no task exceeds 6 new files or 4 interactive behaviors
- [x] Test files named per step — all tasks with tests name target files explicitly
- [x] Breaking changes marked Yes with recovery steps
- [x] BREAK markers — none; appropriate

### Cycle-1 Blocker Resolution Verification

1. [x] **Blocker 1 resolved** — Task 7 Step 3 now declares `from fastapi import APIRouter, Depends, HTTPException, Query, Request` and `return_to: str | None = Query(default=None)` in `auth_google`. Silent fallback gap eliminated.
2. [x] **Blocker 2 resolved** — Task 7 Step 2 now specifies the full `delete_cookie` attribute set: `httponly=True, samesite="lax", secure=settings.COOKIE_SECURE, **_cookie_domain_kwargs()` with an explicit code block. Applied to all three `delete_cookie` targets.
3. [x] **Blocker 3 resolved** — Task 4 Step 3 now says "copy the **titles and `data` keys** from MetricsPanel.tsx:86-90" (not accents) and "use the styleguide accent tokens (NOT the PWA hexes)". Each chart's accent is listed explicitly. No contradiction remains.
4. [x] **Blocker 4 resolved** — `frontend/src/components/__tests__/MiniChart.test.tsx` now in Task 8 delete list (line 446 confirmed).
5. [x] **Blocker 5 resolved** — tailwind.config.js snippet now uses `import tailwindcssAnimate from 'tailwindcss-animate'` (ESM) with `plugins: [tailwindcssAnimate]`. Explicit note: "ESM only — never `require()` here."
6. [x] **Blocker 6 resolved** — `RequireAdmin` redirect moved into `useEffect([loading, user])` that fires only after render. Returns loader placeholder while effect is pending. Strict-Mode safe.

### 🔴 Blocking — Cycle 2

None.

### 🟡 Non-Blocking — Cycle 2

Cycle-1 non-blocking items 1, 2, 5, 7 carry forward unchanged (trailing-slash allowlist test documentation, CI health-check backlog note, useAuth mirror clarification, deep-link return MVP scope). Items 3 and 4 are resolved (UserStatsDialog.test.tsx and usePullToRefresh deletions now in Task 8). Item 6 (AppShell title wiring ambiguity) is resolved by Task 3 Step 4 "Page-title wiring" paragraph which clearly describes the route→title map in AppShell using `useLocation`, with pages rendering via `<Outlet/>`.

AI-Review Pass 2 skipped per thin-plan UI-only rule does NOT apply here — this is a full plan (new backend auth, new service, migration-equivalent PWA removal). However, the cycle-1 AI-Review findings are already incorporated and all structural/backend findings are resolved. Re-running would produce redundant output. No new backend or contract changes were introduced by cycle-1 fixes.

### Verdict — Cycle 2

APPROVED — All 6 cycle-1 blocking issues are resolved in the plan body; Pass-0 gate passes clean; no new leaks introduced by the fixes; plan is implementation-ready.
