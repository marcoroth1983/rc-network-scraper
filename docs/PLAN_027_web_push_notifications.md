# Web Push Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Add a `WebPushPlugin` to the existing `notification_registry` so per-user SavedSearch matches are delivered as native browser/PWA push notifications. Web Push becomes the default channel; Telegram code stays in place but is gated behind `NOTIFICATION_CHANNEL`. UI: a small soft-ask banner cloned from `InstallPrompt` and a `NotificationsPanel` on `/profile` for device management + opt-in.

**Architecture:**
- **Backend (FastAPI / SQLAlchemy async):** New `WebPushPlugin` (`app/notifications/web_push_plugin.py`) implementing the existing `NotificationPlugin` ABC. Two persistence concerns: a new `push_subscriptions` table (multi-device, N rows per user) and a new column `web_push_enabled` on the existing `user_notification_prefs` table. Channel routing happens at plugin-registration time in `main.py:lifespan()` based on `settings.NOTIFICATION_CHANNEL ∈ {webpush, telegram, both}`. The same channel switch also gates Telegram-only side effects (`fav_sweep` scheduler + `setWebhook` call), so `NOTIFICATION_CHANNEL=webpush` does not leave a half-running Telegram subsystem behind. New REST module `app/api/notifications.py` exposes subscription CRUD + the VAPID public key + the consolidated preferences endpoint. The legacy `GET/PUT /api/telegram/prefs` routes are **removed** (the same DB row is now served by `/api/notifications/preferences` as single source of truth).
- **Frontend (React 19 / Vite 8 / Tailwind 3):** Adopt `vite-plugin-pwa` in `injectManifest` mode and ship a custom `src/sw.ts` (push + notificationclick handlers + manifest precache; filename matches the existing `nginx.conf:14` `/sw.js` no-cache rule). Existing legacy artifacts are **deleted** in the same plan (`frontend/public/sw.js`, `frontend/public/manifest.json`, the `<link rel="manifest">` in `index.html`, the manual `navigator.serviceWorker.register('/sw.js')` block in `main.tsx`) — all replaced by VitePWA's auto-injected registration and a `manifest:` config block that mirrors the existing `manifest.json` content (including the maskable icons that already live in `public/icons/`). New `src/notifications/` module with a 5-state `useWebPushSubscription` hook, a small subscriptions client (the prefs functions are extended in `api/client.ts`, not duplicated), a UA→device-label helper, and a `FirstStartPushPrompt` banner that mirrors the existing `InstallPrompt` glassmorphism shell. iOS gating reuses the extracted `isStandalone()` check: on iOS without standalone, the push prompt stays hidden until the PWA is installed. New `NotificationsPanel` slots into `ProfilePage` Column 2 above `TelegramPanel` and is split into two tasks (state-display vs. device-list + prefs).
- **VAPID:** Single keypair, generated once via `npx web-push generate-vapid-keys` (URL-safe base64 output, exactly what the browser expects). Local: `docker-compose.yml` env vars. Prod: GitHub Actions repository secrets, passed to the frontend image at build time as `VITE_VAPID_PUBLIC_KEY` via `frontend/Dockerfile` build-arg (the canonical Dockerfile — there is no `Dockerfile.prod`).

**Tech Stack:** FastAPI, SQLAlchemy async, `pywebpush` (Python), `pydantic-settings`, React 19, `vite-plugin-pwa@^0.21`, Workbox 7, native `PushManager` / `ServiceWorkerRegistration` APIs, Tailwind 3, npm (the `pnpm-lock.yaml` currently sitting untracked in `frontend/` is removed in Task 10).

**Breaking Changes:**
- Default delivery channel flips from Telegram to Web Push. Telegram-only deployments must set `NOTIFICATION_CHANNEL=telegram` to preserve current behavior.
- Backend routes `GET /api/telegram/prefs` and `PUT /api/telegram/prefs` are removed. Only two frontend call-sites exist (`client.ts:getNotificationPrefs` / `updateNotificationPrefs`); both are retargeted to `/api/notifications/preferences` in this plan, so no downstream code change is needed beyond what this plan ships.
- New required env vars when `NOTIFICATION_CHANNEL` includes `webpush`: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`. The frontend reads the public key from the API at runtime (no build-arg required for dev/local; build-arg path documented for prod for marginal request-saving — see Task 20 + Notes).

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-05-03 |
| Human | pending | — |

---

## Context

### What exists today (verified by grep + read, 2026-05-03)

- **Plugin registry** is the right reuse point. [`backend/app/notifications/registry.py:35`](backend/app/notifications/registry.py#L35) defines a module-level `notification_registry` with `register()` + `dispatch(MatchResult)`. Each plugin is checked via `is_configured()` before `send()`; failures are caught and logged. No changes to registry/base needed (one optional non-blocking improvement: add public `is_registered(cls)`; deferred to backlog).
- **`MatchResult` payload** ([backend/app/notifications/base.py:7-16](backend/app/notifications/base.py#L7-L16)) carries `saved_search_id`, `search_name`, `user_id`, `new_listing_ids`, `new_listing_titles`, `total_new` — sufficient for push title/body without further refactoring.
- **TelegramPlugin** ([backend/app/telegram/plugin.py](backend/app/telegram/plugin.py)) is the structural template. Its `is_configured()` returns `settings.telegram_enabled`; `send()` looks up `users.telegram_chat_id`, checks `user_notification_prefs.new_search_results`, formats an HTML digest, calls `bot.send_message`. The WebPushPlugin mirrors this shape but iterates over the user's `push_subscriptions` rows.
- **Existing prefs table** `user_notification_prefs` ([backend/app/db.py:177-186](backend/app/db.py#L177-L186)) — columns: `user_id PK`, `new_search_results`, `fav_sold`, `fav_price`, `fav_deleted`, `updated_at`. Note: the legacy `fav_indicator` column was dropped at [backend/app/db.py:254](backend/app/db.py#L254) (PLAN-025). We **extend** this table with `web_push_enabled` rather than create a parallel one.
- **Existing prefs API** at [backend/app/api/telegram.py:60-69](backend/app/api/telegram.py#L60-L69) (`GET/PUT /api/telegram/prefs`) — this plan **removes** these two routes and serves the same data via the new `/api/notifications/preferences`. The Telegram-specific routes `/api/telegram/link` + `/api/telegram/unlink` remain.
- **Existing frontend type** [frontend/src/types/api.ts:224-229](frontend/src/types/api.ts#L224-L229) declares `NotificationPrefs { new_search_results, fav_sold, fav_price, fav_deleted }`. Plan **extends** this in place with `web_push_enabled` (not duplicated as a parallel `NotificationPreferencesDto`).
- **Existing frontend client** [frontend/src/api/client.ts](frontend/src/api/client.ts): bare `fetch()` + private `handleResponse<T>(res: Response)` (lines 19-31), one exported function per endpoint. There is **no** generic `apiFetch`. The new subscriptions module follows the same pattern. The two prefs functions (`getNotificationPrefs`, `updateNotificationPrefs`, lines 177-189) are retargeted to the new path inside `client.ts` itself.
- **TelegramPanel** ([frontend/src/components/TelegramPanel.tsx](frontend/src/components/TelegramPanel.tsx)) consumes only `getNotificationPrefs`/`updateNotificationPrefs` (lines 81-82, 180) — its UI iterates over the four telegram-relevant keys via the local `TOGGLE_ROWS` constant. After we extend `NotificationPrefs` with `web_push_enabled`, TelegramPanel keeps working unchanged: TypeScript reads the extra field and the UI ignores it because it's not in `TOGGLE_ROWS`.
- **No Alembic.** Schema evolution is inline in `backend/app/db.py:init_db()` — idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, runs on every startup. Plan follows this convention.
- **Test convention.** Tests in `backend/tests/test_<module>.py`. The existing fixture set in [backend/tests/conftest.py:301](backend/tests/conftest.py#L301) provides `authenticated_client` (a fresh user, dependency-overridden auth) and `authenticated_client_linked` (the same plus `telegram_chat_id=99999`). There is **no** `client`, `client_unauth`, `authed_user`, `other_user_with_sub` fixture today — Task 6 + Task 8 add the new fixtures explicitly. **Conftest also bootstraps the test DB schema** at lines 80-89 — when this plan adds `web_push_enabled` to `user_notification_prefs` and creates `push_subscriptions`, the conftest bootstrap must mirror those changes (Task 3 covers both).
- **REST module pattern**: [backend/app/api/telegram.py:6](backend/app/api/telegram.py#L6) imports `from app.api.deps import get_current_user`. The dependency is named `get_current_user` (defined at [backend/app/api/deps.py:12](backend/app/api/deps.py#L12)). Mirror exactly.
- **PWA infra is partially in place but legacy.** [frontend/public/sw.js](frontend/public/sw.js) exists (a static placeholder); [frontend/public/manifest.json](frontend/public/manifest.json) exists with `display:standalone` + 5 icon entries (4 PNG sizes including maskable variants + favicon SVG); icons live at `frontend/public/icons/{icon-192,icon-512,icon-maskable-192,icon-maskable-512,apple-touch-icon-180}.png`; [frontend/index.html:10](frontend/index.html#L10) has `<link rel="manifest" href="/manifest.json">` and apple-touch-icon meta; [frontend/src/main.tsx:27-31](frontend/src/main.tsx#L27-L31) registers `/sw.js` manually on window load. **All of this is replaced** in Task 11.5 — the manifest content is migrated into the VitePWA config, the static files are deleted, `index.html` link is removed, and `main.tsx` no longer registers anything (VitePWA's `injectRegister: 'auto'` does it).
- **Prod build path.** Production frontend image is built by [.github/workflows/deploy.yml](.github/workflows/deploy.yml) using [frontend/Dockerfile](frontend/Dockerfile). There is no `Dockerfile.prod`. `docker-compose.prod.yml` pulls a prebuilt image from GHCR. Task 20 wires the `VITE_VAPID_PUBLIC_KEY` build-arg through both `Dockerfile` and `deploy.yml`.
- **InstallPrompt** ([frontend/src/components/InstallPrompt.tsx](frontend/src/components/InstallPrompt.tsx)) provides the visual template: fixed `bottom-[72px]` (above mobile bottom nav), `sm:hidden`, `rgba(15,15,35,0.92)` glassmorphism, indigo accents, `localStorage` dismissal, local `isIos()` + `isStandalone()` helpers (extracted to `lib/pwa-detect.ts` in Task 11).
- **Mount point.** [frontend/src/App.tsx:223](frontend/src/App.tsx#L223) renders `<InstallPrompt />` inside the auth-gated `<AuthenticatedAppInner>`. `<FirstStartPushPrompt />` mounts directly after.
- **ProfilePage** ([frontend/src/pages/ProfilePage.tsx:236-240](frontend/src/pages/ProfilePage.tsx#L236-L240)) renders Column 2 as `<TelegramPanel /> {user.role === 'admin' && <LLMAdminPanel />}`. NotificationsPanel slots **above** TelegramPanel.

### Verified signatures (no false references)

```text
backend/app/notifications/base.py:19    class NotificationPlugin(ABC)
backend/app/notifications/base.py:23    async def is_configured(self) -> bool
backend/app/notifications/base.py:27    async def send(self, match: MatchResult) -> bool
backend/app/notifications/registry.py:35 notification_registry: NotificationRegistry  (singleton)
backend/app/api/deps.py:12               async def get_current_user(...) -> User
backend/app/api/telegram.py:6            from app.api.deps import get_current_user
backend/app/api/telegram.py:60-69        @router.get/put("/prefs") — REMOVED in Task 7.5
backend/app/db.py:11                     AsyncSessionLocal: async_sessionmaker
backend/app/db.py:18                     async def init_db() -> None  (idempotent migrations)
backend/app/db.py:177-186                CREATE TABLE user_notification_prefs (legacy 4 booleans + updated_at)
backend/app/db.py:254                    DROP COLUMN fav_indicator (PLAN-025)
backend/app/config.py:29                 class Settings(BaseSettings)
backend/app/config.py:87                 settings.telegram_enabled  (property)
backend/app/main.py:50-57                Plugin registration block in lifespan()
backend/app/main.py:101-109              fav_sweep scheduler — gated on telegram_enabled
backend/app/main.py:196-219              setWebhook block — gated on telegram_enabled
backend/tests/conftest.py:80-89          test DB bootstrap of user_notification_prefs (4 cols)
backend/tests/conftest.py:301-343        authenticated_client fixture (auth-overridden)
backend/tests/conftest.py:347-388        authenticated_client_linked fixture
frontend/src/api/client.ts:19            async function handleResponse<T>(res: Response)
frontend/src/api/client.ts:177-189       getNotificationPrefs / updateNotificationPrefs (RETARGETED)
frontend/src/types/api.ts:224-229        interface NotificationPrefs (EXTENDED with web_push_enabled)
frontend/src/components/TelegramPanel.tsx     unchanged behavior post-migration
frontend/src/components/InstallPrompt.tsx     visual template + helper source
frontend/src/components/InstallPrompt.tsx:13  isStandalone() — extracted in Task 11
frontend/src/components/InstallPrompt.tsx:20  isIos() — extracted in Task 11
frontend/src/main.tsx:27-31              manual SW registration — DELETED in Task 11.5
frontend/public/sw.js                    DELETED in Task 11.5
frontend/public/manifest.json            DELETED, content migrated into VitePWA config
frontend/public/icons/icon-{192,512}.png exists — referenced from VitePWA manifest + SW
frontend/public/icons/icon-maskable-{192,512}.png exists — preserved as maskable
frontend/public/icons/apple-touch-icon-180.png exists — kept (referenced from index.html)
frontend/index.html:10                   <link rel="manifest"> — DELETED in Task 11.5
frontend/Dockerfile                      single Dockerfile, no .prod variant
.github/workflows/deploy.yml             builds + pushes the frontend image
frontend/pnpm-lock.yaml                  untracked — DELETED in Task 10 (npm is canonical)
```

### Locked decisions (from discussion 2026-05-03)

| Topic | Decision |
|---|---|
| Scope | Single combined plan: backend plugin + REST + DB + frontend SW + UI + docs |
| Trigger | Exactly one — `MatchResult` from `app/services/search_matcher.py` (existing dispatch) |
| Routing | Push goes to all `push_subscriptions` rows belonging to `MatchResult.user_id` |
| Channel switch | `NOTIFICATION_CHANNEL` env, values `webpush` (default) / `telegram` / `both`; gated at registration time in `main.py` AND on `fav_sweep` + `setWebhook` (so `webpush` deployments don't half-run Telegram) |
| Telegram code | Plugin code untouched. `app/api/telegram.py` loses the `/prefs` GET+PUT routes (consolidation), `/link` + `/unlink` remain |
| Multi-device | Yes — N `push_subscriptions` rows per user, each with `device_label`, `last_used_at`, individually deletable |
| Prefs consolidation | Single source of truth at `/api/notifications/preferences`. Existing `NotificationPrefs` interface extended with `web_push_enabled`. `client.ts:getNotificationPrefs/updateNotificationPrefs` retargeted, function names preserved (no callsite churn). TelegramPanel unchanged |
| Permission UX | First-app-start banner after login; gated by `localStorage["rcn_notif_asked"]`. Mirror InstallPrompt visual shell |
| iOS | Web Push works only when PWA is installed (Safari 16.4+). Banner suppressed on iOS Safari without standalone; user sees InstallPrompt first. After install + relaunch, push prompt appears |
| VAPID storage | Env vars; local in `docker-compose.yml`, prod in GHA repo secrets, passed to frontend build via `VITE_VAPID_PUBLIC_KEY` build-arg in `frontend/Dockerfile`. Public key is also returned from `/api/notifications/vapid-public-key` so dev/local works without a build-time arg |
| Migrations | Inline in `backend/app/db.py:init_db()`. No Alembic. Test schema bootstrap mirrored in `conftest.py` |
| Tests | Backend: `backend/tests/test_*.py`, fixtures `authenticated_client` + new `seeded_*` factories. Frontend: co-located `__tests__/*.test.tsx`. Vitest globals stay enabled (matches existing config); tests still import `describe, it, expect, vi` explicitly per CLAUDE.md to be forward-compatible if globals are disabled later |
| Package manager | npm (canonical). `pnpm-lock.yaml` is removed; `package-lock.json` stays |
| Cost | Zero. `pywebpush` MIT, VAPID keypair generated locally via `npx web-push generate-vapid-keys`. No paid API calls |

### Reuse Check (verified by grep, 2026-05-03)

- **NotificationPlugin ABC** — exists. Reused unchanged.
- **`notification_registry`** — exists. Reused unchanged.
- **`user_notification_prefs` table** — exists. Extended in place.
- **`NotificationPrefs` TS interface** — exists at `types/api.ts:224-229`. Extended in place with `web_push_enabled: boolean`. **Reuse check:** Extends existing interface; not duplicated.
- **`getNotificationPrefs` / `updateNotificationPrefs`** — exist at `client.ts:177-189`. Retargeted to new path; function names preserved.
- **`InstallPrompt` shell + helpers** — `grep -rln "fixed bottom-" frontend/src` shows only `InstallPrompt.tsx`. **Extract** `isIos()` + `isStandalone()` + new `pushSupported()` into `frontend/src/lib/pwa-detect.ts` (consumed by InstallPrompt + FirstStartPushPrompt + the hook). **Reuse check:** Extracts shared helpers from pattern in `InstallPrompt.tsx`.
- **ProfilePage `cardStyle`** — local `const cardStyle` at [ProfilePage.tsx:76-82](frontend/src/pages/ProfilePage.tsx#L76-L82). NotificationsPanel re-declares the same style locally (same two-caller pattern as `TelegramPanel`). **Reuse check:** Reuses inline `cardStyle` shape; no extraction (YAGNI for two callers).
- **API client** — `frontend/src/api/client.ts` (bare `fetch` + `handleResponse`). **Reuse check:** New `notifications/api.ts` follows the same pattern (no `apiFetch` helper); prefs functions stay in `client.ts`.
- **Toggle/switch component** — `grep -rln "role=\"switch\"" frontend/src` shows the inline pattern in `TelegramPanel.tsx` (lines 308-338). NotificationsPanel reuses this exact toggle markup for its single `web_push_enabled` switch (consistency).
- **PWA manifest content** — already correct in `public/manifest.json`. **Reuse check:** Migrate verbatim into VitePWA `manifest:` config, including all five icon entries and the maskable purposes.

### Files structure (final)

**Backend (new):**
```
backend/app/notifications/web_push_plugin.py
backend/app/api/notifications.py
backend/tests/test_web_push_plugin.py
backend/tests/test_notifications_api.py
```

**Backend (modified):**
- `backend/requirements.txt` — add `pywebpush>=2.0`
- `backend/app/config.py` — add `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `NOTIFICATION_CHANNEL` + `web_push_enabled` and `notification_channel_normalized` properties
- `backend/app/models.py` — add `PushSubscription` ORM model
- `backend/app/db.py:init_db()` — append idempotent `CREATE TABLE IF NOT EXISTS push_subscriptions(...)` + `ALTER TABLE user_notification_prefs ADD COLUMN IF NOT EXISTS web_push_enabled BOOLEAN NOT NULL DEFAULT TRUE`
- `backend/app/main.py` — gate plugin registration on `NOTIFICATION_CHANNEL`; gate `fav_sweep` scheduler on channel; gate `setWebhook` block on channel; register `WebPushPlugin`; mount `notifications` router; import `WebPushPlugin` + router
- `backend/app/telegram/prefs.py` — extend `NotificationPrefs` dataclass + `get_prefs` SELECT to include `web_push_enabled`; extend `set_prefs` field whitelist
- `backend/app/api/telegram.py` — **remove** `GET /telegram/prefs` and `PUT /telegram/prefs` routes (lines 60-69) + the now-unused `PrefsBody`, `PrefsResponse`, `_prefs_to_response` helpers (lines 20-40); imports unchanged otherwise
- `backend/tests/conftest.py` — extend test schema bootstrap (Task 3 step) and add new fixtures `seeded_user_with_subs`, `other_user_with_sub` (Task 6 step)
- `backend/tests/test_telegram_api.py` — **remove** test cases that target the removed `/telegram/prefs` routes (Task 7.5 step)
- `docker-compose.yml` — add `VAPID_*`, `NOTIFICATION_CHANNEL` to backend service env (dev)
- `docker-compose.prod.yml` — mirror the same vars on prod backend service env
- `env.prod.example` — document new vars + the GitHub repo variable `VAPID_PUBLIC_KEY` for CI

**Frontend (new):**
```
frontend/src/sw.ts                                       (filename matches existing nginx /sw.js no-cache rule)
frontend/src/lib/pwa-detect.ts
frontend/src/lib/__tests__/pwa-detect.test.ts
frontend/src/notifications/api.ts                        (subscriptions + vapid only — prefs stay in client.ts)
frontend/src/notifications/device-label.ts
frontend/src/notifications/useWebPushSubscription.ts
frontend/src/notifications/FirstStartPushPrompt.tsx
frontend/src/notifications/__tests__/api.test.ts
frontend/src/notifications/__tests__/device-label.test.ts
frontend/src/notifications/__tests__/useWebPushSubscription.test.tsx
frontend/src/notifications/__tests__/FirstStartPushPrompt.test.tsx
frontend/src/components/NotificationsPanel.tsx
frontend/src/components/__tests__/NotificationsPanel.test.tsx
```

**Frontend (modified):**
- `frontend/package.json` — add `vite-plugin-pwa@^0.21`, `workbox-window@^7`, `workbox-precaching@^7` (via `npm install`)
- `frontend/package-lock.json` — regenerated by `npm install`
- `frontend/vite.config.ts` — wire `VitePWA({ strategies: 'injectManifest', srcDir: 'src', filename: 'sw.ts', registerType: 'autoUpdate', injectRegister: 'auto', manifest: <migrated content> })`
- `frontend/index.html` — remove `<link rel="manifest" href="/manifest.json">` (line 10); apple-touch-icon stays
- `frontend/src/main.tsx` — remove the `if ('serviceWorker' in navigator) {...}` block (lines 27-31)
- `frontend/src/components/InstallPrompt.tsx` — replace inline `isIos()` / `isStandalone()` with imports from `lib/pwa-detect.ts`
- `frontend/src/types/api.ts` — extend `NotificationPrefs` with `web_push_enabled: boolean`; add `PushSubscriptionDto`, `CreatePushSubscriptionDto`, `VapidKeyDto`
- `frontend/src/api/client.ts` — retarget `getNotificationPrefs` and `updateNotificationPrefs` from `/api/telegram/prefs` to `/api/notifications/preferences`
- `frontend/src/App.tsx:223` — mount `<FirstStartPushPrompt />` directly after `<InstallPrompt />`
- `frontend/src/pages/ProfilePage.tsx:238` — render `<NotificationsPanel />` above `<TelegramPanel />`
- `frontend/Dockerfile` — accept `ARG VITE_VAPID_PUBLIC_KEY` + `ENV` before `npm run build`
- `.github/workflows/deploy.yml` — pass `--build-arg VITE_VAPID_PUBLIC_KEY=${{ secrets.VAPID_PUBLIC_KEY }}` (or `${{ vars.VAPID_PUBLIC_KEY }}` — public key is fine as a non-secret repo variable)

**Frontend (deleted):**
- `frontend/public/sw.js` (legacy static SW — replaced by VitePWA-generated worker)
- `frontend/public/manifest.json` (content migrated into VitePWA config)
- `frontend/pnpm-lock.yaml` (npm is canonical)

**Docs (modified):**
- `docs/definition.md` §F5 — flip from "Future" to active feature
- `docs/architektur.md` — add §"Notification Channels" section
- `docs/limitations.md` — add entry "iOS Web Push requires PWA install"

---

## Tasks

> **Parallelism:** Tasks 1–9 (backend) parallel after Task 1. Tasks 10–22 (frontend) parallel after Task 10. Backend and frontend layers are fully independent — coder agents can run them simultaneously. Doc updates (Tasks 23–25) require backend + frontend done.
> **No BREAKs.** All tasks are non-destructive on shared/prod state and the coder can self-recover from any single-task failure (per `dglabs.writing-plans` BREAK policy).

---

### Task 1: Backend dependencies [ ]

**Files:** Modify `backend/requirements.txt`

**Step 1: Append `pywebpush`**

```text
pywebpush>=2.0
```

**Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(backend): add pywebpush for PLAN-027"
```

---

### Task 2: Backend config — VAPID + channel switch [ ]

**Depends on:** Task 1

**Files:** Modify `backend/app/config.py`

**Step 1: Add fields to `Settings`** (insert after the Telegram block, before `@property def telegram_enabled` at line 87):

```python
    # Web Push (VAPID) — required only when NOTIFICATION_CHANNEL includes "webpush"
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:marco.roth1983@googlemail.com"

    # Channel router: "webpush" (default) | "telegram" | "both"
    NOTIFICATION_CHANNEL: str = "webpush"

    @property
    def web_push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY and self.VAPID_SUBJECT)

    @property
    def notification_channel_normalized(self) -> str:
        v = (self.NOTIFICATION_CHANNEL or "").strip().lower()
        return v if v in {"webpush", "telegram", "both"} else "webpush"
```

**Step 2: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): add VAPID + NOTIFICATION_CHANNEL settings"
```

---

### Task 3: Backend schema — push_subscriptions + prefs column + test bootstrap [ ]

**Depends on:** Task 1

**Files:** Modify `backend/app/db.py`, `backend/app/models.py`, `backend/tests/conftest.py`

**Step 1: Append idempotent DDL** at the end of `init_db()` in `backend/app/db.py` (after the PLAN-025 block):

```python
        # PLAN-027: Web Push subscriptions + per-user toggle
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint     TEXT NOT NULL UNIQUE,
                p256dh       TEXT NOT NULL,
                auth         TEXT NOT NULL,
                user_agent   TEXT,
                device_label TEXT,
                last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user "
            "ON push_subscriptions (user_id)"
        ))
        await conn.execute(text(
            "ALTER TABLE user_notification_prefs "
            "ADD COLUMN IF NOT EXISTS web_push_enabled BOOLEAN NOT NULL DEFAULT TRUE"
        ))
```

**Step 2: Add ORM model** in `backend/app/models.py` (after `UserFavorite`):

```python
class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

**Step 3: Mirror schema changes in test bootstrap.** In `backend/tests/conftest.py`, three concrete edits:

1. **Manual-table drop list** (around lines 48-50). The existing block drops `user_notification_prefs` + `telegram_link_tokens` *before* `Base.metadata.drop_all()` because they are FK-referencing manual tables not in `Base.metadata`. `push_subscriptions` is also a manual table FK-referencing `users`, so it must join the drop list:

   ```python
   async with engine.begin() as conn:
       await conn.execute(text("DROP TABLE IF EXISTS push_subscriptions CASCADE"))
       await conn.execute(text("DROP TABLE IF EXISTS user_notification_prefs CASCADE"))
       await conn.execute(text("DROP TABLE IF EXISTS telegram_link_tokens CASCADE"))
       await conn.run_sync(Base.metadata.drop_all)
       await conn.run_sync(Base.metadata.create_all)
   ```

2. **`user_notification_prefs` CREATE** (around lines 80-89): add `web_push_enabled BOOLEAN NOT NULL DEFAULT TRUE,` between `fav_deleted` and `updated_at`. Append the `push_subscriptions` CREATE + index that prod `init_db` uses (Step 1's snippet).

3. **`_patch_targets` list** (around lines 132-138). The autouse `patch_async_session_local` fixture redirects `AsyncSessionLocal` to the test engine for every module that does `from app.db import AsyncSessionLocal`. Task 5's `web_push_plugin.py` imports `AsyncSessionLocal` at module scope, so it must be added:

   ```python
   _patch_targets = [
       "app.telegram.bot",
       "app.telegram.link",
       "app.telegram.prefs",
       "app.telegram.plugin",
       "app.telegram.fav_sweep",
       "app.notifications.web_push_plugin",  # PLAN-027
   ]
   ```

The test schema section after edit 2 becomes:

```python
        # PLAN-019: user_notification_prefs table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_notification_prefs (
                user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                new_search_results BOOLEAN NOT NULL DEFAULT TRUE,
                fav_sold           BOOLEAN NOT NULL DEFAULT TRUE,
                fav_price          BOOLEAN NOT NULL DEFAULT TRUE,
                fav_deleted        BOOLEAN NOT NULL DEFAULT TRUE,
                web_push_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        # PLAN-027: push_subscriptions table (mirror of init_db)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint     TEXT NOT NULL UNIQUE,
                p256dh       TEXT NOT NULL,
                auth         TEXT NOT NULL,
                user_agent   TEXT,
                device_label TEXT,
                last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user ON push_subscriptions (user_id)"
        ))
```

**Step 4: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/tests/conftest.py
git commit -m "feat(db): add push_subscriptions + web_push_enabled (prod + test schema)"
```

---

### Task 4: Extend prefs dataclass with web_push_enabled [ ]

**Depends on:** Task 3

**Files:** Modify `backend/app/telegram/prefs.py`

**Step 1: Add field to dataclass + select + whitelist**

Change `NotificationPrefs`:

```python
@dataclass(frozen=True)
class NotificationPrefs:
    user_id: int
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    web_push_enabled: bool
```

Update `get_prefs` SELECT:

```python
        result = await session.execute(
            text("""
                SELECT new_search_results, fav_sold, fav_price, fav_deleted, web_push_enabled
                FROM user_notification_prefs WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        r = result.one()
        await session.commit()
    return NotificationPrefs(user_id, r[0], r[1], r[2], r[3], r[4])
```

Update `set_prefs` field tuple:

```python
    for field in ("new_search_results", "fav_sold", "fav_price", "fav_deleted", "web_push_enabled"):
```

**Step 2: Commit**

```bash
git add backend/app/telegram/prefs.py
git commit -m "feat(prefs): add web_push_enabled toggle to NotificationPrefs"
```

---

### Task 5: WebPushPlugin implementation [ ]

**Depends on:** Tasks 2, 3, 4

**Files:** Create `backend/app/notifications/web_push_plugin.py`

**Step 1: Implement plugin**

```python
"""WebPushPlugin — delivers MatchResult digests as Web Push notifications."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pywebpush import WebPushException, webpush
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications.base import MatchResult, NotificationPlugin
from app.telegram import prefs as prefs_module

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Subscription:
    id: int
    endpoint: str
    p256dh: str
    auth: str


def _build_payload(match: MatchResult) -> dict:
    title = f"Neue Treffer: {match.search_name}"
    top = match.new_listing_titles[:3]
    body_lines = list(top)
    if match.total_new > len(top):
        body_lines.append(f"… und {match.total_new - len(top)} weitere")
    return {
        "title": title,
        "body": "\n".join(body_lines),
        "url": f"{settings.PUBLIC_BASE_URL}/?saved_search={match.saved_search_id}",
        "tag": f"saved-search-{match.saved_search_id}",
    }


class WebPushPlugin(NotificationPlugin):
    """Sends a digest payload to every push_subscription belonging to the user."""

    async def is_configured(self) -> bool:
        # Channel gating happens at registration time in main.py.
        # Here we only verify VAPID keys are loaded.
        return settings.web_push_enabled

    async def send(self, match: MatchResult) -> bool:
        # 1. Per-user opt-in
        p = await prefs_module.get_prefs(match.user_id)
        if not p.web_push_enabled or not p.new_search_results:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d skipped (pref off)",
                match.saved_search_id,
                match.user_id,
            )
            return False

        # 2. Load subscriptions
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
                        "WHERE user_id = :uid"
                    ),
                    {"uid": match.user_id},
                )
            ).all()
        subs = [_Subscription(r[0], r[1], r[2], r[3]) for r in rows]
        if not subs:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d skipped (no subscriptions)",
                match.saved_search_id,
                match.user_id,
            )
            return False

        # 3. Send to each subscription
        payload = json.dumps(_build_payload(match))
        any_ok = False
        stale_ids: list[int] = []
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": settings.VAPID_SUBJECT},
                )
                any_ok = True
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None) if exc.response else None
                if status in (404, 410):
                    stale_ids.append(sub.id)
                    logger.info(
                        "web_push.plugin: stale subscription id=%d (status=%s) — removing",
                        sub.id,
                        status,
                    )
                else:
                    logger.warning(
                        "web_push.plugin: send failed sub_id=%d status=%s err=%s",
                        sub.id,
                        status,
                        exc,
                    )

        # 4. Garbage-collect stale subscriptions
        if stale_ids:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("DELETE FROM push_subscriptions WHERE id = ANY(:ids)"),
                    {"ids": stale_ids},
                )
                await session.commit()

        # 5. Touch last_used_at on success
        if any_ok:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE push_subscriptions SET last_used_at = now() "
                        "WHERE user_id = :uid"
                    ),
                    {"uid": match.user_id},
                )
                await session.commit()

        return any_ok
```

**Step 2: Commit**

```bash
git add backend/app/notifications/web_push_plugin.py
git commit -m "feat(notifications): add WebPushPlugin"
```

---

### Task 6: WebPushPlugin tests + new fixtures [ ]

**Depends on:** Task 5

**Files:** Create `backend/tests/test_web_push_plugin.py`, modify `backend/tests/conftest.py`

**Step 1: New fixtures in `conftest.py`** (append after `db_listing` fixture):

```python
from dataclasses import dataclass as _dc  # already imported above; ensure single import


@_dc
class _UserWithSubs:
    user_id: int
    sub_ids: list[int]


@pytest_asyncio.fixture()
async def seeded_user_with_subs(db_session: AsyncSession) -> _UserWithSubs:
    """Insert a user (id captured) and two push_subscription rows."""
    from sqlalchemy import text as _text  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved)
            VALUES ('seed-subs-google', 'seed_subs@example.com', 'Seed Subs', TRUE)
            RETURNING id
        """)
    )
    user_id = (
        await db_session.execute(_text("SELECT id FROM users WHERE google_id = 'seed-subs-google'"))
    ).scalar_one()
    sub_ids: list[int] = []
    for endpoint in ("https://fcm.example/1", "https://fcm.example/2"):
        row = await db_session.execute(
            _text("""
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, device_label)
                VALUES (:uid, :ep, 'P', 'A', 'Test Device')
                RETURNING id
            """),
            {"uid": user_id, "ep": endpoint},
        )
        sub_ids.append(row.scalar_one())
    await db_session.commit()
    return _UserWithSubs(user_id=user_id, sub_ids=sub_ids)


@pytest_asyncio.fixture()
async def other_user_with_sub(db_session: AsyncSession) -> _UserWithSubs:
    """Insert a *different* user + one subscription — used for ownership-isolation tests."""
    from sqlalchemy import text as _text  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved)
            VALUES ('other-subs-google', 'other_subs@example.com', 'Other', TRUE)
        """)
    )
    user_id = (
        await db_session.execute(_text("SELECT id FROM users WHERE google_id = 'other-subs-google'"))
    ).scalar_one()
    row = await db_session.execute(
        _text("""
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, device_label)
            VALUES (:uid, 'https://other-user-endpoint', 'P', 'A', 'Other Device')
            RETURNING id
        """),
        {"uid": user_id},
    )
    sub_id = row.scalar_one()
    await db_session.commit()
    return _UserWithSubs(user_id=user_id, sub_ids=[sub_id])
```

**Step 2: Plugin tests** — `backend/tests/test_web_push_plugin.py`:

```python
"""Tests for WebPushPlugin — mocks pywebpush, asserts behavior with real DB rows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pywebpush import WebPushException
from sqlalchemy import text

from app.notifications.base import MatchResult
from app.notifications.web_push_plugin import WebPushPlugin


def _match(user_id: int) -> MatchResult:
    return MatchResult(
        saved_search_id=1,
        search_name="Wing 2.5m",
        user_id=user_id,
        new_listing_ids=[10, 11, 12],
        new_listing_titles=["A", "B", "C"],
        total_new=3,
    )


@pytest.mark.asyncio
async def test_is_configured_false_when_no_vapid(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    assert await WebPushPlugin().is_configured() is False


@pytest.mark.asyncio
async def test_is_configured_true_when_vapid_set(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:x@y")
    assert await WebPushPlugin().is_configured() is True


@pytest.mark.asyncio
async def test_send_returns_false_when_pref_disabled(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    fake = MagicMock(web_push_enabled=False, new_search_results=True)
    monkeypatch.setattr(mod.prefs_module, "get_prefs", AsyncMock(return_value=fake))
    assert await WebPushPlugin().send(_match(seeded_user_with_subs.user_id)) is False


@pytest.mark.asyncio
async def test_send_returns_false_when_user_has_no_subscriptions(monkeypatch, db_user):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    assert await WebPushPlugin().send(_match(db_user.id)) is False


@pytest.mark.asyncio
async def test_send_calls_webpush_for_each_subscription(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    calls: list[dict] = []
    monkeypatch.setattr(mod, "webpush", lambda **kw: calls.append(kw))
    ok = await WebPushPlugin().send(_match(seeded_user_with_subs.user_id))
    assert ok is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_send_deletes_subscription_on_410_gone(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    response = MagicMock(status_code=410)
    def raise_gone(**_):
        raise WebPushException("gone", response=response)
    monkeypatch.setattr(mod, "webpush", raise_gone)
    await WebPushPlugin().send(_match(seeded_user_with_subs.user_id))
    rows = await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )
    assert rows.scalar_one() == 0


@pytest.mark.asyncio
async def test_send_deletes_subscription_on_404(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    response = MagicMock(status_code=404)
    def raise_404(**_):
        raise WebPushException("not found", response=response)
    monkeypatch.setattr(mod, "webpush", raise_404)
    await WebPushPlugin().send(_match(seeded_user_with_subs.user_id))
    rows = await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )
    assert rows.scalar_one() == 0


@pytest.mark.asyncio
async def test_send_returns_false_when_all_endpoints_fail_with_500(
    monkeypatch, seeded_user_with_subs
):
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    response = MagicMock(status_code=500)
    def raise_500(**_):
        raise WebPushException("oops", response=response)
    monkeypatch.setattr(mod, "webpush", raise_500)
    assert await WebPushPlugin().send(_match(seeded_user_with_subs.user_id)) is False
```

**Step 3: Commit**

```bash
git add backend/tests/test_web_push_plugin.py backend/tests/conftest.py
git commit -m "test(notifications): cover WebPushPlugin send paths + new fixtures"
```

---

### Task 7: Notifications REST API [ ]

**Depends on:** Tasks 2, 3, 4

**Files:** Create `backend/app/api/notifications.py`

**Step 1: Implement router**

```python
"""REST endpoints for Web Push subscriptions, preferences, and VAPID public key."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.models import User
from app.telegram import prefs as prefs_module

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---------- Models ----------

class _Keys(BaseModel):
    p256dh: str
    auth: str


class CreateSubscriptionDto(BaseModel):
    endpoint: str
    keys: _Keys
    user_agent: str | None = Field(default=None, max_length=512)
    device_label: str | None = Field(default=None, max_length=120)


class PushSubscriptionDto(BaseModel):
    id: int
    endpoint: str
    device_label: str | None
    user_agent: str | None
    last_used_at: datetime
    created_at: datetime


class PreferencesDto(BaseModel):
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    web_push_enabled: bool


class UpdatePreferencesDto(BaseModel):
    new_search_results: bool | None = None
    fav_sold: bool | None = None
    fav_price: bool | None = None
    fav_deleted: bool | None = None
    web_push_enabled: bool | None = None


class VapidKeyDto(BaseModel):
    public_key: str


def _to_prefs_dto(p: prefs_module.NotificationPrefs) -> PreferencesDto:
    return PreferencesDto(
        new_search_results=p.new_search_results,
        fav_sold=p.fav_sold,
        fav_price=p.fav_price,
        fav_deleted=p.fav_deleted,
        web_push_enabled=p.web_push_enabled,
    )


# ---------- VAPID ----------

@router.get("/vapid-public-key", response_model=VapidKeyDto)
async def get_vapid_public_key() -> VapidKeyDto:
    if not settings.web_push_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Web Push not configured")
    return VapidKeyDto(public_key=settings.VAPID_PUBLIC_KEY)


# ---------- Subscriptions ----------

@router.get("/subscriptions", response_model=list[PushSubscriptionDto])
async def list_subscriptions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PushSubscriptionDto]:
    rows = (
        await session.execute(
            text(
                "SELECT id, endpoint, device_label, user_agent, last_used_at, created_at "
                "FROM push_subscriptions WHERE user_id = :uid ORDER BY last_used_at DESC"
            ),
            {"uid": user.id},
        )
    ).all()
    return [
        PushSubscriptionDto(
            id=r[0], endpoint=r[1], device_label=r[2],
            user_agent=r[3], last_used_at=r[4], created_at=r[5],
        )
        for r in rows
    ]


@router.post("/subscriptions", response_model=PushSubscriptionDto, status_code=201)
async def create_subscription(
    dto: CreateSubscriptionDto,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PushSubscriptionDto:
    # ON CONFLICT (endpoint) — idempotent re-subscribe.
    # Re-assigning user_id is intentional: a single browser endpoint moving between
    # accounts on the same device is legitimate (single-user system, but the table
    # is structured generically).
    await session.execute(
        text("""
            INSERT INTO push_subscriptions
                (user_id, endpoint, p256dh, auth, user_agent, device_label, last_used_at)
            VALUES (:uid, :ep, :p, :a, :ua, :lbl, now())
            ON CONFLICT (endpoint) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth,
                user_agent = EXCLUDED.user_agent,
                device_label = EXCLUDED.device_label,
                last_used_at = now()
        """),
        {
            "uid": user.id, "ep": dto.endpoint,
            "p": dto.keys.p256dh, "a": dto.keys.auth,
            "ua": dto.user_agent, "lbl": dto.device_label,
        },
    )
    await session.commit()
    row = (
        await session.execute(
            text(
                "SELECT id, endpoint, device_label, user_agent, last_used_at, created_at "
                "FROM push_subscriptions WHERE endpoint = :ep"
            ),
            {"ep": dto.endpoint},
        )
    ).one()
    return PushSubscriptionDto(
        id=row[0], endpoint=row[1], device_label=row[2],
        user_agent=row[3], last_used_at=row[4], created_at=row[5],
    )


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        text("DELETE FROM push_subscriptions WHERE id = :id AND user_id = :uid"),
        {"id": sub_id, "uid": user.id},
    )
    await session.commit()
    if (result.rowcount or 0) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


# ---------- Preferences (consolidated) ----------

@router.get("/preferences", response_model=PreferencesDto)
async def get_preferences(user: User = Depends(get_current_user)) -> PreferencesDto:
    return _to_prefs_dto(await prefs_module.get_prefs(user.id))


@router.put("/preferences", response_model=PreferencesDto)
async def put_preferences(
    dto: UpdatePreferencesDto,
    user: User = Depends(get_current_user),
) -> PreferencesDto:
    patch = {k: v for k, v in dto.model_dump(exclude_unset=True).items() if v is not None}
    return _to_prefs_dto(await prefs_module.set_prefs(user.id, **patch))
```

**Step 2: Commit**

```bash
git add backend/app/api/notifications.py
git commit -m "feat(api): notifications router — subscriptions + preferences + vapid key"
```

---

### Task 7.5: Remove legacy /api/telegram/prefs routes [ ]

**Depends on:** Task 7

**Files:** Modify `backend/app/api/telegram.py`, modify `backend/tests/test_telegram_api.py`

**Step 1: Strip prefs from `app/api/telegram.py`**

Delete:
- `class PrefsBody(BaseModel): ...` (lines 20-24)
- `class PrefsResponse(BaseModel): ...` (lines 27-31)
- `def _prefs_to_response(...)` (lines 34-40)
- `@router.get("/prefs", ...) async def get_prefs_endpoint(...)` (lines 60-62)
- `@router.put("/prefs", ...) async def put_prefs(...)` (lines 65-69)

Also remove the now-unused `from app.telegram import link, prefs` → keep only `link` (or remove `prefs` from the tuple).

Final `app/api/telegram.py` keeps only: `LinkResponse`, `POST /link`, `POST /unlink`. The `from app.telegram import link, prefs` import becomes `from app.telegram import link`.

**Step 2: Strip prefs tests from `test_telegram_api.py`**

Open `backend/tests/test_telegram_api.py` and delete every test whose name contains `prefs` or whose body posts/gets `/api/telegram/prefs`. Equivalent coverage is added in Task 8 against `/api/notifications/preferences`.

**Step 3: Commit**

```bash
git add backend/app/api/telegram.py backend/tests/test_telegram_api.py
git commit -m "refactor(api): drop /telegram/prefs (moved to /notifications/preferences)"
```

---

### Task 8: REST API tests [ ]

**Depends on:** Tasks 7, 7.5

**Files:** Create `backend/tests/test_notifications_api.py`

**Step 1: Tests** — use the existing `authenticated_client` + new `other_user_with_sub` fixtures. `authenticated_client` impersonates the `auth_client@example.com` user via dependency-override; subscriptions created through its `POST` calls are owned by that user. `seeded_user_with_subs` and `other_user_with_sub` create *separate* users — `other_user_with_sub` is used here only for the ownership-isolation negative case (its sub_id should be invisible to the authenticated client and unauthorized to delete).

```python
"""Tests for /api/notifications/* — uses authenticated_client fixture from conftest."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_get_vapid_public_key_returns_key(api_client, monkeypatch):
    """api_client is unauthenticated for the prefs/subs routes but the VAPID key is public."""
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "BPub")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:x@y")
    r = await api_client.get("/api/notifications/vapid-public-key")
    assert r.status_code == 200
    assert r.json() == {"public_key": "BPub"}


@pytest.mark.asyncio
async def test_get_vapid_public_key_503_when_unconfigured(api_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    r = await api_client.get("/api/notifications/vapid-public-key")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_subscription_creates_row(authenticated_client):
    body = {
        "endpoint": "https://fcm.googleapis.com/abc",
        "keys": {"p256dh": "P1", "auth": "A1"},
        "user_agent": "test-ua",
        "device_label": "Pixel 8",
    }
    r = await authenticated_client.post("/api/notifications/subscriptions", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["endpoint"] == body["endpoint"]
    assert data["device_label"] == "Pixel 8"


@pytest.mark.asyncio
async def test_post_subscription_upserts_existing_endpoint(authenticated_client):
    body = {"endpoint": "https://fcm/abc", "keys": {"p256dh": "P", "auth": "A"}}
    a = await authenticated_client.post("/api/notifications/subscriptions", json=body)
    b = await authenticated_client.post(
        "/api/notifications/subscriptions",
        json={**body, "device_label": "renamed"},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["device_label"] == "renamed"


@pytest.mark.asyncio
async def test_get_subscriptions_returns_only_owned(
    authenticated_client, other_user_with_sub
):
    # Create one subscription owned by the authenticated user
    await authenticated_client.post(
        "/api/notifications/subscriptions",
        json={"endpoint": "https://fcm/owned", "keys": {"p256dh": "P", "auth": "A"}},
    )
    r = await authenticated_client.get("/api/notifications/subscriptions")
    assert r.status_code == 200
    endpoints = [s["endpoint"] for s in r.json()]
    assert "https://fcm/owned" in endpoints
    assert "https://other-user-endpoint" not in endpoints


@pytest.mark.asyncio
async def test_delete_subscription_removes_row(authenticated_client):
    create = await authenticated_client.post(
        "/api/notifications/subscriptions",
        json={"endpoint": "https://fcm/x", "keys": {"p256dh": "P", "auth": "A"}},
    )
    sub_id = create.json()["id"]
    r = await authenticated_client.delete(f"/api/notifications/subscriptions/{sub_id}")
    assert r.status_code == 204
    r2 = await authenticated_client.get("/api/notifications/subscriptions")
    assert all(s["id"] != sub_id for s in r2.json())


@pytest.mark.asyncio
async def test_delete_subscription_404_when_not_owned(
    authenticated_client, other_user_with_sub
):
    r = await authenticated_client.delete(
        f"/api/notifications/subscriptions/{other_user_with_sub.sub_ids[0]}"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_preferences_creates_default(authenticated_client):
    r = await authenticated_client.get("/api/notifications/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["web_push_enabled"] is True
    assert body["new_search_results"] is True
    # Telegram-side prefs are still served from this endpoint:
    assert "fav_sold" in body and "fav_price" in body and "fav_deleted" in body


@pytest.mark.asyncio
async def test_put_preferences_updates_web_push_enabled(authenticated_client):
    r = await authenticated_client.put(
        "/api/notifications/preferences",
        json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["web_push_enabled"] is False


@pytest.mark.asyncio
async def test_put_preferences_partial_does_not_clobber_other_fields(authenticated_client):
    # First set fav_sold=False so we can detect any unintended overwrite
    await authenticated_client.put(
        "/api/notifications/preferences", json={"fav_sold": False},
    )
    # Now PUT only web_push_enabled
    r = await authenticated_client.put(
        "/api/notifications/preferences", json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["fav_sold"] is False  # unchanged


@pytest.mark.asyncio
async def test_unauthenticated_subscriptions_returns_401(api_client):
    """api_client has _fake_user override active — so this is actually authenticated.
    Replicate an unauthenticated client by clearing the override before the request."""
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides.pop(get_current_user, None)
    try:
        r = await api_client.get("/api/notifications/subscriptions")
        assert r.status_code == 401
    finally:
        # Re-install for any later tests that share this client
        pass
```

**Step 2: Commit**

```bash
git add backend/tests/test_notifications_api.py
git commit -m "test(api): cover /api/notifications/* endpoints"
```

---

### Task 9: Wire plugin + router + channel gates into main.py + docker-compose [ ]

**Depends on:** Tasks 5, 7, 7.5

**Files:** Modify `backend/app/main.py`, `docker-compose.yml`, `env.prod.example`

**Step 1: Update main.py — imports + lifespan + channel gates**

Add near existing notification imports (around line 25):

```python
from app.api.notifications import router as notifications_router
from app.notifications.web_push_plugin import WebPushPlugin
```

Replace the existing plugin-registration block ([main.py:50-57](backend/app/main.py#L50-L57)):

```python
    # Register notification plugins — guard against hot-reload duplicates.
    # Channel routing: NOTIFICATION_CHANNEL ∈ {webpush, telegram, both} decides which plugins run.
    if not notification_registry._plugins:
        notification_registry.register(LogPlugin())

    channel = settings.notification_channel_normalized
    telegram_active = channel in {"telegram", "both"} and settings.telegram_enabled
    webpush_active = channel in {"webpush", "both"} and settings.web_push_enabled

    if telegram_active and not any(
        isinstance(p, TelegramPlugin) for p in notification_registry._plugins
    ):
        notification_registry.register(TelegramPlugin())
        logger.info("telegram.plugin: registered (channel=%s)", channel)

    if webpush_active and not any(
        isinstance(p, WebPushPlugin) for p in notification_registry._plugins
    ):
        notification_registry.register(WebPushPlugin())
        logger.info("web_push.plugin: registered (channel=%s)", channel)
```

Replace the `fav_sweep` block ([main.py:101-109](backend/app/main.py#L101-L109)):

```python
    if telegram_active:
        from app.telegram import fav_sweep  # local import — only when telegram is active
        scheduler.add_job(
            fav_sweep.run_fav_status_sweep,
            trigger="interval",
            minutes=settings.TELEGRAM_FAV_SWEEP_INTERVAL_MIN,
            id="telegram_fav_status_sweep",
            replace_existing=True,
        )
```

Replace the `setWebhook` block ([main.py:196-219](backend/app/main.py#L196-L219)). Change the outer condition from `if settings.telegram_enabled:` to `if telegram_active:` (the rest of the body stays as written). The existing else-branch's log message stays informative for the `webpush`-only case.

Add the router include after the existing telegram webhook include (around line 239):

```python
app.include_router(notifications_router, prefix="/api")
```

**Step 2: docker-compose.yml (dev) — backend service env block**

Add to the backend service `environment:`:

```yaml
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY:-}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY:-}
      VAPID_SUBJECT: ${VAPID_SUBJECT:-mailto:marco.roth1983@googlemail.com}
      NOTIFICATION_CHANNEL: ${NOTIFICATION_CHANNEL:-webpush}
```

**Step 2b: docker-compose.prod.yml — backend service env block**

The prod compose file (lines 25-34) has its own `environment:` block (no inheritance from dev). Without this step, prod boots with empty VAPID, `WebPushPlugin.is_configured()` returns False, and push delivery silently fails on the VPS. Add the same four vars:

```yaml
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/rcscout
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
      JWT_SECRET: ${JWT_SECRET}
      PUBLIC_BASE_URL: https://rcn-scout.d2x-labs.de
      FRONTEND_URL: https://rcn-scout.d2x-labs.de
      ALLOWED_ORIGINS: https://rcn-scout.d2x-labs.de
      COOKIE_SECURE: "true"
      SCRAPE_DELAY: "1.0"
      # PLAN-027: Web Push
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_SUBJECT: ${VAPID_SUBJECT:-mailto:marco.roth1983@googlemail.com}
      NOTIFICATION_CHANNEL: ${NOTIFICATION_CHANNEL:-webpush}
```

The values come from the VPS-side `.env` file (sourced by `docker compose -f docker-compose.prod.yml up`). Document this in `env.prod.example` (Step 3).

The frontend image build-arg is wired in Task 20; local dev reads the public key from the API at runtime.

**Step 3: env.prod.example — append**

```bash
# Web Push (PLAN-027)
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:marco.roth1983@googlemail.com
NOTIFICATION_CHANNEL=webpush
```

**Step 4: Commit**

```bash
git add backend/app/main.py docker-compose.yml docker-compose.prod.yml env.prod.example
git commit -m "feat(boot): register WebPushPlugin + gate telegram side-effects on channel"
```

---

### Task 10: Frontend dependencies + lockfile cleanup [ ]

**Files:** Modify `frontend/package.json`, regenerate `frontend/package-lock.json`, delete `frontend/pnpm-lock.yaml`

**Step 1: Install via npm**

```bash
cd frontend
npm install -D vite-plugin-pwa@^0.21
npm install workbox-window@^7 workbox-precaching@^7
```

**Step 2: Remove pnpm lockfile** (was untracked; npm is canonical for this repo):

```bash
rm frontend/pnpm-lock.yaml
```

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git rm --ignore-unmatch frontend/pnpm-lock.yaml
git commit -m "chore(frontend): add vite-plugin-pwa + workbox; pin to npm"
```

---

### Task 11: PWA detection helpers [ ]

**Depends on:** Task 10

**Files:** Create `frontend/src/lib/pwa-detect.ts`, create `frontend/src/lib/__tests__/pwa-detect.test.ts`, modify `frontend/src/components/InstallPrompt.tsx`

**Step 1: Extract helpers**

`frontend/src/lib/pwa-detect.ts`:

```typescript
export function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

export function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}
```

**Step 2: Update InstallPrompt to import**

In `frontend/src/components/InstallPrompt.tsx`, delete the local `isStandalone` and `isIos` helpers (lines 13-22) and add:

```typescript
import { isIos, isStandalone } from '../lib/pwa-detect';
```

**Step 3: Tests** — `frontend/src/lib/__tests__/pwa-detect.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest';
import { isIos, isStandalone, pushSupported } from '../pwa-detect';

afterEach(() => vi.unstubAllGlobals());

describe('pwa-detect', () => {
  it('isIos true for iPhone UA', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS …)' });
    expect(isIos()).toBe(true);
  });

  it('isIos false for Android UA', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Linux; Android 13)' });
    expect(isIos()).toBe(false);
  });

  it('isStandalone reads display-mode media query', () => {
    vi.stubGlobal('window', {
      ...window,
      matchMedia: () => ({ matches: true } as MediaQueryList),
    });
    vi.stubGlobal('navigator', {});
    expect(isStandalone()).toBe(true);
  });

  it('pushSupported false when serviceWorker missing', () => {
    vi.stubGlobal('navigator', {});
    expect(pushSupported()).toBe(false);
  });

  it('pushSupported true when SW + PushManager + Notification present', () => {
    vi.stubGlobal('navigator', { serviceWorker: {} });
    vi.stubGlobal('window', { ...window, PushManager: class {}, Notification: class {} });
    expect(pushSupported()).toBe(true);
  });
});
```

**Step 4: Commit**

```bash
git add frontend/src/lib/pwa-detect.ts frontend/src/lib/__tests__/pwa-detect.test.ts frontend/src/components/InstallPrompt.tsx
git commit -m "refactor(frontend): extract PWA detection helpers"
```

---

### Task 11.5: Remove legacy PWA artifacts [ ]

**Depends on:** Task 10

**Files:** Modify `frontend/src/main.tsx`, modify `frontend/index.html`, delete `frontend/public/sw.js`, delete `frontend/public/manifest.json`

**Step 1: Remove manual SW registration in `main.tsx`**

Delete lines 27-31:

```typescript
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
  })
}
```

**Step 2: Remove manifest link in `index.html`**

In `frontend/index.html` line 10, delete:

```html
<link rel="manifest" href="/manifest.json">
```

The apple-touch-icon line and the iOS PWA meta tags (capable, status-bar-style, title) **stay** — they are read by Safari independently of the manifest. VitePWA injects its own `<link rel="manifest">` referencing the generated manifest at build time.

**Step 3: Delete the static legacy files**

```bash
rm frontend/public/sw.js
rm frontend/public/manifest.json
```

The icons in `frontend/public/icons/` **stay** — they are referenced from the new VitePWA `manifest:` config in Task 12.

**Step 4: Commit**

```bash
git rm frontend/public/sw.js frontend/public/manifest.json
git add frontend/src/main.tsx frontend/index.html
git commit -m "chore(pwa): remove legacy sw.js + manifest.json (replaced by vite-plugin-pwa)"
```

---

### Task 12: Vite PWA config [ ]

**Depends on:** Tasks 10, 11.5

**Files:** Modify `frontend/vite.config.ts`

**Step 1: Replace vite.config.ts**

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      // Output file: sw.js. Filename matches the existing nginx no-cache rule
      // (frontend/nginx.conf:14 `location = /sw.js`) — do not rename without
      // updating that rule, otherwise SW updates cache aggressively in prod.
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      manifest: {
        name: 'RC Scout',
        short_name: 'RC Scout',
        description: 'Dein persönlicher RC-Flohmarkt-Scout',
        start_url: '/',
        display: 'standalone',
        background_color: '#0f0f23',
        theme_color: '#0f0f23',
        orientation: 'portrait',
        icons: [
          { src: '/favicon.svg',                  sizes: 'any',     type: 'image/svg+xml' },
          { src: '/icons/icon-192.png',           sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png',           sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-maskable-192.png',  sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/icons/icon-maskable-512.png',  sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://localhost:8002',
        changeOrigin: true,
      },
    },
    watch: { usePolling: true },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
});
```

**Step 2: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "feat(frontend): wire vite-plugin-pwa with manifest migrated from public/"
```

---

### Task 13: Service worker (push + notificationclick) [ ]

**Depends on:** Task 10

**Files:** Create `frontend/src/sw.ts` (path matches `vite-plugin-pwa` `filename: 'sw.ts'` in Task 12 → output `dist/sw.js`, which the existing nginx no-cache rule already targets)

**Step 1: Implement service worker**

```typescript
/// <reference lib="webworker" />
import { precacheAndRoute } from 'workbox-precaching';

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

interface PushPayload {
  title: string;
  body: string;
  url?: string;
  tag?: string;
}

self.addEventListener('push', (event) => {
  let data: PushPayload = { title: 'RC Scout', body: 'Neue Treffer' };
  try {
    if (event.data) data = { ...data, ...(event.data.json() as PushPayload) };
  } catch {
    if (event.data) data.body = event.data.text();
  }

  const options: NotificationOptions = {
    body: data.body,
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.tag,
    data: { url: data.url ?? '/' },
  };

  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | undefined)?.url ?? '/';
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const c of all) {
        if (c.url.includes(url) && 'focus' in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })(),
  );
});
```

**Step 2: Commit**

```bash
git add frontend/src/sw.ts
git commit -m "feat(sw): push + notificationclick handlers"
```

---

### Task 14: Notifications API client + types + retarget existing prefs functions [ ]

**Depends on:** Task 10

**Files:** Create `frontend/src/notifications/api.ts`, modify `frontend/src/types/api.ts`, modify `frontend/src/api/client.ts`

**Step 1: Extend `NotificationPrefs` + add new DTOs in `types/api.ts`**

Find the existing `NotificationPrefs` interface (lines 224-229) and add `web_push_enabled`:

```typescript
export interface NotificationPrefs {
  new_search_results: boolean;
  fav_sold: boolean;
  fav_price: boolean;
  fav_deleted: boolean;
  web_push_enabled: boolean;
}
```

**Step 1b: Update existing test fixture literal**

`frontend/src/components/__tests__/TelegramPanel.test.tsx:39-44` declares a typed `defaultPrefs: NotificationPrefs` literal that does NOT include `web_push_enabled`. After the interface change in Step 1, `tsc -b` (run as part of `npm run build` per `package.json:8`) will fail. Add the field:

```typescript
const defaultPrefs: NotificationPrefs = {
  new_search_results: true,
  fav_sold: true,
  fav_price: false,
  fav_deleted: false,
  web_push_enabled: true,
};
```

(No assertion changes needed — TelegramPanel.tsx iterates only over `TOGGLE_ROWS`, which doesn't include `web_push_enabled`, so the new field is simply present and unused by this test.)

At the end of `types/api.ts`, append:

```typescript
export interface PushSubscriptionDto {
  id: number;
  endpoint: string;
  device_label: string | null;
  user_agent: string | null;
  last_used_at: string;
  created_at: string;
}

export interface CreatePushSubscriptionDto {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  user_agent?: string;
  device_label?: string;
}

export interface VapidKeyDto {
  public_key: string;
}
```

**Step 2: Retarget existing prefs functions in `client.ts`**

Find `getNotificationPrefs` (line 177) and `updateNotificationPrefs` (line 182). Change the URL from `/api/telegram/prefs` to `/api/notifications/preferences`:

```typescript
export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  const res = await fetch('/api/notifications/preferences');
  return handleResponse<NotificationPrefs>(res);
}

export async function updateNotificationPrefs(partial: Partial<NotificationPrefs>): Promise<NotificationPrefs> {
  const res = await fetch('/api/notifications/preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  });
  return handleResponse<NotificationPrefs>(res);
}
```

**Step 3: Subscriptions client** — `frontend/src/notifications/api.ts` (only subscriptions + vapid; prefs continue via `client.ts`):

```typescript
import type {
  CreatePushSubscriptionDto,
  PushSubscriptionDto,
  VapidKeyDto,
} from '../types/api';
import { ApiError } from '../types/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

export const notificationsApi = {
  getVapidPublicKey: async (): Promise<VapidKeyDto> => {
    const res = await fetch('/api/notifications/vapid-public-key');
    return handleResponse<VapidKeyDto>(res);
  },
  listSubscriptions: async (): Promise<PushSubscriptionDto[]> => {
    const res = await fetch('/api/notifications/subscriptions');
    return handleResponse<PushSubscriptionDto[]>(res);
  },
  createSubscription: async (dto: CreatePushSubscriptionDto): Promise<PushSubscriptionDto> => {
    const res = await fetch('/api/notifications/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dto),
    });
    return handleResponse<PushSubscriptionDto>(res);
  },
  deleteSubscription: async (id: number): Promise<void> => {
    const res = await fetch(`/api/notifications/subscriptions/${id}`, { method: 'DELETE' });
    return handleResponse<void>(res);
  },
};
```

**Step 4: Tests** — `frontend/src/notifications/__tests__/api.test.ts`. Use `vi.stubGlobal('fetch', ...)` to intercept:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { notificationsApi } from '../api';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ok = (json: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: () => Promise.resolve(json),
});

describe('notificationsApi', () => {
  it('getVapidPublicKey GETs /api/notifications/vapid-public-key', async () => {
    fetchMock.mockResolvedValue(ok({ public_key: 'pub' }));
    await notificationsApi.getVapidPublicKey();
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/vapid-public-key');
  });

  it('createSubscription POSTs JSON body', async () => {
    fetchMock.mockResolvedValue(ok({ id: 1, endpoint: 'x' }, 201));
    await notificationsApi.createSubscription({
      endpoint: 'x',
      keys: { p256dh: 'p', auth: 'a' },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/notifications/subscriptions',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('deleteSubscription DELETEs the id path and returns void on 204', async () => {
    fetchMock.mockResolvedValue(ok(undefined, 204));
    await expect(notificationsApi.deleteSubscription(42)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/notifications/subscriptions/42',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('throws ApiError on 4xx', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: 'gone' }),
    });
    await expect(notificationsApi.deleteSubscription(99)).rejects.toMatchObject({ status: 404 });
  });
});
```

**Step 5: Commit**

```bash
git add frontend/src/notifications/api.ts frontend/src/notifications/__tests__/api.test.ts \
        frontend/src/types/api.ts frontend/src/api/client.ts \
        frontend/src/components/__tests__/TelegramPanel.test.tsx
git commit -m "feat(notifications): subscriptions client + DTOs; retarget prefs to /notifications/preferences"
```

---

### Task 15: Device-label helper [ ]

**Files:** Create `frontend/src/notifications/device-label.ts` + co-located test

**Step 1: Implement**

```typescript
/** Best-effort UA → human label. Never throws — falls back to "Unbekanntes Gerät". */
export function getDeviceLabel(ua: string = navigator.userAgent): string {
  const lower = ua.toLowerCase();
  let device: string | null = null;
  if (lower.includes('iphone')) device = 'iPhone';
  else if (lower.includes('ipad')) device = 'iPad';
  else if (lower.includes('android')) device = 'Android';
  else if (lower.includes('windows')) device = 'Windows';
  else if (lower.includes('macintosh') || lower.includes('mac os')) device = 'Mac';
  else if (lower.includes('linux')) device = 'Linux';

  let browser: string | null = null;
  if (lower.includes('edg/')) browser = 'Edge';
  else if (lower.includes('chrome/') && !lower.includes('chromium')) browser = 'Chrome';
  else if (lower.includes('firefox/')) browser = 'Firefox';
  else if (lower.includes('safari/') && !lower.includes('chrome')) browser = 'Safari';

  if (device && browser) return `${device} · ${browser}`;
  if (device) return device;
  if (browser) return browser;
  return 'Unbekanntes Gerät';
}
```

**Step 2: Tests** — `frontend/src/notifications/__tests__/device-label.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { getDeviceLabel } from '../device-label';

describe('getDeviceLabel', () => {
  it('parses Chrome on Android', () => {
    expect(getDeviceLabel('Mozilla/5.0 (Linux; Android 13) Chrome/120.0')).toBe('Android · Chrome');
  });
  it('parses Safari on iPhone', () => {
    expect(getDeviceLabel('Mozilla/5.0 (iPhone) Safari/17.0')).toBe('iPhone · Safari');
  });
  it('parses Edge on Windows', () => {
    expect(getDeviceLabel('Mozilla/5.0 (Windows NT 10.0) Edg/120.0')).toBe('Windows · Edge');
  });
  it('falls back when nothing matches', () => {
    expect(getDeviceLabel('totally-unknown-ua')).toBe('Unbekanntes Gerät');
  });
});
```

**Step 3: Commit**

```bash
git add frontend/src/notifications/device-label.ts frontend/src/notifications/__tests__/device-label.test.ts
git commit -m "feat(notifications): device-label helper"
```

---

### Task 16: useWebPushSubscription hook [ ]

**Depends on:** Tasks 11, 14, 15

**Files:** Create `frontend/src/notifications/useWebPushSubscription.ts` + test

**Step 1: Implement**

```typescript
import { useCallback, useEffect, useState } from 'react';
import { pushSupported } from '../lib/pwa-detect';
import { notificationsApi } from './api';
import { getDeviceLabel } from './device-label';

export type PushState =
  | { status: 'unsupported' }
  | { status: 'default' }
  | { status: 'denied' }
  | { status: 'granted-no-subscription' }
  | { status: 'granted-subscribed'; endpoint: string };

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const safe = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(safe);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function useWebPushSubscription() {
  const [state, setState] = useState<PushState>({ status: 'default' });
  const supported = pushSupported();

  const refresh = useCallback(async () => {
    if (!pushSupported()) return setState({ status: 'unsupported' });
    if (Notification.permission === 'denied') return setState({ status: 'denied' });
    if (Notification.permission === 'default') return setState({ status: 'default' });
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return setState({ status: 'granted-no-subscription' });
    setState({ status: 'granted-subscribed', endpoint: sub.endpoint });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const subscribe = useCallback(async () => {
    if (!pushSupported()) throw new Error('Push wird in diesem Browser nicht unterstützt');
    const { public_key } = await notificationsApi.getVapidPublicKey();
    if (!public_key) throw new Error('VAPID-Schlüssel nicht verfügbar');

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      await refresh();
      return;
    }

    const reg = await navigator.serviceWorker.ready;
    const applicationServerKey = urlBase64ToUint8Array(public_key) as unknown as BufferSource;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey });
    const json = sub.toJSON();
    await notificationsApi.createSubscription({
      endpoint: json.endpoint!,
      keys: { p256dh: json.keys!['p256dh'], auth: json.keys!['auth'] },
      user_agent: navigator.userAgent,
      device_label: getDeviceLabel(),
    });
    await refresh();
  }, [refresh]);

  const unsubscribeCurrent = useCallback(async () => {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) await sub.unsubscribe();
    await refresh();
  }, [refresh]);

  return { state, supported, subscribe, unsubscribeCurrent, refresh };
}
```

**Step 2: Tests** — `frontend/src/notifications/__tests__/useWebPushSubscription.test.tsx`. Stub `navigator.serviceWorker`, `Notification`, `window.PushManager`. One `it` per state transition + subscribe path:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

afterEach(() => vi.unstubAllGlobals());

describe('useWebPushSubscription', () => {
  it('unsupported when serviceWorker missing', async () => {
    vi.stubGlobal('navigator', { userAgent: 'x' });
    const { useWebPushSubscription } = await import('../useWebPushSubscription');
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('unsupported'));
  });

  it('default when permission is default', async () => {
    /* stub navigator.serviceWorker, window.PushManager, Notification.permission='default' */
  });

  it('denied when permission is denied', async () => {
    /* … */
  });

  it('granted-no-subscription when permission granted but pushManager.getSubscription() → null', async () => {
    /* … */
  });

  it('granted-subscribed when pushManager.getSubscription() → { endpoint }', async () => {
    /* … */
  });

  it('subscribe requests permission, calls pushManager.subscribe, posts to API', async () => {
    /* mock notificationsApi.getVapidPublicKey, notificationsApi.createSubscription */
  });

  it('subscribe throws when public_key is empty', async () => {
    /* mock getVapidPublicKey → { public_key: '' } */
  });
});
```

**Step 3: Commit**

```bash
git add frontend/src/notifications/useWebPushSubscription.ts frontend/src/notifications/__tests__/useWebPushSubscription.test.tsx
git commit -m "feat(notifications): useWebPushSubscription hook"
```

---

### Task 17: FirstStartPushPrompt banner [ ]

**Depends on:** Tasks 11, 16

**Files:** Create `frontend/src/notifications/FirstStartPushPrompt.tsx` + test

**Reuse check:** Reuses visual shell from `frontend/src/components/InstallPrompt.tsx`. Helpers `isIos`, `isStandalone` from `lib/pwa-detect`.

**Step 1: Component**

```typescript
import { useEffect, useState } from 'react';
import { useWebPushSubscription } from './useWebPushSubscription';
import { isIos, isStandalone } from '../lib/pwa-detect';

const FLAG = 'rcn_notif_asked';

export function FirstStartPushPrompt() {
  const { state, subscribe } = useWebPushSubscription();
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(FLAG) === 'true');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // iOS Safari: hide until PWA is installed (Apple API limitation).
  const blockedByIos = isIos() && !isStandalone();
  const visible = !dismissed && !blockedByIos && state.status === 'default';

  useEffect(() => {
    if (state.status === 'granted-subscribed' || state.status === 'denied') {
      localStorage.setItem(FLAG, 'true');
    }
  }, [state.status]);

  if (!visible) return null;

  const dismiss = () => {
    localStorage.setItem(FLAG, 'true');
    setDismissed(true);
  };

  const enable = () => {
    setError(null);
    setBusy(true);
    void subscribe()
      .then(() => dismiss())
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Aktivierung fehlgeschlagen'),
      )
      .finally(() => setBusy(false));
  };

  return (
    <div
      role="region"
      aria-live="polite"
      aria-label="Benachrichtigungen aktivieren"
      className="sm:hidden fixed bottom-[140px] left-3 right-3 z-50 rounded-xl px-4 py-3"
      style={{
        background: 'rgba(15, 15, 35, 0.92)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(99, 102, 241, 0.3)',
        boxShadow: '0 -4px 24px rgba(0, 0, 0, 0.4)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex-shrink-0 flex items-center justify-center rounded-lg"
          style={{
            width: 36,
            height: 36,
            background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(147,51,234,0.3))',
            border: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M15 17h5l-1.4-1.4A2 2 0 0118 14V11a6 6 0 10-12 0v3a2 2 0 01-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium" style={{ color: '#F8FAFC' }}>
            Benachrichtigungen aktivieren?
          </p>
          <p className="text-xs" style={{ color: 'rgba(248, 250, 252, 0.45)' }}>
            Bei neuen Treffern für deine gespeicherten Suchen.
          </p>
          {error && (
            <p className="text-xs mt-1" role="alert" style={{ color: '#F87171' }}>
              Fehler: {error}
            </p>
          )}
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-3">
        <button
          type="button"
          onClick={dismiss}
          disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{ color: 'rgba(248, 250, 252, 0.55)' }}
        >
          Später
        </button>
        <button
          type="button"
          onClick={enable}
          disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{
            background: 'rgba(99, 102, 241, 0.2)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            color: '#A78BFA',
          }}
        >
          {busy ? 'Wird aktiviert …' : 'Aktivieren'}
        </button>
      </div>
    </div>
  );
}
```

**Step 2: Tests** — `frontend/src/notifications/__tests__/FirstStartPushPrompt.test.tsx`. Mock `useWebPushSubscription` and `pwa-detect` helpers:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../useWebPushSubscription', () => ({ useWebPushSubscription: vi.fn() }));
vi.mock('../../lib/pwa-detect', () => ({
  isIos: vi.fn(() => false),
  isStandalone: vi.fn(() => true),
}));

import { FirstStartPushPrompt } from '../FirstStartPushPrompt';
import { useWebPushSubscription } from '../useWebPushSubscription';

const mockHook = useWebPushSubscription as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  mockHook.mockReset();
});

describe('FirstStartPushPrompt', () => {
  it('hides when localStorage flag is set', () => {
    localStorage.setItem('rcn_notif_asked', 'true');
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('hides when state is not default', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('shows banner when state is default and no flag set', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    render(<FirstStartPushPrompt />);
    expect(screen.getByText(/Benachrichtigungen aktivieren/)).toBeInTheDocument();
  });

  it('dismiss sets flag and hides banner', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Später'));
    expect(localStorage.getItem('rcn_notif_asked')).toBe('true');
    expect(container.firstChild).toBeNull();
  });

  it('enable calls subscribe then sets flag', async () => {
    const subscribe = vi.fn().mockResolvedValue(undefined);
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe });
    render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(subscribe).toHaveBeenCalledOnce());
    await waitFor(() => expect(localStorage.getItem('rcn_notif_asked')).toBe('true'));
  });

  it('hidden on iOS Safari without standalone', async () => {
    const pwa = await import('../../lib/pwa-detect');
    (pwa.isIos as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    (pwa.isStandalone as unknown as ReturnType<typeof vi.fn>).mockReturnValue(false);
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('shows error when subscribe rejects', async () => {
    const subscribe = vi.fn().mockRejectedValue(new Error('boom'));
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe });
    render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/boom/));
  });
});
```

**Step 3: Commit**

```bash
git add frontend/src/notifications/FirstStartPushPrompt.tsx frontend/src/notifications/__tests__/FirstStartPushPrompt.test.tsx
git commit -m "feat(notifications): FirstStartPushPrompt banner"
```

---

### Task 18a: NotificationsPanel — state display [ ]

**Depends on:** Tasks 11, 16

**Files:** Create `frontend/src/components/NotificationsPanel.tsx` (initial scaffold)

**Reuse check:** Reuses inline `cardStyle` shape from `ProfilePage.tsx` (locally re-declared — same two-caller pattern as `TelegramPanel`). Reuses `useWebPushSubscription` hook.

**Step 1: Component scaffold — supported/default/denied/granted-no-subscription branches only**

```typescript
import { useState } from 'react';
import { useWebPushSubscription } from '../notifications/useWebPushSubscription';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

export function NotificationsPanel() {
  const { state, supported, subscribe } = useWebPushSubscription();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubscribe = () => {
    setError(null);
    setBusy(true);
    void subscribe()
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Fehler'))
      .finally(() => setBusy(false));
  };

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <p className="text-sm font-semibold mb-4" style={{ color: '#A78BFA' }}>
        Benachrichtigungen (Web Push)
      </p>

      {!supported && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.55)' }}>
          Dein Browser unterstützt keine Web-Push-Benachrichtigungen.
        </p>
      )}

      {supported && state.status === 'default' && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.65)' }}>
            Push ist auf diesem Gerät noch nicht aktiviert.
          </p>
          <button
            type="button"
            onClick={handleSubscribe}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
            style={{
              background: 'rgba(99, 102, 241, 0.2)',
              border: '1px solid rgba(99, 102, 241, 0.4)',
              color: '#A78BFA',
            }}
          >
            {busy ? 'Wird aktiviert …' : 'Aktivieren'}
          </button>
        </div>
      )}

      {supported && state.status === 'denied' && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.65)' }}>
          Benachrichtigungen sind im Browser blockiert. Erlaube sie in den Site-Settings deines
          Browsers für RC Scout und lade die Seite neu.
        </p>
      )}

      {supported && state.status === 'granted-no-subscription' && (
        <button
          type="button"
          onClick={handleSubscribe}
          disabled={busy}
          className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
          style={{
            background: 'rgba(99, 102, 241, 0.2)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            color: '#A78BFA',
          }}
        >
          {busy ? 'Wird aktiviert …' : 'Auf diesem Gerät aktivieren'}
        </button>
      )}

      {supported && state.status === 'granted-subscribed' && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.75)' }}>
          {'✅'} Benachrichtigungen sind auf diesem Gerät aktiv.
        </p>
      )}

      {error && (
        <p role="alert" className="text-xs mt-2" style={{ color: '#F87171' }}>
          Fehler: {error}
        </p>
      )}
    </section>
  );
}
```

**Step 2: Tests** — `frontend/src/components/__tests__/NotificationsPanel.test.tsx` for the four state branches above:

```typescript
// it('renders unsupported message when supported=false')
// it('renders default state with Aktivieren button')
// it('renders denied state with browser hint')
// it('renders granted-no-subscription with on-device button')
// it('renders granted-subscribed confirmation')
// it('renders error when subscribe rejects')
```

**Step 3: Commit**

```bash
git add frontend/src/components/NotificationsPanel.tsx frontend/src/components/__tests__/NotificationsPanel.test.tsx
git commit -m "feat(profile): NotificationsPanel — state display"
```

---

### Task 18b: NotificationsPanel — device list + prefs toggle [ ]

**Depends on:** Task 18a, Task 14

**Files:** Modify `frontend/src/components/NotificationsPanel.tsx`, extend the test file

**Step 1: Add device list + prefs toggle to the existing component**

Add imports at the top:

```typescript
import { useCallback, useEffect } from 'react';
import { notificationsApi } from '../notifications/api';
import { getNotificationPrefs, updateNotificationPrefs } from '../api/client';
import type { NotificationPrefs, PushSubscriptionDto } from '../types/api';
```

Inside the component, add state + load effects:

```typescript
  const [subs, setSubs] = useState<PushSubscriptionDto[]>([]);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);

  const reloadSubs = useCallback(async () => {
    try {
      setSubs(await notificationsApi.listSubscriptions());
    } catch {
      /* non-fatal */
    }
  }, []);

  const reloadPrefs = useCallback(async () => {
    try {
      setPrefs(await getNotificationPrefs());
    } catch {
      /* non-fatal */
    }
  }, []);

  useEffect(() => {
    if (state.status === 'granted-subscribed' || state.status === 'granted-no-subscription') {
      void reloadSubs();
    }
    void reloadPrefs();
  }, [state.status, reloadSubs, reloadPrefs]);

  const handleDelete = (id: number) => {
    void notificationsApi.deleteSubscription(id).then(reloadSubs);
  };

  const handleTogglePush = (value: boolean) => {
    // Optimistic update with revert-on-error — mirrors TelegramPanel.handleToggle.
    const previous = prefs?.web_push_enabled;
    setPrefs((p) => (p ? { ...p, web_push_enabled: value } : p));
    void updateNotificationPrefs({ web_push_enabled: value })
      .then(setPrefs)
      .catch(() => {
        if (previous !== undefined) {
          setPrefs((p) => (p ? { ...p, web_push_enabled: previous } : p));
        }
      });
  };
```

Append two blocks before `</section>`:

```tsx
      {(state.status === 'granted-subscribed' || state.status === 'granted-no-subscription') && subs.length > 0 && (
        <div className="mt-5">
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2"
             style={{ color: 'rgba(248, 250, 252, 0.35)' }}>
            Registrierte Geräte
          </p>
          <ul className="flex flex-col gap-2">
            {subs.map((s) => (
              <li key={s.id} className="flex items-center justify-between text-sm">
                <span style={{ color: 'rgba(248, 250, 252, 0.8)' }}>
                  {s.device_label ?? 'Unbekanntes Gerät'}
                </span>
                <button
                  type="button"
                  onClick={() => handleDelete(s.id)}
                  aria-label={`Gerät ${s.device_label ?? s.id} entfernen`}
                  className="text-xs"
                  style={{ color: 'rgba(248, 250, 252, 0.45)' }}
                >
                  Entfernen
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {prefs && (
        <div className="mt-5 flex items-center justify-between">
          <span className="text-sm" style={{ color: 'rgba(248,250,252,0.75)' }}>
            Push-Benachrichtigungen empfangen
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={prefs.web_push_enabled}
            aria-label="Push aktiv"
            onClick={() => handleTogglePush(!prefs.web_push_enabled)}
            className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200"
            style={{
              background: prefs.web_push_enabled
                ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                : 'rgba(255,255,255,0.1)',
              border: prefs.web_push_enabled
                ? '1px solid rgba(139,92,246,0.5)'
                : '1px solid rgba(255,255,255,0.15)',
            }}
          >
            <span
              className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
              style={{
                background: '#fff',
                transform: prefs.web_push_enabled ? 'translateX(18px)' : 'translateX(2px)',
                boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
              }}
              aria-hidden="true"
            />
          </button>
        </div>
      )}
```

**Step 2: Append tests** to the existing `NotificationsPanel.test.tsx`:

```typescript
// it('shows device list when granted-subscribed and listSubscriptions returned rows')
// it('clicking Entfernen calls deleteSubscription and reloads')
// it('toggling pref calls updateNotificationPrefs with web_push_enabled')
```

**Step 3: Commit**

```bash
git add frontend/src/components/NotificationsPanel.tsx frontend/src/components/__tests__/NotificationsPanel.test.tsx
git commit -m "feat(profile): NotificationsPanel — devices + prefs toggle"
```

---

### Task 19: Mount FirstStartPushPrompt + NotificationsPanel [ ]

**Depends on:** Tasks 17, 18b

**Files:** Modify `frontend/src/App.tsx`, modify `frontend/src/pages/ProfilePage.tsx`

**Step 1: App.tsx**

At line 223 change:

```tsx
      <InstallPrompt />
```

to:

```tsx
      <InstallPrompt />
      <FirstStartPushPrompt />
```

Add the import near the top:

```tsx
import { FirstStartPushPrompt } from './notifications/FirstStartPushPrompt';
```

**Step 2: ProfilePage.tsx**

Change Column 2 ([ProfilePage.tsx:236-240](frontend/src/pages/ProfilePage.tsx#L236-L240)):

```tsx
        <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
          <NotificationsPanel />
          <TelegramPanel user={user} onUserReload={onUserReload} />
          {user.role === 'admin' && <LLMAdminPanel />}
        </div>
```

Add the import:

```tsx
import { NotificationsPanel } from '../components/NotificationsPanel';
```

**Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/ProfilePage.tsx
git commit -m "feat(ui): mount FirstStartPushPrompt + NotificationsPanel"
```

---

### Task 20: Production build path — Dockerfile + GHA [ ]

**Depends on:** Task 12

**Files:** Modify `frontend/Dockerfile`, modify `.github/workflows/deploy.yml`

**Step 1: Add build-arg to `frontend/Dockerfile`**

Insert before `RUN npm run build`:

```dockerfile
ARG VITE_VAPID_PUBLIC_KEY=""
ENV VITE_VAPID_PUBLIC_KEY=$VITE_VAPID_PUBLIC_KEY
```

**Step 2: Pass build-arg in GHA**

Replace the existing `Build & push nginx/frontend image` step ([deploy.yml:39-47](.github/workflows/deploy.yml#L39-L47)) with:

```yaml
      - name: Build & push nginx/frontend image
        uses: docker/build-push-action@v6
        with:
          context: ./frontend
          file: ./frontend/Dockerfile
          push: true
          build-args: |
            VITE_VAPID_PUBLIC_KEY=${{ vars.VAPID_PUBLIC_KEY }}
          tags: |
            ghcr.io/marcoroth1983/rc-network-scraper/nginx:latest
            ghcr.io/marcoroth1983/rc-network-scraper/nginx:${{ steps.tag.outputs.sha }}
```

(The VAPID public key is exposed to every browser anyway, so `vars.VAPID_PUBLIC_KEY` — a non-secret repository variable — is correct. Use `secrets.VAPID_PUBLIC_KEY` only if the project standardizes on Secrets for everything.)

**Step 3: Document the GitHub repo variable**

In `env.prod.example`, add a comment near the VAPID block:

```bash
# Set VAPID_PUBLIC_KEY as a GitHub repository variable (Settings → Secrets and variables → Actions → Variables)
# so it gets baked into the frontend image during CI build.
```

**Step 4: Commit**

```bash
git add frontend/Dockerfile .github/workflows/deploy.yml env.prod.example
git commit -m "chore(ci): wire VITE_VAPID_PUBLIC_KEY into frontend build"
```

---

### Task 21: Generate VAPID keypair [ ]

**Step 1: Run once, locally, outside the repo:**

```bash
npx web-push generate-vapid-keys
```

Output is two URL-safe base64 strings — exactly the format the frontend hook (`urlBase64ToUint8Array`) and `pywebpush` (`vapid_private_key=...`) expect. No conversion required.

**Step 2: Populate `.env`** (NOT committed):

```bash
VAPID_PUBLIC_KEY=<the public key from step 1>
VAPID_PRIVATE_KEY=<the private key from step 1>
VAPID_SUBJECT=mailto:marco.roth1983@googlemail.com
NOTIFICATION_CHANNEL=webpush
```

**Step 3: Populate the GitHub repository variable** `VAPID_PUBLIC_KEY` (public key only). The private key goes onto the VPS in its `.env` file directly — never into CI/CD.

**No commit** — this task produces secrets only.

---

### Task 22: Verification gate (no commit, see § Verification) [ ]

This is a placeholder for the end-of-plan verification — actual commands are in the `## Verification` section below.

---

### Task 23: Update definition.md [ ]

**Depends on:** All implementation tasks (1–22)

**Files:** Modify `docs/definition.md`

Replace §F5 with:

```markdown
### F5: Web Push Alerts (active)

- Per-user opt-in via `/profile` notifications panel.
- Trigger: new listing matches for any **active** SavedSearch (existing pipeline via `notification_registry.dispatch(MatchResult)`).
- Multi-device: each browser install registers its own subscription; users can remove devices individually.
- Delivery channel selectable via `NOTIFICATION_CHANNEL` env: `webpush` (default), `telegram`, or `both`.
- iOS: requires PWA install (Add to Home Screen) — see `limitations.md`.
```

**Commit:**

```bash
git add docs/definition.md
git commit -m "docs(definition): activate F5 Web Push"
```

---

### Task 24: Update architektur.md [ ]

**Depends on:** All implementation tasks

**Files:** Modify `docs/architektur.md`

Append at end:

```markdown
## Notification Channels

`app/notifications/registry.py` holds a singleton `notification_registry`. Plugins implement `NotificationPlugin` (`is_configured()` + `send(MatchResult)`). Channel routing happens **at registration time** in `app/main.py:lifespan()` based on `settings.NOTIFICATION_CHANNEL`. The same channel switch also gates Telegram-only side effects (`fav_sweep` scheduler + `setWebhook` registration).

| Value | Plugins registered | Telegram side-effects |
|-------|-------------------|----------------------|
| `webpush` (default) | `LogPlugin` + `WebPushPlugin` (when VAPID set) | OFF |
| `telegram`          | `LogPlugin` + `TelegramPlugin` (when bot token set) | ON |
| `both`              | `LogPlugin` + `WebPushPlugin` + `TelegramPlugin` | ON |

WebPush stores subscriptions in `push_subscriptions` (multi-device). Per-user opt-in lives on `user_notification_prefs.web_push_enabled` and is served via `GET/PUT /api/notifications/preferences` — the consolidated single source of truth (the legacy `/api/telegram/prefs` routes were removed in PLAN-027). The frontend uses `vite-plugin-pwa` in `injectManifest` mode with a custom `src/sw.ts` (built to `dist/sw.js`, served with `Cache-Control: no-cache` by `nginx.conf`) that handles `push` and `notificationclick` events.
```

**Commit:**

```bash
git add docs/architektur.md
git commit -m "docs(arch): document notification channels + WebPushPlugin"
```

---

### Task 25: Update limitations.md [ ]

**Files:** Modify `docs/limitations.md`

Append:

```markdown
---

## iOS Web Push requires PWA install

**What:** On iOS Safari, Web Push only works after the user adds the site to their Home Screen ("Add to Home Screen") so it runs as a standalone PWA. In a regular Safari tab, `Notification.requestPermission()` is unavailable.

**Why:** Apple's policy since iOS 16.4 (March 2023). Cannot be worked around — no Apple Developer account or APNs token would change this.

**Mitigation:** The frontend detects iOS-without-standalone and suppresses the push prompt. The InstallPrompt banner is shown first; once the user installs the PWA and reopens it, the push prompt becomes available.
```

**Commit:**

```bash
git add docs/limitations.md
git commit -m "docs(limitations): document iOS Web Push PWA requirement"
```

---

## Verification

> Run after **all** tasks above are `[DONE]`.

**Step 1: Backend tests**

```bash
docker compose up -d db
docker compose run --rm backend pytest tests/ -v
```

Expected: existing suite passes; new `test_web_push_plugin.py` (7 tests) and `test_notifications_api.py` (10 tests) pass; the removed `test_telegram_api.py::*prefs*` tests do not appear; nothing else regresses.

**Step 2: Frontend tests**

```bash
cd frontend
npm run test -- --run
```

Expected: existing suite passes; new tests for `pwa-detect`, `device-label`, `useWebPushSubscription`, `FirstStartPushPrompt`, `NotificationsPanel`, and `notifications/api` pass.

**Step 3: Frontend build**

```bash
cd frontend
VITE_VAPID_PUBLIC_KEY=BDevPub npm run build
```

Expected: `dist/sw.js` and a generated manifest are produced. Build does not error.

**Step 4: Backend startup smoke**

```bash
docker compose up --build -d
docker compose logs backend --tail=80
```

With `NOTIFICATION_CHANNEL=webpush` and VAPID populated:
- `Database initialised`
- `web_push.plugin: registered (channel=webpush)`
- No `telegram.plugin: registered` line
- No `telegram_fav_status_sweep` scheduler line
- No `setWebhook` traffic
- No tracebacks

With `NOTIFICATION_CHANNEL=telegram`:
- `telegram.plugin: registered (channel=telegram)`
- No `web_push.plugin: registered` line
- `fav_sweep` scheduler runs

**Step 5: API smoke**

```bash
# Auth cookie required for /subscriptions; /vapid-public-key is public
curl -s http://localhost:8002/api/notifications/vapid-public-key
```

Expected: `{"public_key": "..."}` (200) when VAPID set, `{"detail": "Web Push not configured"}` (503) when unset.

**Step 6: Browser smoke (manual)**

1. `npm run dev` (frontend, with VAPID populated in backend `.env`).
2. Login.
3. Mobile viewport: see FirstStartPushPrompt banner.
4. Click Aktivieren → browser permission prompt → accept.
5. `/profile` shows the device under "Registrierte Geräte" + the Web-Push toggle in the on state.
6. Trigger a SavedSearch match (insert a listing matching an active search, or invoke the existing match dispatch path manually) → push notification appears.
7. Toggle off → next match produces no notification.
8. Click "Entfernen" → next match produces no notification on that device.
9. iPhone Safari (without Add-to-Home-Screen): banner is hidden. After install + relaunch from Home Screen: banner appears. Note: HTTPS or `localhost` is required (browsers refuse Push on plain HTTP for non-localhost origins).

---

## Notes for the Coder

- **DO NOT** introduce Alembic. Schema changes go into `app/db.py:init_db()` AND `tests/conftest.py` (Task 3).
- **DO NOT** modify `app/notifications/base.py` or `app/notifications/registry.py`. Add only.
- **DO NOT** modify `app/telegram/plugin.py`. Channel gating happens in `main.py`.
- **DO NOT** rename `getNotificationPrefs`/`updateNotificationPrefs`. Only the URL changes; callers (`TelegramPanel`, `NotificationsPanel`) stay unchanged.
- **Vitest globals**: Plan keeps `globals: true` in `vite.config.ts` to match existing tests; new tests still import `describe, it, expect, vi` explicitly per CLAUDE.md so the file is forward-compatible if globals are disabled later.
- **Frontend build args**: `VITE_VAPID_PUBLIC_KEY` is optional in dev/local — the hook fetches the key at runtime via `/api/notifications/vapid-public-key`. The build-arg path exists only to spare prod a request on first cold load.
- **Frequent commits** between sub-steps if work pauses. Each commit message uses the project's existing prefix style (`feat(...)`, `fix(...)`, `chore(...)`, `test(...)`, `docs(...)`, `refactor(...)`).

---

## Plan Review

_Plan review closed 2026-05-03: 26 findings addressed across 3 cycles._
