# Web Push Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

> **Update 2026-05-30:** Scope changed. Web Push is now the **only** notification channel — Telegram is **removed entirely** (no `NOTIFICATION_CHANNEL` switch). The favorites status sweep (sold/price/deleted) is migrated from Telegram to Web Push via a shared `send_web_push_to_user()` helper. All anchors re-verified against current code (the old plan missed that the Telegram API router is included in `routes.py`, not `main.py`, and that `/api/auth/me` returns telegram fields). Approvals reset to pending — re-review required.

**Goal:** Add a `WebPushPlugin` to the existing `notification_registry` so per-user SavedSearch matches are delivered as native browser/PWA push notifications, migrate the favorites status sweep to Web Push, and **remove the Telegram subsystem completely**. UI: a soft-ask banner cloned from `InstallPrompt` and a `NotificationsPanel` on `/profile` (replacing `TelegramPanel`) for device management + opt-in.

**Architecture:**
- **Backend (FastAPI / SQLAlchemy async):** New `WebPushPlugin` (`app/notifications/web_push_plugin.py`) implementing the existing `NotificationPlugin` ABC. A shared module-level helper `send_web_push_to_user(user_id, payload)` (same file) owns the per-subscription send loop, the 404/410 stale-subscription garbage collection, and the per-delivered `last_used_at` bump. Both the plugin (`send()`) and the migrated favorites sweep use this single helper (DRY). Two persistence concerns: a new `push_subscriptions` table (multi-device, N rows per user) and a new column `web_push_enabled` on the existing `user_notification_prefs` table.
- **Notification prefs move out of `app/telegram`.** `NotificationPrefs` + `get_prefs`/`set_prefs` move to a new non-telegram module `app/notifications/prefs.py` (the only non-telegram code in the deleted `app/telegram/prefs.py`). All importers are retargeted.
- **Favorites sweep migrates** from `app/telegram/fav_sweep.py` to `app/notifications/fav_sweep.py`: the SQL `WHERE u.telegram_chat_id IS NOT NULL` filter is replaced with "user has ≥1 push subscription", `bot.send_message` is replaced with `send_web_push_to_user`, the HTML digest becomes a `{title, body, url}` push payload, and the link-token cleanup tail is dropped (no more tokens). The scheduler job in `main.py` stays but is **ungated** (no `telegram_enabled`). Interval/cutoff settings renamed `TELEGRAM_FAV_SWEEP_INTERVAL_MIN → FAV_SWEEP_INTERVAL_MIN`, `TELEGRAM_FAV_DELETED_DAYS → FAV_DELETED_DAYS`.
- **Telegram removed:** modules `app/telegram/{bot,link,plugin,webhook,fav_sweep}.py` deleted; `app/telegram/prefs.py` deleted (logic moved); the `app/telegram/` package removed. `app/api/telegram.py` deleted; its include removed from `routes.py`. `TelegramPlugin` registration, the `fav_sweep` gate, and the `setWebhook` block removed from `main.py`. All `TELEGRAM_*` settings + `telegram_enabled` removed from `config.py`. `/api/auth/me` stops returning telegram fields. DB: `telegram_link_tokens` table + `users.telegram_chat_id`/`telegram_linked_at` columns dropped (idempotent). Frontend `TelegramPanel.tsx` + tests deleted, telegram client functions/types removed, `AuthUser` telegram fields removed.
- **New REST module** `app/api/notifications.py` exposes subscription CRUD, the VAPID public key, and the consolidated preferences endpoint (`GET/PUT /api/notifications/preferences`) — single source of truth for `user_notification_prefs`.
- **Frontend (React 19 / Vite 8 / Tailwind 3):** Adopt `vite-plugin-pwa` in `injectManifest` mode with a custom `src/sw.ts` (push + notificationclick + manifest precache; built to `dist/sw.js` matching the existing `nginx.conf:14` `/sw.js` no-cache rule). Legacy artifacts (`public/sw.js`, `public/manifest.json`, the `index.html` manifest link, the manual SW registration in `main.tsx`) are deleted and replaced by VitePWA's auto-injected registration + migrated `manifest:` config. New `src/notifications/` module: a 5-state `useWebPushSubscription` hook, a subscriptions client, a UA→device-label helper, and a `FirstStartPushPrompt` banner mirroring `InstallPrompt`. iOS gating reuses the extracted `isStandalone()` check. New `NotificationsPanel` replaces `TelegramPanel` in `ProfilePage` Column 2, split into two tasks (state-display vs. device-list + prefs).
- **VAPID:** Single keypair, generated once via `npx web-push generate-vapid-keys` (URL-safe base64). Local: `docker-compose.yml` env. Prod: GitHub repo variable + VPS `.env`, passed to the frontend image at build time as `VITE_VAPID_PUBLIC_KEY` via `frontend/Dockerfile` build-arg.

**Tech Stack:** FastAPI, SQLAlchemy async, `pywebpush` (Python), `pydantic-settings`, React 19, `vite-plugin-pwa@^0.21`, Workbox 7, native `PushManager` / `ServiceWorkerRegistration` APIs, Tailwind 3, npm.

**Breaking Changes:** Yes.
- **Telegram subsystem removed entirely.** No fallback channel. Any deployment relying on Telegram delivery loses it. Recovery: re-introduce from git history if ever needed (intentionally not preserved per project breaking-change policy).
- Backend routes removed: `POST /api/telegram/link`, `POST /api/telegram/unlink`, `GET/PUT /api/telegram/prefs`, `POST /api/telegram/webhook`. Prefs data now served by `GET/PUT /api/notifications/preferences`.
- `/api/auth/me` response loses `telegram_chat_id` and `telegram_linked_at` fields.
- DB: table `telegram_link_tokens` dropped; columns `users.telegram_chat_id` + `users.telegram_linked_at` dropped (idempotent `DROP` — no data migration, per project policy).
- Settings removed: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_LINK_TOKEN_TTL_MIN`, `TELEGRAM_DIGEST_TOP_N`. Renamed: `TELEGRAM_FAV_SWEEP_INTERVAL_MIN → FAV_SWEEP_INTERVAL_MIN`, `TELEGRAM_FAV_DELETED_DAYS → FAV_DELETED_DAYS`.
- New required env vars for push delivery: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`. If unset, `WebPushPlugin.is_configured()` returns False and no push is delivered (degrades gracefully, no crash).

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-05-30 |
| Human | approved | 2026-05-31 |

---

## Context

### What exists today (verified by grep + read, 2026-05-30)

- **Plugin registry** is the reuse point. [`backend/app/notifications/registry.py:35`](backend/app/notifications/registry.py#L35) defines a module-level `notification_registry` with `register()` + `dispatch(MatchResult)`. Each plugin is checked via `is_configured()` before `send()`; failures are caught and logged. No changes to registry/base needed.
- **`MatchResult` payload** ([backend/app/notifications/base.py:7-16](backend/app/notifications/base.py#L7-L16)) carries `saved_search_id`, `search_name`, `user_id`, `new_listing_ids`, `new_listing_titles`, `total_new`. `NotificationPlugin` ABC ([base.py:19-30](backend/app/notifications/base.py#L19-L30)): `is_configured()` + `send(MatchResult) -> bool`.
- **Dispatch trigger** — exactly one: [`backend/app/services/search_matcher.py:117-125`](backend/app/services/search_matcher.py#L117-L125) builds a `MatchResult` and calls `notification_registry.dispatch(match_result)`. Unchanged.
- **TelegramPlugin** ([backend/app/telegram/plugin.py:39-95](backend/app/telegram/plugin.py)) is the structural template for `WebPushPlugin.send()`: fetch user, check `prefs.new_search_results`, format digest, deliver. **Deleted** in this plan; `WebPushPlugin` replaces it.
- **Favorites sweep** ([backend/app/telegram/fav_sweep.py](backend/app/telegram/fav_sweep.py)) — `run_fav_status_sweep()` queries `user_favorites JOIN listings JOIN users WHERE u.telegram_chat_id IS NOT NULL`, diffs against `last_known_*` snapshots via `_detect_events()` (respecting `user_prefs.fav_sold/fav_price/fav_deleted`), sends HTML via `bot.send_message(chat_id, ...)`, always updates the snapshot, then prunes link tokens. Currently gated `if not settings.telegram_enabled: return 0` at the top ([fav_sweep.py:75](backend/app/telegram/fav_sweep.py#L75)) and scheduled in `main.py` ([main.py:101-109](backend/app/main.py#L101-L109)). Migrated to `app/notifications/fav_sweep.py` (Task 9).
- **Prefs module** ([backend/app/telegram/prefs.py](backend/app/telegram/prefs.py)) — the only non-Telegram code under `app/telegram/`. Defines frozen dataclass `NotificationPrefs(user_id, new_search_results, fav_sold, fav_price, fav_deleted)` + async `get_prefs(user_id)` (upsert-then-SELECT, creates default row) + `set_prefs(user_id, **partial)` (whitelist of the four booleans). Imported by `plugin.py`, `fav_sweep.py`, `api/telegram.py`, and tests. **Moved** to `app/notifications/prefs.py` (Task 4).
- **Importers of `app.telegram.prefs`** (verified by grep, 2026-05-30): `app/telegram/plugin.py:13`, `app/telegram/fav_sweep.py:18`, `app/api/telegram.py:9`, `backend/tests/test_telegram_plugin.py:55`, `backend/tests/test_telegram_prefs.py:4`, `backend/tests/test_telegram_fav_sweep.py:8`. All telegram modules/tests are deleted; remaining live importers after deletion = the new `web_push_plugin.py` + `fav_sweep.py` + `api/notifications.py` (all created against the new path).
- **Existing prefs table** `user_notification_prefs` ([backend/app/db.py:176-186](backend/app/db.py#L176-L186)) — columns `user_id PK`, `new_search_results`, `fav_sold`, `fav_price`, `fav_deleted`, `fav_indicator`, `updated_at`. The `fav_indicator` column is dropped later in the same `init_db()` at [db.py:253-255](backend/app/db.py#L253-L255) (PLAN-025). We **extend** this table with `web_push_enabled` (Task 3).
- **Telegram API router** is included in [`backend/app/api/routes.py:12,31`](backend/app/api/routes.py#L12) (`from app.api.telegram import router as telegram_api_router` / `router.include_router(telegram_api_router)`) — **NOT** in `main.py`. (`app/api/telegram.py` defines `/telegram/link`, `/unlink`, `/prefs` GET+PUT.) Removed in Task 7.5. The inbound webhook router `telegram_webhook_router` IS in `main.py` ([main.py:21,239](backend/app/main.py#L21)).
- **`/api/auth/me`** ([backend/app/api/auth.py:133-157](backend/app/api/auth.py#L133-L157)) re-fetches `telegram_chat_id, telegram_linked_at` and returns them in the response dict ([auth.py:144-156](backend/app/api/auth.py#L144-L156)). The telegram fields are stripped in Task 7.6.
- **No Alembic.** Schema evolution is inline in [`backend/app/db.py:init_db()`](backend/app/db.py#L18) — idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD/DROP COLUMN IF [NOT] EXISTS`, runs on every startup. Plan follows this convention.
- **Test schema bootstrap** in [`backend/tests/conftest.py:48-89`](backend/tests/conftest.py#L48) drops `user_notification_prefs` + `telegram_link_tokens` (lines 49-50) before `Base.metadata.drop_all()`, then recreates telegram columns/tables (lines 61-78) + `user_notification_prefs` (lines 80-89). The autouse `patch_async_session_local` fixture redirects `AsyncSessionLocal` for a `_patch_targets` list ([conftest.py:132-138](backend/tests/conftest.py#L132)) that today lists five `app.telegram.*` modules. Telegram fixtures: `db_user_linked` ([conftest.py:259-275](backend/tests/conftest.py#L259)) and `authenticated_client_linked` ([conftest.py:346-388](backend/tests/conftest.py#L346)) seed `telegram_chat_id`. All updated in Task 3 + Task 6.
- **REST module pattern**: [backend/app/api/telegram.py:6](backend/app/api/telegram.py#L6) imports `from app.api.deps import get_current_user` (defined at [deps.py:12](backend/app/api/deps.py#L12)). Mirror exactly.
- **PWA infra is partially in place but legacy.** [frontend/public/sw.js](frontend/public/sw.js) (static placeholder) + [frontend/public/manifest.json](frontend/public/manifest.json) (display:standalone, 5 icon entries) exist; icons at `frontend/public/icons/{icon-192,icon-512,icon-maskable-192,icon-maskable-512,apple-touch-icon-180}.png`; [frontend/index.html:10](frontend/index.html#L10) has `<link rel="manifest" href="/manifest.json">`; [frontend/src/main.tsx:27-31](frontend/src/main.tsx#L27-L31) registers `/sw.js` manually. All replaced/removed in Tasks 11.5 + 12.
- **Prod build path.** [.github/workflows/deploy.yml](.github/workflows/deploy.yml) builds the frontend via [frontend/Dockerfile](frontend/Dockerfile) (no `.prod` variant). The nginx/frontend build step is at [deploy.yml:39-47](.github/workflows/deploy.yml#L39-L47). `docker-compose.prod.yml` pulls a prebuilt GHCR image. Task 20 wires `VITE_VAPID_PUBLIC_KEY`.
- **InstallPrompt** ([frontend/src/components/InstallPrompt.tsx](frontend/src/components/InstallPrompt.tsx)): visual template — `fixed bottom-[72px]`, `sm:hidden`, `rgba(15,15,35,0.92)` glassmorphism, indigo accents, `localStorage` dismissal, local `isStandalone()` ([InstallPrompt.tsx:13-18](frontend/src/components/InstallPrompt.tsx#L13)) + `isIos()` ([InstallPrompt.tsx:20-22](frontend/src/components/InstallPrompt.tsx#L20)) — extracted to `lib/pwa-detect.ts` in Task 11.
- **Mount point.** [frontend/src/App.tsx:223](frontend/src/App.tsx#L223) renders `<InstallPrompt />`. `<FirstStartPushPrompt />` mounts directly after (Task 19).
- **ProfilePage** ([frontend/src/pages/ProfilePage.tsx:237-240](frontend/src/pages/ProfilePage.tsx#L237-L240)) renders Column 2 as `<TelegramPanel user={user} onUserReload={onUserReload} /> {user.role === 'admin' && <LLMAdminPanel />}`. `TelegramPanel` is **replaced** by `<NotificationsPanel />` (Task 19); the `onUserReload` prop becomes unused and the import is removed.
- **TelegramPanel** ([frontend/src/components/TelegramPanel.tsx](frontend/src/components/TelegramPanel.tsx)) + its test ([frontend/src/components/__tests__/TelegramPanel.test.tsx](frontend/src/components/__tests__/TelegramPanel.test.tsx)) — **deleted** (Task 7.7). It owns the reusable `role="switch"` toggle markup ([TelegramPanel.tsx:306-338](frontend/src/components/TelegramPanel.tsx#L306)) and the optimistic-toggle-with-revert pattern ([TelegramPanel.tsx:171-188](frontend/src/components/TelegramPanel.tsx#L171)) — both **mirrored** into `NotificationsPanel` (Task 18b) before deletion. The toggle markup is copied verbatim there since the source file is removed.
- **Frontend telegram surfaces** (verified by grep `[Tt]elegram` in `frontend/src`, 2026-05-30): `types/api.ts` (`NotificationPrefs` + `TelegramLinkResponse`), `api/client.ts` (`linkTelegram`, `unlinkTelegram`, `getNotificationPrefs`, `updateNotificationPrefs`, `TelegramLinkResponse` import), `pages/ProfilePage.tsx`, `components/TelegramPanel.tsx` + test, `__tests__/ModalRouting.test.tsx` (seeds `telegram_chat_id`/`telegram_linked_at` in the mocked user at lines 38, 204), `hooks/useAuth.ts` (`AuthUser.telegram_chat_id`/`telegram_linked_at`). `PlzBar.tsx` matched the grep only via the substring `gram` inside other words — **no actual telegram code** (verified: grep `telegram` → no matches). All real surfaces handled in Tasks 7.7, 14.

### Verified signatures (no false references)

```text
backend/app/notifications/base.py:8       @dataclass MatchResult(saved_search_id, search_name, user_id, new_listing_ids, new_listing_titles, total_new)
backend/app/notifications/base.py:19      class NotificationPlugin(ABC) — is_configured() + send(MatchResult)->bool
backend/app/notifications/registry.py:35  notification_registry: NotificationRegistry (singleton)
backend/app/services/search_matcher.py:125 await notification_registry.dispatch(match_result)
backend/app/api/deps.py:12                async def get_current_user(...) -> User
backend/app/telegram/prefs.py:12-18       @dataclass NotificationPrefs(user_id,new_search_results,fav_sold,fav_price,fav_deleted) — MOVED
backend/app/telegram/prefs.py:21          async def get_prefs(user_id) -> NotificationPrefs — MOVED
backend/app/telegram/prefs.py:40          async def set_prefs(user_id, **partial) -> NotificationPrefs — MOVED
backend/app/telegram/fav_sweep.py:69      async def run_fav_status_sweep() -> int — MIGRATED to app/notifications/fav_sweep.py
backend/app/telegram/fav_sweep.py:34      def _detect_events(row, deleted_cutoff, user_prefs) -> list[str] — MIGRATED
backend/app/db.py:18                       async def init_db() — idempotent migrations
backend/app/db.py:153-175                 PLAN-019 telegram DDL (chat_id col, unique idx, linked_at col, link_tokens table+idx) — DROPPED
backend/app/db.py:176-186                 CREATE TABLE user_notification_prefs (incl. legacy fav_indicator)
backend/app/db.py:253-255                 ALTER TABLE user_notification_prefs DROP COLUMN fav_indicator (PLAN-025)
backend/app/config.py:77-92               TELEGRAM_* settings + telegram_enabled property — REMOVED/renamed
backend/app/main.py:21                     from app.telegram.webhook import router as telegram_webhook_router — REMOVED
backend/app/main.py:25                     from app.telegram.plugin import TelegramPlugin — REMOVED
backend/app/main.py:49-57                 plugin registration block (LogPlugin + TelegramPlugin)
backend/app/main.py:101-109               fav_sweep scheduler — gated on telegram_enabled (UNGATED + retargeted)
backend/app/main.py:196-219               setWebhook block — REMOVED
backend/app/main.py:239                    app.include_router(telegram_webhook_router) — REMOVED
backend/app/api/routes.py:12,31           telegram_api_router import + include — REMOVED
backend/app/api/auth.py:144-156           /auth/me returns telegram_chat_id + telegram_linked_at — STRIPPED
backend/tests/conftest.py:49-50           DROP user_notification_prefs + telegram_link_tokens
backend/tests/conftest.py:61-78           recreate telegram columns + telegram_link_tokens + idx — REMOVED
backend/tests/conftest.py:80-89           CREATE user_notification_prefs (4 booleans + updated_at) — add web_push_enabled
backend/tests/conftest.py:132-138         _patch_targets (5 app.telegram.* entries) — replaced
backend/tests/conftest.py:259-275         db_user_linked fixture — REMOVED
backend/tests/conftest.py:346-388         authenticated_client_linked fixture — REMOVED
frontend/src/api/client.ts:19             async function handleResponse<T>(res: Response)
frontend/src/api/client.ts:167-189        linkTelegram/unlinkTelegram/getNotificationPrefs/updateNotificationPrefs
frontend/src/types/api.ts:224-229         interface NotificationPrefs — EXTENDED with web_push_enabled
frontend/src/types/api.ts:231-234         interface TelegramLinkResponse — REMOVED
frontend/src/hooks/useAuth.ts:3-10        AuthUser (incl. telegram_chat_id/telegram_linked_at) — fields REMOVED
frontend/src/components/InstallPrompt.tsx:13 isStandalone() — extracted in Task 11
frontend/src/components/InstallPrompt.tsx:20 isIos() — extracted in Task 11
frontend/src/components/TelegramPanel.tsx:306-338 role="switch" toggle markup — mirrored then file DELETED
frontend/src/pages/ProfilePage.tsx:237-240 Column 2 (TelegramPanel) — TelegramPanel replaced
frontend/src/App.tsx:223                   <InstallPrompt /> — FirstStartPushPrompt mounts after
frontend/src/main.tsx:27-31                manual SW registration — DELETED in Task 11.5
frontend/__tests__/ModalRouting.test.tsx:38,204 mocked user has telegram fields — REMOVED in Task 14
frontend/index.html:10                     <link rel="manifest"> — DELETED in Task 11.5
frontend/nginx.conf:14                     location = /sw.js no-cache rule — sw output filename must stay sw.js
frontend/vite.config.ts                    defineConfig from vitest/config; plugins:[react()]; test.globals:true
frontend/package.json:8                    "build": "tsc -b && vite build"
frontend/package.json:11                   "test": "vitest"
frontend/Dockerfile                        single Dockerfile, no .prod variant
.github/workflows/deploy.yml:39-47         nginx/frontend build step (no build-args today)
docker-compose.yml:42-44                   TELEGRAM_* backend env — REMOVED, VAPID added
docker-compose.prod.yml:25-34              prod backend env block (no telegram vars today) — VAPID added
env.prod.example:18-24                     TELEGRAM_* block — REMOVED, VAPID added
```

### Locked decisions

| Topic | Decision |
|---|---|
| Channel | Web Push is the **only** channel. No `NOTIFICATION_CHANNEL` switch. |
| Telegram | Removed entirely (code, routes, settings, DB columns/table, frontend, tests). |
| Prefs location | `NotificationPrefs` + get/set moved to `app/notifications/prefs.py`. |
| Trigger | One — `MatchResult` from `search_matcher.py` (unchanged dispatch). |
| Fav sweep | Migrated to `app/notifications/fav_sweep.py`; selects users with ≥1 push subscription; delivers via shared `send_web_push_to_user`; ungated scheduler; renamed interval/cutoff settings. `fav_sold/fav_price/fav_deleted` opt-ins preserved. |
| Send helper | `send_web_push_to_user(user_id, payload)` in `web_push_plugin.py` — owns send loop + 404/410 GC + per-delivered `last_used_at` bump. Used by plugin AND fav sweep (DRY). |
| Multi-device | N `push_subscriptions` rows per user; each `device_label`, `last_used_at`, individually deletable. |
| Prefs consolidation | Single source at `/api/notifications/preferences`. |
| Permission UX | First-app-start banner after login; gated by `localStorage["rcn_notif_asked"]`; mirrors InstallPrompt shell. |
| iOS | Push works only when PWA installed (Safari 16.4+). Banner suppressed on iOS Safari without standalone. |
| VAPID storage | Env vars; local in `docker-compose.yml`, prod in GH repo var + VPS `.env`, frontend build via `VITE_VAPID_PUBLIC_KEY` build-arg. Public key also returned from `/api/notifications/vapid-public-key` so dev works without a build-time arg. |
| Migrations | Inline in `init_db()`. No Alembic. Test schema mirrored in `conftest.py`. |
| SW update reliability | Adopt the minimal half of Do-It's PLAN_037: SW `message` SKIP_WAITING handler + nginx no-cache for `index.html`. Skip the periodic-update React hook (YAGNI for single-user hobby). See Task 12.5. |
| Package manager | npm (canonical). |
| Cost | Zero. `pywebpush` MIT; VAPID generated locally. No paid API calls. |

### Concept reference (Do-It / "Do It!", NestJS — NOT copied, different stack)

Verified against `D:\DEVELOPMENT\_workplace_AI\ToDoList` on 2026-05-30. Stack differs (NestJS+Prisma+`web-push` npm vs. FastAPI+SQLAlchemy+`pywebpush`); concepts adopted, code not:
- `apps/api/src/notifications/web-push-notification-provider.ts` — confirms the send pattern: load subs → `Promise.allSettled` send → collect `stale` (404/410) and `succeeded` ids → `deleteMany({where:{userId, id:{in:stale}}})` (scoped by userId, defense-in-depth) → bump `lastUsedAt` **only for succeeded** subs. **Two refinements folded into our helper vs. the old plan:** (a) GC delete is scoped by `user_id AND id IN (...)`, not `id IN (...)` alone; (b) `last_used_at` is bumped only for subscriptions that actually delivered, not blanket per-user.
- `apps/web/src/service-worker.ts` — confirms push/notificationclick handlers, `assertSafeNotificationUrl` open-redirect guard (relative-`/`-only), exact-pathname client match (substring match would route `/lists/1` to `/lists/10`), and a `SKIP_WAITING` `message` handler. Our SW uses an in-app URL (`/?saved_search=…`), so we keep the safe-URL guard and pathname-exact match.
- `apps/web/src/notifications/{useWebPushSubscription.ts,api.ts,FirstStartPushPrompt.tsx}`, `apps/web/src/features/profile/{ProfileNotifications.tsx,DeviceListSection.tsx}` — confirm the hook/state-machine, the subscriptions client, and the device-list UI shape.
- `docs/archive/PLAN_037_pwa_update_reliability.md` (approved 2026-05-05, **after** this plan's original review) — root cause: with VitePWA `autoUpdate` + `injectManifest`, a new SW stays in `waiting` indefinitely without a `SKIP_WAITING` `message` handler, and browsers serve a stale `index.html` without an nginx no-cache rule. We adopt the SW handler + nginx rule (Task 12.5). We skip Do-It's `usePwaUpdate` resume/30-min polling hook (YAGNI here). Note: our `sw.ts` calls `self.skipWaiting()` in the `install` handler unconditionally, which is a simpler equivalent for a single-user app — the explicit message handler is added belt-and-suspenders so a future `registerType` change does not silently strand updates.

### Reuse Check (verified by grep, 2026-05-30)

- **NotificationPlugin ABC / `notification_registry`** — exist. Reused unchanged.
- **`user_notification_prefs` table** — exists. Extended in place with `web_push_enabled BOOLEAN NOT NULL DEFAULT TRUE`.
- **`NotificationPrefs` TS interface** — exists at `types/api.ts:224-229`. Extended in place with `web_push_enabled: boolean`. **Reuse check:** extends existing interface; not duplicated.
- **InstallPrompt shell + helpers** — `grep -rln "fixed bottom-" frontend/src` shows only `InstallPrompt.tsx`. **Extract** `isIos()` + `isStandalone()` + new `pushSupported()` into `frontend/src/lib/pwa-detect.ts`. **Reuse check:** extracts shared helpers from `InstallPrompt.tsx`.
- **ProfilePage `cardStyle`** — local `const cardStyle` at [ProfilePage.tsx:76-82](frontend/src/pages/ProfilePage.tsx#L76). NotificationsPanel re-declares the same style locally. **Reuse check:** reuses inline `cardStyle` shape; no extraction (YAGNI for two callers).
- **API client** — `frontend/src/api/client.ts` (bare `fetch` + `handleResponse`). **Reuse check:** new `notifications/api.ts` follows the same pattern; the consolidated prefs functions stay in `client.ts` (retargeted, renamed-free).
- **Toggle/switch component** — the `role="switch"` markup lives only in `TelegramPanel.tsx:306-338`, which is **deleted** in this plan. **Reuse check:** the markup is mirrored verbatim into `NotificationsPanel` (Task 18b) before TelegramPanel is removed; no shared component extraction (YAGNI — single remaining caller).
- **Optimistic-toggle-with-revert** — pattern at `TelegramPanel.tsx:171-188`. **Reuse check:** mirrored into `NotificationsPanel.handleTogglePush` (Task 18b).
- **PWA manifest content** — already correct in `public/manifest.json`. **Reuse check:** migrate verbatim into VitePWA `manifest:` config incl. all five icon entries + maskable purposes.

### Files structure (final)

**Backend (new):**
```
backend/app/notifications/prefs.py
backend/app/notifications/fav_sweep.py
backend/app/notifications/web_push_plugin.py
backend/app/api/notifications.py
backend/tests/test_notifications_prefs.py
backend/tests/test_web_push_plugin.py
backend/tests/test_notifications_fav_sweep.py
backend/tests/test_notifications_api.py
```

**Backend (modified):**
- `backend/requirements.txt` — add `pywebpush>=2.0`
- `backend/app/config.py` — remove all `TELEGRAM_*` settings + `telegram_enabled`; rename two fav-sweep settings; add `VAPID_*` + `web_push_enabled` property
- `backend/app/models.py` — add `PushSubscription` ORM model
- `backend/app/db.py:init_db()` — append `CREATE TABLE push_subscriptions` + `ALTER … ADD web_push_enabled`; append idempotent `DROP TABLE telegram_link_tokens` + `ALTER … DROP telegram_chat_id/telegram_linked_at`
- `backend/app/main.py` — remove telegram imports/registration/setWebhook/webhook-include; register `WebPushPlugin`; ungate + retarget fav_sweep scheduler; mount notifications router
- `backend/app/api/routes.py` — remove telegram_api_router import + include
- `backend/app/api/auth.py` — strip telegram fields from `/auth/me`
- `backend/tests/conftest.py` — drop telegram schema/fixtures; add `web_push_enabled` + `push_subscriptions`; update `_patch_targets`; add new fixtures
- `docker-compose.yml`, `docker-compose.prod.yml`, `env.prod.example` — remove `TELEGRAM_*`, add `VAPID_*` + renamed fav-sweep vars

**Backend (deleted):**
```
backend/app/telegram/                       (entire package: __init__.py, bot.py, link.py, plugin.py, prefs.py, fav_sweep.py, webhook.py)
backend/app/api/telegram.py
backend/tests/test_telegram_api.py
backend/tests/test_telegram_bot.py
backend/tests/test_telegram_link.py
backend/tests/test_telegram_plugin.py
backend/tests/test_telegram_prefs.py
backend/tests/test_telegram_webhook.py
backend/tests/test_telegram_fav_sweep.py
```

**Frontend (new):**
```
frontend/src/sw.ts
frontend/src/lib/pwa-detect.ts
frontend/src/lib/__tests__/pwa-detect.test.ts
frontend/src/notifications/api.ts
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
- `frontend/package.json` / `package-lock.json` — add `vite-plugin-pwa@^0.21`, `workbox-window@^7`, `workbox-precaching@^7`
- `frontend/vite.config.ts` — wire `VitePWA({ injectManifest, srcDir:'src', filename:'sw.ts', registerType:'autoUpdate', injectRegister:'auto', manifest:<migrated> })`
- `frontend/index.html` — remove `<link rel="manifest">` (line 10)
- `frontend/src/main.tsx` — remove manual SW registration (lines 27-31)
- `frontend/nginx.conf` — add `location = /index.html` no-cache block (Task 12.5)
- `frontend/src/components/InstallPrompt.tsx` — import `isIos`/`isStandalone` from `lib/pwa-detect`
- `frontend/src/types/api.ts` — extend `NotificationPrefs`; remove `TelegramLinkResponse`; add `PushSubscriptionDto`, `CreatePushSubscriptionDto`, `VapidKeyDto`
- `frontend/src/api/client.ts` — remove `linkTelegram`/`unlinkTelegram` + `TelegramLinkResponse` import; retarget `getNotificationPrefs`/`updateNotificationPrefs` to `/api/notifications/preferences`
- `frontend/src/hooks/useAuth.ts` — remove `telegram_chat_id`/`telegram_linked_at` from `AuthUser`
- `frontend/src/__tests__/ModalRouting.test.tsx` — remove telegram fields from mocked user (lines 38, 204)
- `frontend/src/App.tsx` — mount `<FirstStartPushPrompt />` after `<InstallPrompt />`
- `frontend/src/pages/ProfilePage.tsx` — replace `<TelegramPanel>` with `<NotificationsPanel>`; drop unused import/prop
- `frontend/Dockerfile` — `ARG VITE_VAPID_PUBLIC_KEY` + `ENV` before build
- `.github/workflows/deploy.yml` — pass `--build-arg VITE_VAPID_PUBLIC_KEY`

**Frontend (deleted):**
- `frontend/src/components/TelegramPanel.tsx`
- `frontend/src/components/__tests__/TelegramPanel.test.tsx`
- `frontend/public/sw.js`
- `frontend/public/manifest.json`
- `frontend/pnpm-lock.yaml` (if present — npm is canonical)

**Docs (modified):**
- `docs/definition.md` §F5 — flip to active; note Telegram removed
- `docs/architektur.md` — add "Notification Channel (Web Push)" section; remove Telegram references
- `docs/limitations.md` — add "iOS Web Push requires PWA install"

---

## Tasks

> **Parallelism:** Backend Tasks 1–9 run after Task 1 (some depend on 3/4). Frontend Tasks 10–22 run after Task 10. Backend and frontend layers are otherwise independent, with **one exception: Task 7.7 (final Telegram deletion) is the cross-layer join point** — it depends on frontend Tasks 14 + 19 having retargeted all importers, so Task 7.7 must run last (after both layers complete). Its Step 1 verification grep enforces this. Doc Tasks 23–25 require implementation done.
> **No BREAKs.** All tasks are non-destructive on shared/prod state; the coder can self-recover from any single-task failure (per `dglabs.writing-plans` BREAK policy). DB drops are idempotent and dev/test-only at execution time.

---

### Task 1: Backend dependency [IMPLEMENTED]

**Files:** Modify `backend/requirements.txt`

**Step 1: Append**

```text
pywebpush>=2.0
```

**Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(backend): add pywebpush for PLAN-027"
```

---

### Task 2: Backend config — VAPID, remove Telegram, rename fav-sweep settings [IMPLEMENTED]

**Depends on:** Task 1

**Files:** Modify `backend/app/config.py`

**Step 1: Remove the Telegram block** (`config.py:77-92`): delete `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_LINK_TOKEN_TTL_MIN`, `TELEGRAM_DIGEST_TOP_N`, and the `telegram_enabled` property.

**Step 2: Add the replacement block** in the same place (after `ebay_client_secret`, before `openrouter_free_models_list`):

```python
    # Favorites status sweep (was TELEGRAM_FAV_*)
    FAV_SWEEP_INTERVAL_MIN: int = 60
    FAV_DELETED_DAYS: int = 3

    # Web Push (VAPID) — push disabled (no crash) when any field is empty
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:marco.roth1983@googlemail.com"

    @property
    def web_push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY and self.VAPID_SUBJECT)
```

**Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): add VAPID, remove Telegram settings, rename fav-sweep knobs"
```

---

### Task 3: Backend schema — push_subscriptions, web_push_enabled, drop Telegram DDL, test bootstrap [IMPLEMENTED]

**Depends on:** Task 1

**Files:** Modify `backend/app/db.py`, `backend/app/models.py`, `backend/tests/conftest.py`

**Step 1: Append idempotent DDL** at the end of `init_db()` in `backend/app/db.py` (after the PLAN-025 block at line 255):

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
        # PLAN-027: Telegram removed — drop its table + columns (idempotent, no migration)
        await conn.execute(text("DROP TABLE IF EXISTS telegram_link_tokens CASCADE"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS telegram_chat_id"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS telegram_linked_at"))
```

**Step 1b: Delete the dead PLAN-019 Telegram DDL** in `backend/app/db.py` (lines **153-175**, verified 2026-05-30). These statements create the `telegram_chat_id` column, the `ux_users_telegram_chat_id` unique index, the `telegram_linked_at` column, the `telegram_link_tokens` table, and the `ix_telegram_link_tokens_user` index — all of which the Step 1 drops now immediately undo within the same `init_db()` run (a no-net-effect create-then-drop cycle). Delete this exact block:

```python
        # PLAN-019: Telegram notifications
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_chat_id
            ON users (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL
        """))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at  TIMESTAMPTZ NOT NULL,
                used_at     TIMESTAMPTZ
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_telegram_link_tokens_user ON telegram_link_tokens (user_id)"
        ))
```

The `user_notification_prefs` CREATE that immediately follows (currently `db.py:176-186`) stays — only the Telegram column/index/table statements above it are removed.

**Step 2: Add ORM model** in `backend/app/models.py` (after `UserFavorite`, the last class):

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

(`Integer`, `Text`, `ForeignKey`, `DateTime`, `func`, `Mapped`, `mapped_column` are all already imported in `models.py`.)

**Step 3: Update test bootstrap** in `backend/tests/conftest.py`:

3a. **Drop list** (lines 49-50): replace the two telegram-aware drops with the push + prefs drops (telegram tables no longer exist in the new schema):

```python
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS push_subscriptions CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS user_notification_prefs CASCADE"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
```

3b. **Remove the PLAN-019 telegram bootstrap** (lines 61-78): delete the `telegram_chat_id` column add, the `ux_users_telegram_chat_id` index, the `telegram_linked_at` column add, and the `telegram_link_tokens` table + index.

3c. **`user_notification_prefs` CREATE** (lines 80-89): add `web_push_enabled` and append the `push_subscriptions` table + index. Final block:

```python
        # PLAN-019/027: user_notification_prefs table
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

3d. **`_patch_targets`** (lines 132-138): replace the five `app.telegram.*` entries with the new module paths (these `from app.db import AsyncSessionLocal` at module scope):

```python
    _patch_targets = [
        "app.notifications.prefs",          # PLAN-027
        "app.notifications.web_push_plugin", # PLAN-027
        "app.notifications.fav_sweep",       # PLAN-027
    ]
```

**Step 4: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/tests/conftest.py
git commit -m "feat(db): push_subscriptions + web_push_enabled; drop telegram schema (prod + test)"
```

---

### Task 4: Move NotificationPrefs to app/notifications/prefs.py [IMPLEMENTED]

**Depends on:** Task 3

**Files:** Create `backend/app/notifications/prefs.py`, create `backend/tests/test_notifications_prefs.py`

**Step 1: Create `backend/app/notifications/prefs.py`** — moved from `app/telegram/prefs.py`, with `web_push_enabled` added:

```python
"""Per-user notification prefs — 5 booleans, defaults TRUE. (Moved from app.telegram.prefs in PLAN-027.)"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.db import AsyncSessionLocal


@dataclass(frozen=True)
class NotificationPrefs:
    user_id: int
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    web_push_enabled: bool


async def get_prefs(user_id: int) -> NotificationPrefs:
    """Return prefs; creates default row if missing (upsert no-op then SELECT)."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
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


async def set_prefs(user_id: int, **partial: bool | None) -> NotificationPrefs:
    """Partial update: only fields passed as non-None are written."""
    updates = []
    params: dict = {"uid": user_id}
    for field in ("new_search_results", "fav_sold", "fav_price", "fav_deleted", "web_push_enabled"):
        val = partial.get(field)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val
    if not updates:
        return await get_prefs(user_id)

    set_clause = ", ".join(updates + ["updated_at = now()"])
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        await session.execute(
            text(f"UPDATE user_notification_prefs SET {set_clause} WHERE user_id = :uid"),
            params,
        )
        await session.commit()
    return await get_prefs(user_id)
```

**Step 2: Tests** — `backend/tests/test_notifications_prefs.py` (mirrors the old `test_telegram_prefs.py` against the new path + the new field):

```python
"""Tests for app.notifications.prefs — notification preference upsert."""

import pytest

from app.notifications import prefs


@pytest.mark.asyncio
async def test_get_prefs_creates_default_row(db_user):
    p = await prefs.get_prefs(db_user.id)
    assert p.new_search_results is True
    assert p.fav_sold is True
    assert p.fav_price is True
    assert p.fav_deleted is True
    assert p.web_push_enabled is True


@pytest.mark.asyncio
async def test_set_prefs_partial_update(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is False
    assert p.fav_price is True  # untouched


@pytest.mark.asyncio
async def test_set_prefs_web_push_enabled_toggle(db_user):
    await prefs.set_prefs(db_user.id, web_push_enabled=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.web_push_enabled is False


@pytest.mark.asyncio
async def test_set_prefs_no_fields_is_noop(db_user):
    p = await prefs.set_prefs(db_user.id)  # nothing to write
    assert p.new_search_results is True
```

**Step 3: Commit**

```bash
git add backend/app/notifications/prefs.py backend/tests/test_notifications_prefs.py
git commit -m "feat(notifications): move NotificationPrefs out of telegram, add web_push_enabled"
```

---

### Task 5: WebPushPlugin + shared send helper [IMPLEMENTED]

**Depends on:** Tasks 2, 3, 4

**Files:** Create `backend/app/notifications/web_push_plugin.py`

**Step 1: Implement** — note `send_web_push_to_user` is module-level and reused by the fav sweep (Task 9). GC delete is scoped by `user_id`; `last_used_at` is bumped only for delivered subs (Do-It refinement).

```python
"""WebPushPlugin + shared send helper — delivers payloads as Web Push notifications."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pywebpush import WebPushException, webpush
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications import prefs as prefs_module
from app.notifications.base import MatchResult, NotificationPlugin

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Subscription:
    id: int
    endpoint: str
    p256dh: str
    auth: str


async def send_web_push_to_user(user_id: int, payload: dict) -> bool:
    """Send `payload` (dict with title/body/url/tag) to every push_subscription of `user_id`.

    Garbage-collects 404/410 (Gone/Not Found) subscriptions and bumps last_used_at
    only for subscriptions that actually delivered. Returns True if at least one
    delivery succeeded. VAPID config is the caller's responsibility (checked via
    settings.web_push_enabled before calling).
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
                    "WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).all()
    subs = [_Subscription(r[0], r[1], r[2], r[3]) for r in rows]
    if not subs:
        return False

    data = json.dumps(payload)
    succeeded_ids: list[int] = []
    stale_ids: list[int] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
            )
            succeeded_ids.append(sub.id)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response else None
            if status in (404, 410):
                stale_ids.append(sub.id)
                logger.info("web_push: stale subscription id=%d (status=%s) — removing", sub.id, status)
            else:
                logger.warning("web_push: send failed sub_id=%d status=%s err=%s", sub.id, status, exc)

    if stale_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM push_subscriptions WHERE user_id = :uid AND id = ANY(:ids)"),
                {"uid": user_id, "ids": stale_ids},
            )
            await session.commit()

    if succeeded_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE push_subscriptions SET last_used_at = now() WHERE id = ANY(:ids)"),
                {"ids": succeeded_ids},
            )
            await session.commit()

    return bool(succeeded_ids)


def _build_search_payload(match: MatchResult) -> dict:
    top = match.new_listing_titles[:3]
    body_lines = list(top)
    if match.total_new > len(top):
        body_lines.append(f"… und {match.total_new - len(top)} weitere")
    return {
        "title": f"Neue Treffer: {match.search_name}",
        "body": "\n".join(body_lines),
        "url": f"/?saved_search={match.saved_search_id}",
        "tag": f"saved-search-{match.saved_search_id}",
    }


class WebPushPlugin(NotificationPlugin):
    """Sends a SavedSearch digest to every push_subscription belonging to the user."""

    async def is_configured(self) -> bool:
        return settings.web_push_enabled

    async def send(self, match: MatchResult) -> bool:
        p = await prefs_module.get_prefs(match.user_id)
        if not p.web_push_enabled or not p.new_search_results:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d skipped (pref off)",
                match.saved_search_id, match.user_id,
            )
            return False
        ok = await send_web_push_to_user(match.user_id, _build_search_payload(match))
        if not ok:
            logger.info(
                "web_push.plugin: search_id=%d user_id=%d no delivery (no subs or all failed)",
                match.saved_search_id, match.user_id,
            )
        return ok
```

> **URL note:** payload `url` is an in-app relative path (`/?saved_search=…`); the SW guards it with `assertSafeNotificationUrl` (Task 13). The old plan used `settings.PUBLIC_BASE_URL/...` absolute URLs — relative is preferred (origin-safe, matches Do-It).

**Step 2: Commit**

```bash
git add backend/app/notifications/web_push_plugin.py
git commit -m "feat(notifications): WebPushPlugin + shared send_web_push_to_user helper"
```

---

### Task 6: WebPushPlugin + helper tests + new fixtures [IMPLEMENTED]

**Depends on:** Task 5

**Files:** Create `backend/tests/test_web_push_plugin.py`, modify `backend/tests/conftest.py`

**Step 1: New fixtures in `conftest.py`** (append after `db_listing`; reuse the existing `dataclass` import at line 233):

```python
@dataclass
class _UserWithSubs:
    user_id: int
    sub_ids: list[int]


@pytest_asyncio.fixture()
async def seeded_user_with_subs(db_session: AsyncSession) -> _UserWithSubs:
    """Insert a user + two push_subscription rows."""
    from sqlalchemy import text as _text  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved)
            VALUES ('seed-subs-google', 'seed_subs@example.com', 'Seed Subs', TRUE)
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
                VALUES (:uid, :ep, 'P', 'A', 'Test Device') RETURNING id
            """),
            {"uid": user_id, "ep": endpoint},
        )
        sub_ids.append(row.scalar_one())
    await db_session.commit()
    return _UserWithSubs(user_id=user_id, sub_ids=sub_ids)


@pytest_asyncio.fixture()
async def other_user_with_sub(db_session: AsyncSession) -> _UserWithSubs:
    """Insert a different user + one subscription — for ownership-isolation tests."""
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
            VALUES (:uid, 'https://other-user-endpoint', 'P', 'A', 'Other Device') RETURNING id
        """),
        {"uid": user_id},
    )
    await db_session.commit()
    return _UserWithSubs(user_id=user_id, sub_ids=[row.scalar_one()])
```

**Step 2: Plugin + helper tests** — `backend/tests/test_web_push_plugin.py`:

```python
"""Tests for WebPushPlugin + send_web_push_to_user — mocks pywebpush, real DB rows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pywebpush import WebPushException
from sqlalchemy import text

from app.notifications.base import MatchResult
from app.notifications.web_push_plugin import WebPushPlugin, send_web_push_to_user


def _match(user_id: int) -> MatchResult:
    return MatchResult(
        saved_search_id=1, search_name="Wing 2.5m", user_id=user_id,
        new_listing_ids=[10, 11, 12], new_listing_titles=["A", "B", "C"], total_new=3,
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
async def test_helper_deletes_subscription_on_410_gone(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=410)
    def raise_gone(**_):
        raise WebPushException("gone", response=response)
    monkeypatch.setattr(mod, "webpush", raise_gone)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_helper_deletes_subscription_on_404(monkeypatch, seeded_user_with_subs, db_session):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=404)
    def raise_404(**_):
        raise WebPushException("not found", response=response)
    monkeypatch.setattr(mod, "webpush", raise_404)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": seeded_user_with_subs.user_id},
    )).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_helper_does_not_delete_other_users_subscription_on_410(
    monkeypatch, seeded_user_with_subs, other_user_with_sub, db_session
):
    """GC must be scoped by user_id — a 410 for user A never removes user B's row."""
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=410)
    def raise_gone(**_):
        raise WebPushException("gone", response=response)
    monkeypatch.setattr(mod, "webpush", raise_gone)
    await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"})
    n = (await db_session.execute(
        text("SELECT count(*) FROM push_subscriptions WHERE user_id = :uid"),
        {"uid": other_user_with_sub.user_id},
    )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_helper_returns_false_when_all_endpoints_fail_with_500(monkeypatch, seeded_user_with_subs):
    from app.notifications import web_push_plugin as mod
    response = MagicMock(status_code=500)
    def raise_500(**_):
        raise WebPushException("oops", response=response)
    monkeypatch.setattr(mod, "webpush", raise_500)
    assert await send_web_push_to_user(seeded_user_with_subs.user_id, {"title": "t", "body": "b"}) is False
```

**Step 3: Commit**

```bash
git add backend/tests/test_web_push_plugin.py backend/tests/conftest.py
git commit -m "test(notifications): cover WebPushPlugin + send helper (incl. user-scoped GC)"
```

---

### Task 7: Notifications REST API [IMPLEMENTED]

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
from app.notifications import prefs as prefs_module

router = APIRouter(prefix="/notifications", tags=["notifications"])


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


@router.get("/vapid-public-key", response_model=VapidKeyDto)
async def get_vapid_public_key() -> VapidKeyDto:
    if not settings.web_push_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Web Push not configured")
    return VapidKeyDto(public_key=settings.VAPID_PUBLIC_KEY)


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
    # ON CONFLICT (endpoint) — idempotent re-subscribe; re-assigning user_id is
    # intentional (a browser endpoint may move between accounts on one device).
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

### Task 7.5: Remove Telegram API router from routes.py [IMPLEMENTED]

**Depends on:** Task 7

**Files:** Modify `backend/app/api/routes.py`

**Step 1:** Delete the import at `routes.py:12` (`from app.api.telegram import router as telegram_api_router`) and the include at `routes.py:31` (`router.include_router(telegram_api_router)`).

**Step 2: Commit**

```bash
git add backend/app/api/routes.py
git commit -m "refactor(api): drop telegram router include"
```

---

### Task 7.6: Strip telegram fields from /auth/me [IMPLEMENTED]

**Depends on:** Task 3

**Files:** Modify `backend/app/api/auth.py`

**Step 1:** In `auth_me` (`auth.py:133-157`) delete the re-fetch block (lines 144-149: the comment, the `SELECT telegram_chat_id, telegram_linked_at`, and `tg = row.one_or_none()`) and remove the two telegram keys from the returned dict. Final return:

```python
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }
```

(The `last_seen_at` UPDATE above stays. If `text`/`session` become unused after the edit, leave them — `session` is still used for the UPDATE.)

**Step 2: Commit**

```bash
git add backend/app/api/auth.py
git commit -m "refactor(api): drop telegram fields from /auth/me"
```

---

### Task 7.7: Delete Telegram backend + frontend modules and tests [IMPLEMENTED]

**Depends on:** Tasks 4, 7.5, 7.6, 9 (fav_sweep migrated), and frontend Tasks 14 + 19 (importers retargeted)

> **Ordering:** this deletion task runs only after every importer of `app.telegram.*` and `TelegramPanel`/telegram client functions has been retargeted (Tasks 4, 9, 14, 19) and the includes removed (7.5/7.6). Verify with grep before deleting.

**Step 1: Verify no live imports remain** (must return only deleted-file matches):

```bash
grep -rn "app\.telegram" backend/app backend/tests
grep -rn "TelegramPanel\|linkTelegram\|unlinkTelegram\|TelegramLinkResponse\|telegram_chat_id\|telegram_linked_at" frontend/src
```

**Step 2: Delete backend Telegram package + API + tests:**

```bash
git rm -r backend/app/telegram
git rm backend/app/api/telegram.py
git rm backend/tests/test_telegram_api.py backend/tests/test_telegram_bot.py \
       backend/tests/test_telegram_link.py backend/tests/test_telegram_plugin.py \
       backend/tests/test_telegram_prefs.py backend/tests/test_telegram_webhook.py \
       backend/tests/test_telegram_fav_sweep.py
```

**Step 3: Delete frontend TelegramPanel + test:**

```bash
git rm frontend/src/components/TelegramPanel.tsx frontend/src/components/__tests__/TelegramPanel.test.tsx
```

**Step 4: Commit**

```bash
git commit -m "chore: remove Telegram subsystem (PLAN-027)"
```

---

### Task 8: REST API tests [IMPLEMENTED]

**Depends on:** Tasks 7, 7.5

**Files:** Create `backend/tests/test_notifications_api.py`

**Step 1: Tests** — uses the existing `authenticated_client` fixture (impersonates `auth_client@example.com`) + `other_user_with_sub` (Task 6) for ownership isolation. `api_client` (unauthenticated for owned routes; VAPID is public).

```python
"""Tests for /api/notifications/* — uses authenticated_client fixture from conftest."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_vapid_public_key_returns_key(api_client, monkeypatch):
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
        "/api/notifications/subscriptions", json={**body, "device_label": "renamed"},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["device_label"] == "renamed"


@pytest.mark.asyncio
async def test_get_subscriptions_returns_only_owned(authenticated_client, other_user_with_sub):
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
async def test_delete_subscription_404_when_not_owned(authenticated_client, other_user_with_sub):
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
    assert "fav_sold" in body and "fav_price" in body and "fav_deleted" in body


@pytest.mark.asyncio
async def test_put_preferences_updates_web_push_enabled(authenticated_client):
    r = await authenticated_client.put(
        "/api/notifications/preferences", json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["web_push_enabled"] is False


@pytest.mark.asyncio
async def test_put_preferences_partial_does_not_clobber_other_fields(authenticated_client):
    await authenticated_client.put("/api/notifications/preferences", json={"fav_sold": False})
    r = await authenticated_client.put(
        "/api/notifications/preferences", json={"web_push_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["fav_sold"] is False  # unchanged
```

**Step 2: Commit**

```bash
git add backend/tests/test_notifications_api.py
git commit -m "test(api): cover /api/notifications/* endpoints"
```

---

### Task 9: Migrate favorites sweep to Web Push [IMPLEMENTED]

**Depends on:** Tasks 4, 5

**Files:** Create `backend/app/notifications/fav_sweep.py`, create `backend/tests/test_notifications_fav_sweep.py`

**Step 1: Create `backend/app/notifications/fav_sweep.py`** — migrated from `app/telegram/fav_sweep.py`. Changes vs. original: import `prefs`/`send_web_push_to_user` from `app.notifications`; query selects users with ≥1 push subscription instead of `telegram_chat_id`; `_detect_events` returns plain text lines (no HTML); delivery via `send_web_push_to_user`; gate is `settings.web_push_enabled` (not telegram); renamed settings; no link-token cleanup tail.

```python
"""Favorites-status sweep: detect sold/price/deleted changes, deliver via Web Push.

Runs every FAV_SWEEP_INTERVAL_MIN minutes via APScheduler (registered in main.py).
Migrated from app.telegram.fav_sweep in PLAN-027.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications import prefs as prefs_module
from app.notifications.web_push_plugin import send_web_push_to_user

logger = logging.getLogger(__name__)


def _decimal_eq(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is b
    return Decimal(str(a)) == Decimal(str(b))


def _detect_events(row: dict, deleted_cutoff: datetime, user_prefs: prefs_module.NotificationPrefs) -> list[str]:
    """Return plain-text event lines based on diffs + per-user prefs."""
    events: list[str] = []
    lk_sold = row["last_known_is_sold"]
    lk_price = row["last_known_price_numeric"]
    lk_scr = row["last_known_scraped_at"]
    title = row["title"]
    is_sold = row["is_sold"]
    price = row["price_numeric"]
    scraped_at = row["scraped_at"]

    if lk_sold is not None and lk_sold is False and is_sold is True and user_prefs.fav_sold:
        events.append(f"Verkauft: {title}")

    if (
        lk_price is not None
        and price is not None
        and not _decimal_eq(lk_price, price)
        and user_prefs.fav_price
    ):
        events.append(f"Preis geändert: {title} — {float(lk_price):.0f}€ → {float(price):.0f}€")

    listing_gone = scraped_at is not None and scraped_at < deleted_cutoff
    snapshot_alive = lk_scr is not None and lk_scr >= deleted_cutoff
    if listing_gone and snapshot_alive and user_prefs.fav_deleted:
        events.append(f"Gelöscht: {title}")

    return events


async def run_fav_status_sweep() -> int:
    """Scan user_favorites, diff against snapshots, push per-favorite event digests.

    Returns the number of users a push was delivered to.
    Always updates snapshots (even when no push sent / pref disabled).
    """
    if not settings.web_push_enabled:
        return 0

    deleted_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.FAV_DELETED_DAYS)
    sent_count = 0

    try:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT uf.user_id, uf.listing_id,
                           uf.last_known_is_sold, uf.last_known_price_numeric,
                           uf.last_known_scraped_at,
                           l.title, l.url,
                           l.is_sold, l.price_numeric, l.scraped_at
                    FROM user_favorites uf
                    JOIN listings l ON l.id = uf.listing_id
                    WHERE EXISTS (
                        SELECT 1 FROM push_subscriptions ps WHERE ps.user_id = uf.user_id
                    )
                """)
            )
            favorites = [row._asdict() for row in rows.all()]
    except Exception:
        logger.exception("notifications.sweep.fav: load FAILED — aborting sweep")
        return 0

    for fav in favorites:
        user_id = fav["user_id"]
        listing_id = fav["listing_id"]
        try:
            user_prefs = await prefs_module.get_prefs(user_id)
            events = _detect_events(fav, deleted_cutoff, user_prefs)

            if events and user_prefs.web_push_enabled:
                payload = {
                    "title": "Merkliste aktualisiert",
                    "body": "\n".join(events),
                    "url": f"/listings/{listing_id}",
                    "tag": f"fav-{listing_id}",
                }
                if await send_web_push_to_user(user_id, payload):
                    sent_count += 1
                    logger.info(
                        "notifications.sweep.fav: user_id=%d listing_id=%d triggers=%d pushed",
                        user_id, listing_id, len(events),
                    )

            # Always update snapshot (even when no push sent / pref disabled)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("""
                        UPDATE user_favorites
                        SET last_known_is_sold = :sold,
                            last_known_price_numeric = :price,
                            last_known_scraped_at = :scr
                        WHERE user_id = :u AND listing_id = :l
                    """),
                    {
                        "sold": fav["is_sold"], "price": fav["price_numeric"],
                        "scr": fav["scraped_at"], "u": user_id, "l": listing_id,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "notifications.sweep.fav: user_id=%d listing_id=%d FAILED — skipping",
                user_id, listing_id,
            )
            continue

    return sent_count
```

**Step 2: Tests** — `backend/tests/test_notifications_fav_sweep.py` (mirrors the structure of the old `test_telegram_fav_sweep.py`, patching `send_web_push_to_user` instead of `bot.send_message`). One `it` per behavior:

```python
"""Tests for app.notifications.fav_sweep — favorites status-change sweep via Web Push."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.notifications import fav_sweep


async def _seed_user_with_sub(db_session) -> int:
    await db_session.execute(text("""
        INSERT INTO users (google_id, email, name, is_approved)
        VALUES ('fav-sweep-u', 'fav_sweep@example.com', 'Fav Sweep', TRUE)
    """))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'fav-sweep-u'")
    )).scalar_one()
    await db_session.execute(
        text("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (:u, 'https://fcm/fav', 'P', 'A')"""),
        {"u": uid},
    )
    await db_session.commit()
    return uid


async def _seed_favorite(db_session, uid: int, *, is_sold: bool, lk_sold: bool) -> int:
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text("""INSERT INTO listings (external_id, url, title, description, author, scraped_at, images, tags, is_sold)
                VALUES ('fav-ext', 'http://x/1', 'My Fav', 'd', 'a', :now, '[]', '[]', :sold)"""),
        {"now": now, "sold": is_sold},
    )
    lid = (await db_session.execute(
        text("SELECT id FROM listings WHERE external_id = 'fav-ext'")
    )).scalar_one()
    await db_session.execute(
        text("""INSERT INTO user_favorites (user_id, listing_id, last_known_is_sold, last_known_scraped_at)
                VALUES (:u, :l, :lk, :now)"""),
        {"u": uid, "l": lid, "lk": lk_sold, "now": now},
    )
    await db_session.commit()
    return lid


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_web_push_disabled(monkeypatch):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "")
    assert await fav_sweep.run_fav_status_sweep() == 0


@pytest.mark.asyncio
async def test_sweep_pushes_on_sold_transition(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 1
    assert m.await_count == 1
    payload = m.await_args.args[1]
    assert "Verkauft" in payload["body"]


@pytest.mark.asyncio
async def test_sweep_no_push_when_no_event(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    await _seed_favorite(db_session, uid, is_sold=False, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 0
    assert m.await_count == 0


@pytest.mark.asyncio
async def test_sweep_updates_snapshot_even_without_push(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    uid = await _seed_user_with_sub(db_session)
    lid = await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)):
        await fav_sweep.run_fav_status_sweep()
    snap = (await db_session.execute(
        text("SELECT last_known_is_sold FROM user_favorites WHERE user_id=:u AND listing_id=:l"),
        {"u": uid, "l": lid},
    )).scalar_one()
    assert snap is True


@pytest.mark.asyncio
async def test_sweep_skips_user_without_subscription(monkeypatch, db_session):
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PUBLIC_KEY", "p")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(fav_sweep.settings, "VAPID_SUBJECT", "mailto:x@y")
    # user with a favorite but NO push subscription
    await db_session.execute(text("""
        INSERT INTO users (google_id, email, name, is_approved)
        VALUES ('no-sub-u', 'nosub@example.com', 'No Sub', TRUE)
    """))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'no-sub-u'")
    )).scalar_one()
    await _seed_favorite(db_session, uid, is_sold=True, lk_sold=False)
    with patch.object(fav_sweep, "send_web_push_to_user", new=AsyncMock(return_value=True)) as m:
        n = await fav_sweep.run_fav_status_sweep()
    assert n == 0
    assert m.await_count == 0
```

**Step 3: Commit**

```bash
git add backend/app/notifications/fav_sweep.py backend/tests/test_notifications_fav_sweep.py
git commit -m "feat(notifications): migrate favorites sweep to Web Push"
```

---

### Task 9.5: Wire main.py + docker-compose + env example [IMPLEMENTED]

**Depends on:** Tasks 5, 7, 9

**Files:** Modify `backend/app/main.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `env.prod.example`

**Step 1: main.py imports** — remove `from app.telegram.webhook import router as telegram_webhook_router` (line 21) and `from app.telegram.plugin import TelegramPlugin` (line 25). Add near the other notification imports (after line 24):

```python
from app.api.notifications import router as notifications_router
from app.notifications.web_push_plugin import WebPushPlugin
```

**Step 2: Plugin registration** — replace the block at `main.py:49-57`:

```python
    # Register notification plugins — guard against hot-reload duplicates
    if not notification_registry._plugins:
        notification_registry.register(LogPlugin())

    if settings.web_push_enabled and not any(
        isinstance(p, WebPushPlugin) for p in notification_registry._plugins
    ):
        notification_registry.register(WebPushPlugin())
        logger.info("web_push.plugin: registered")
```

**Step 3: Fav-sweep scheduler** — replace the gated block at `main.py:101-109` with an ungated, retargeted job:

```python
    from app.notifications import fav_sweep
    scheduler.add_job(
        fav_sweep.run_fav_status_sweep,
        trigger="interval",
        minutes=settings.FAV_SWEEP_INTERVAL_MIN,
        id="fav_status_sweep",
        replace_existing=True,
    )
```

(`run_fav_status_sweep` self-guards on `settings.web_push_enabled`, so an unconfigured deployment runs the job as a cheap no-op.)

**Step 4: Remove the setWebhook block** (`main.py:196-219`, the whole `if settings.telegram_enabled: ... else: ...`).

**Step 5: Remove the webhook router include** at `main.py:239` (`app.include_router(telegram_webhook_router)`).

**Step 6: Mount notifications router** — after the existing router includes (replace the removed line 239 area):

```python
app.include_router(notifications_router, prefix="/api")
```

**Step 7: docker-compose.yml** — in the backend `environment:` block, remove the three `TELEGRAM_*` lines (42-44) and add:

```yaml
      FAV_SWEEP_INTERVAL_MIN: ${FAV_SWEEP_INTERVAL_MIN:-60}
      FAV_DELETED_DAYS: ${FAV_DELETED_DAYS:-3}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY:-}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY:-}
      VAPID_SUBJECT: ${VAPID_SUBJECT:-mailto:marco.roth1983@googlemail.com}
```

**Step 8: docker-compose.prod.yml** — append to the backend `environment:` block (lines 25-34; no telegram vars exist there today):

```yaml
      # PLAN-027: Web Push
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_SUBJECT: ${VAPID_SUBJECT:-mailto:marco.roth1983@googlemail.com}
```

**Step 9: env.prod.example** — remove the Telegram block (lines 18-24) and append:

```bash
# Web Push (PLAN-027)
# Generate once: npx web-push generate-vapid-keys
# Set VAPID_PUBLIC_KEY also as a GitHub repository VARIABLE (Settings → Secrets and
# variables → Actions → Variables) so it is baked into the frontend image during CI.
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:marco.roth1983@googlemail.com
```

**Step 10: Commit**

```bash
git add backend/app/main.py docker-compose.yml docker-compose.prod.yml env.prod.example
git commit -m "feat(boot): register WebPushPlugin, ungate fav-sweep, remove telegram wiring"
```

---

### Task 10: Frontend dependencies [IMPLEMENTED]

**Files:** Modify `frontend/package.json`, regenerate `frontend/package-lock.json`

**Step 1: Install via npm** (run from `frontend/`):

```bash
npm install -D vite-plugin-pwa@^0.21
npm install workbox-window@^7 workbox-precaching@^7
```

**Step 2: Remove pnpm lockfile if present** (npm is canonical):

```bash
rm -f frontend/pnpm-lock.yaml
```

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git rm --ignore-unmatch frontend/pnpm-lock.yaml
git commit -m "chore(frontend): add vite-plugin-pwa + workbox"
```

---

### Task 11: PWA detection helpers [IMPLEMENTED]

**Depends on:** Task 10

**Files:** Create `frontend/src/lib/pwa-detect.ts`, create `frontend/src/lib/__tests__/pwa-detect.test.ts`, modify `frontend/src/components/InstallPrompt.tsx`

**Step 1:** `frontend/src/lib/pwa-detect.ts`:

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

**Step 2:** In `frontend/src/components/InstallPrompt.tsx`, delete the local `isStandalone` (lines 13-18) and `isIos` (lines 20-22) and add at the top:

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
    vi.stubGlobal('window', { ...window, matchMedia: () => ({ matches: true } as MediaQueryList) });
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

### Task 11.5: Remove legacy PWA artifacts [IMPLEMENTED]

**Depends on:** Task 10

**Files:** Modify `frontend/src/main.tsx`, `frontend/index.html`; delete `frontend/public/sw.js`, `frontend/public/manifest.json`

**Step 1:** Delete the manual SW registration in `main.tsx` (lines 27-31):

```typescript
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
  })
}
```

**Step 2:** Remove `<link rel="manifest" href="/manifest.json">` at `index.html:10`. The apple-touch-icon + iOS PWA meta tags stay. VitePWA injects its own manifest link.

**Step 3:** Delete static files:

```bash
git rm frontend/public/sw.js frontend/public/manifest.json
```

The icons in `frontend/public/icons/` stay (referenced from the VitePWA manifest in Task 12).

**Step 4: Commit**

```bash
git add frontend/src/main.tsx frontend/index.html
git commit -m "chore(pwa): remove legacy sw.js + manifest.json (replaced by vite-plugin-pwa)"
```

---

### Task 12: Vite PWA config [IMPLEMENTED]

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
      // Output file: sw.js. Must match the nginx no-cache rule (frontend/nginx.conf:14
      // `location = /sw.js`). Do not rename without updating that rule.
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
git commit -m "feat(frontend): wire vite-plugin-pwa with migrated manifest"
```

---

### Task 12.5: PWA update reliability — nginx + SW SKIP_WAITING [IMPLEMENTED]

**Depends on:** Task 12, Task 13

**Files:** Modify `frontend/nginx.conf` (Task 13 adds the `message` handler in `sw.ts`)

> Adopts the minimal half of Do-It's PLAN_037: never-cache `index.html` so a redeploy is discovered, and let the new SW take over without sitting in `waiting`. The `message` SKIP_WAITING handler is part of `sw.ts` (Task 13). YAGNI: no resume/30-min update-poll hook.

**Step 1:** In `frontend/nginx.conf`, add a `location = /index.html` block directly before the `location /` SPA fallback (line 40). Mirror the header set from the existing `location = /sw.js` block (nginx `add_header` does not inherit once a `location` declares its own):

```nginx
    # index.html must never be cached — ensures the browser fetches the latest
    # SW registration after a new deployment.
    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    }
```

**Step 2: Commit**

```bash
git add frontend/nginx.conf
git commit -m "fix(pwa): never cache index.html so redeploys are discovered"
```

---

### Task 13: Service worker (push + notificationclick + skip-waiting) [IMPLEMENTED]

**Depends on:** Task 10

**Files:** Create `frontend/src/sw.ts`

**Step 1: Implement** — includes the `assertSafeNotificationUrl` open-redirect guard, exact-pathname client match, and the SKIP_WAITING message handler (mirrors Do-It's `service-worker.ts`):

```typescript
/// <reference lib="webworker" />
import { precacheAndRoute } from 'workbox-precaching';

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Belt-and-suspenders: receive SKIP_WAITING from workbox-window if a future
// registerType change ever leaves a new SW in "waiting".
self.addEventListener('message', (event) => {
  if ((event.data as { type?: string } | null)?.type === 'SKIP_WAITING') {
    event.waitUntil(self.skipWaiting());
  }
});

interface PushPayload {
  title: string;
  body: string;
  url?: string;
  tag?: string;
}

/** Only allow in-app relative paths ("/..."). Blocks open-redirect via push URL. */
function safeUrl(url: string | undefined): string {
  if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//')) return url;
  return '/';
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
    data: { url: safeUrl(data.url) },
  };

  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = safeUrl((event.notification.data as { url?: string } | undefined)?.url);
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const existing = all.find((c) => {
        try {
          return new URL(c.url).pathname === new URL(target, self.location.origin).pathname;
        } catch {
          return false;
        }
      });
      if (existing && 'focus' in existing) return existing.focus();
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })(),
  );
});
```

**Step 2: Commit**

```bash
git add frontend/src/sw.ts
git commit -m "feat(sw): push + notificationclick + skip-waiting handlers"
```

---

### Task 14: Notifications client + types + remove telegram client surfaces [IMPLEMENTED]

**Depends on:** Task 10

**Files:** Create `frontend/src/notifications/api.ts`, modify `frontend/src/types/api.ts`, `frontend/src/api/client.ts`, `frontend/src/hooks/useAuth.ts`, `frontend/src/__tests__/ModalRouting.test.tsx`

**Step 1: `types/api.ts`** — extend `NotificationPrefs` (lines 224-229), delete `TelegramLinkResponse` (lines 231-234), append the new DTOs:

```typescript
export interface NotificationPrefs {
  new_search_results: boolean;
  fav_sold: boolean;
  fav_price: boolean;
  fav_deleted: boolean;
  web_push_enabled: boolean;
}

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

**Step 2: `api/client.ts`** — remove `TelegramLinkResponse` from the type import (lines 1-16), delete `linkTelegram` (167-170) and `unlinkTelegram` (172-175), and retarget the prefs functions (177-189):

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

**Step 3: `hooks/useAuth.ts`** — remove `telegram_chat_id` and `telegram_linked_at` from the `AuthUser` type (lines 8-9).

**Step 4: `__tests__/ModalRouting.test.tsx`** — remove `telegram_chat_id: null, telegram_linked_at: null` from the two mocked `user` objects (lines 38, 204).

**Step 5: `notifications/api.ts`** — subscriptions + vapid client (prefs stay in `client.ts`):

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

**Step 6: Tests** — `frontend/src/notifications/__tests__/api.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { notificationsApi } from '../api';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ok = (json: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(json) });

describe('notificationsApi', () => {
  it('getVapidPublicKey GETs /api/notifications/vapid-public-key', async () => {
    fetchMock.mockResolvedValue(ok({ public_key: 'pub' }));
    await notificationsApi.getVapidPublicKey();
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/vapid-public-key');
  });

  it('createSubscription POSTs JSON body', async () => {
    fetchMock.mockResolvedValue(ok({ id: 1, endpoint: 'x' }, 201));
    await notificationsApi.createSubscription({ endpoint: 'x', keys: { p256dh: 'p', auth: 'a' } });
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
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: 'gone' }) });
    await expect(notificationsApi.deleteSubscription(99)).rejects.toMatchObject({ status: 404 });
  });
});
```

**Step 7: Commit**

```bash
git add frontend/src/notifications/api.ts frontend/src/notifications/__tests__/api.test.ts \
        frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/hooks/useAuth.ts \
        frontend/src/__tests__/ModalRouting.test.tsx
git commit -m "feat(notifications): subscriptions client + DTOs; remove telegram client surfaces"
```

---

### Task 15: Device-label helper [IMPLEMENTED]

**Files:** Create `frontend/src/notifications/device-label.ts` + co-located test

**Step 1:** `frontend/src/notifications/device-label.ts`:

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

### Task 16: useWebPushSubscription hook [IMPLEMENTED]

**Depends on:** Tasks 11, 14, 15

**Files:** Create `frontend/src/notifications/useWebPushSubscription.ts` + test

**Step 1:** `frontend/src/notifications/useWebPushSubscription.ts`:

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

**Step 2: Tests** — `frontend/src/notifications/__tests__/useWebPushSubscription.test.tsx`. All 7 `it` blocks are fully implemented (no stubs). Mock setup mirrors Do-It's `apps/web/src/notifications/useWebPushSubscription.test.tsx` (the `stubPushEnvironment` helper that installs fake `navigator.serviceWorker`/`window.Notification`/`window.PushManager` via `Object.defineProperty`, and the `delete window.X` trick for the unsupported case — setting a global to `undefined` does NOT make `'X' in window` false). **Deviations from the Do-It reference** (rcn hook differs):
> - rcn reads the VAPID key at `subscribe()` time via `notificationsApi.getVapidPublicKey()` returning `{ public_key }` — NOT from `import.meta.env`. So mock `notificationsApi.getVapidPublicKey`, do NOT use `vi.stubEnv`.
> - rcn `createSubscription` payload is snake_case `{ endpoint, keys, user_agent, device_label }` (Do-It uses camelCase `userAgent`/`deviceLabel`).
> - rcn `getDeviceLabel()` is synchronous (returns a string), so its mock returns a plain string (not a resolved promise).
> - rcn `pushSupported()` checks `'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window`. The unsupported test must make at least one of those `in`-checks false.
> - rcn has no on-mount label re-POST effect, so there is no "re-POSTs on mount" test.

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Hoisted mocks — must precede any import that touches these modules.
vi.mock('../api', () => ({
  notificationsApi: {
    getVapidPublicKey: vi.fn().mockResolvedValue({ public_key: 'dGVzdA' }), // URL-safe b64 "test"
    createSubscription: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock('../device-label', () => ({
  getDeviceLabel: vi.fn().mockReturnValue('Chrome auf Windows'),
}));

import { useWebPushSubscription } from '../useWebPushSubscription';
import { notificationsApi } from '../api';

type Permission = 'default' | 'denied' | 'granted';

interface StubHandles {
  mockSub: {
    endpoint: string;
    unsubscribe: ReturnType<typeof vi.fn>;
    toJSON: ReturnType<typeof vi.fn>;
  };
  mockPushManager: {
    getSubscription: ReturnType<typeof vi.fn>;
    subscribe: ReturnType<typeof vi.fn>;
  };
}

// Installs fake push APIs on window/navigator. pushSupported() is evaluated at
// render time, so stubs must be in place before renderHook() is called.
function stubPushEnvironment(permission: Permission, hasSub: boolean): StubHandles {
  const mockSub = {
    endpoint: 'https://push.example.com/stub-endpoint',
    unsubscribe: vi.fn().mockResolvedValue(true),
    toJSON: vi.fn().mockReturnValue({
      endpoint: 'https://push.example.com/stub-endpoint',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    }),
  };
  const mockPushManager = {
    getSubscription: vi.fn().mockResolvedValue(hasSub ? mockSub : null),
    subscribe: vi.fn().mockResolvedValue(mockSub),
  };
  const mockRegistration = { pushManager: mockPushManager };

  Object.defineProperty(navigator, 'serviceWorker', {
    value: { ready: Promise.resolve(mockRegistration) },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(window, 'Notification', {
    value: { permission, requestPermission: vi.fn().mockResolvedValue(permission) },
    writable: true,
    configurable: true,
  });
  // jsdom lacks PushManager — add a sentinel so the `'PushManager' in window` check passes.
  Object.defineProperty(window, 'PushManager', {
    value: class {},
    writable: true,
    configurable: true,
  });
  return { mockSub, mockPushManager };
}

beforeEach(() => {
  vi.mocked(notificationsApi.getVapidPublicKey).mockResolvedValue({ public_key: 'dGVzdA' });
  vi.mocked(notificationsApi.createSubscription).mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.clearAllMocks();
});

describe('useWebPushSubscription', () => {
  it('unsupported when push APIs are missing', async () => {
    Object.defineProperty(navigator, 'serviceWorker', {
      value: undefined,
      writable: true,
      configurable: true,
    });
    // Setting to undefined is not enough — `'X' in window` stays true. Delete them.
    delete (window as unknown as Record<string, unknown>)['Notification'];
    delete (window as unknown as Record<string, unknown>)['PushManager'];

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('unsupported'));
    expect(result.current.supported).toBe(false);
  });

  it('default when permission is default', async () => {
    stubPushEnvironment('default', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));
  });

  it('denied when permission is denied', async () => {
    stubPushEnvironment('denied', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('denied'));
  });

  it('granted-no-subscription when granted but getSubscription() → null', async () => {
    stubPushEnvironment('granted', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('granted-no-subscription'));
  });

  it('granted-subscribed when getSubscription() → { endpoint }', async () => {
    const { mockSub } = stubPushEnvironment('granted', true);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('granted-subscribed'));
    expect((result.current.state as { status: string; endpoint: string }).endpoint)
      .toBe(mockSub.endpoint);
  });

  it('subscribe requests permission, calls pushManager.subscribe, posts snake_case payload to API', async () => {
    const { mockPushManager } = stubPushEnvironment('default', false);
    vi.mocked(window.Notification.requestPermission).mockResolvedValue('granted');

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));

    await act(async () => {
      await result.current.subscribe();
    });

    expect(window.Notification.requestPermission).toHaveBeenCalledOnce();
    expect(mockPushManager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: expect.anything(),
    });
    expect(notificationsApi.createSubscription).toHaveBeenCalledWith({
      endpoint: 'https://push.example.com/stub-endpoint',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
      user_agent: navigator.userAgent,
      device_label: 'Chrome auf Windows',
    });
  });

  it('subscribe throws when public_key is empty', async () => {
    stubPushEnvironment('default', false);
    vi.mocked(notificationsApi.getVapidPublicKey).mockResolvedValue({ public_key: '' });

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));

    await expect(
      act(async () => {
        await result.current.subscribe();
      }),
    ).rejects.toThrow(/VAPID-Schlüssel nicht verfügbar/);
    expect(notificationsApi.createSubscription).not.toHaveBeenCalled();
  });
});
```

**Step 3: Commit**

```bash
git add frontend/src/notifications/useWebPushSubscription.ts frontend/src/notifications/__tests__/useWebPushSubscription.test.tsx
git commit -m "feat(notifications): useWebPushSubscription hook"
```

---

### Task 17: FirstStartPushPrompt banner [IMPLEMENTED]

**Depends on:** Tasks 11, 16

**Files:** Create `frontend/src/notifications/FirstStartPushPrompt.tsx` + test

**Reuse check:** Reuses visual shell from `InstallPrompt.tsx` (glassmorphism). Helpers `isIos`, `isStandalone` from `lib/pwa-detect`.

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
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Aktivierung fehlgeschlagen'))
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
            width: 36, height: 36,
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
        <button type="button" onClick={dismiss} disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{ color: 'rgba(248, 250, 252, 0.55)' }}>
          Später
        </button>
        <button type="button" onClick={enable} disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{
            background: 'rgba(99, 102, 241, 0.2)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            color: '#A78BFA',
          }}>
          {busy ? 'Wird aktiviert …' : 'Aktivieren'}
        </button>
      </div>
    </div>
  );
}
```

**Step 2: Tests** — `frontend/src/notifications/__tests__/FirstStartPushPrompt.test.tsx`. Mock `useWebPushSubscription` and `pwa-detect`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../useWebPushSubscription', () => ({ useWebPushSubscription: vi.fn() }));
vi.mock('../../lib/pwa-detect', () => ({ isIos: vi.fn(() => false), isStandalone: vi.fn(() => true) }));

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

### Task 18a: NotificationsPanel — state display [IMPLEMENTED]

**Depends on:** Tasks 11, 16

**Files:** Create `frontend/src/components/NotificationsPanel.tsx`

**Reuse check:** Reuses inline `cardStyle` shape from `ProfilePage.tsx` (locally re-declared). Reuses `useWebPushSubscription`.

**Step 1: Component scaffold — supported/default/denied/granted-no-subscription/granted-subscribed branches**

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
          <button type="button" onClick={handleSubscribe} disabled={busy}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
            style={{ background: 'rgba(99, 102, 241, 0.2)', border: '1px solid rgba(99, 102, 241, 0.4)', color: '#A78BFA' }}>
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
        <button type="button" onClick={handleSubscribe} disabled={busy}
          className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
          style={{ background: 'rgba(99, 102, 241, 0.2)', border: '1px solid rgba(99, 102, 241, 0.4)', color: '#A78BFA' }}>
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

**Step 2: Tests** — `frontend/src/components/__tests__/NotificationsPanel.test.tsx`. Mock `useWebPushSubscription`. One `it` per branch:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../../notifications/useWebPushSubscription', () => ({ useWebPushSubscription: vi.fn() }));
import { NotificationsPanel } from '../NotificationsPanel';
import { useWebPushSubscription } from '../../notifications/useWebPushSubscription';

const mockHook = useWebPushSubscription as unknown as ReturnType<typeof vi.fn>;
beforeEach(() => mockHook.mockReset());

describe('NotificationsPanel — state display', () => {
  it('renders unsupported message when supported=false', () => {
    mockHook.mockReturnValue({ state: { status: 'unsupported' }, supported: false, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/unterstützt keine Web-Push/)).toBeInTheDocument();
  });

  it('renders default state with Aktivieren button', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText('Aktivieren')).toBeInTheDocument();
  });

  it('renders denied state with browser hint', () => {
    mockHook.mockReturnValue({ state: { status: 'denied' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/im Browser blockiert/)).toBeInTheDocument();
  });

  it('renders granted-no-subscription with on-device button', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-no-subscription' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText('Auf diesem Gerät aktivieren')).toBeInTheDocument();
  });

  it('renders granted-subscribed confirmation', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/aktiv/)).toBeInTheDocument();
  });

  it('renders error when subscribe rejects', async () => {
    const subscribe = vi.fn().mockRejectedValue(new Error('boom'));
    mockHook.mockReturnValue({ state: { status: 'default' }, supported: true, subscribe });
    render(<NotificationsPanel />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/boom/));
  });
});
```

**Step 3: Commit**

```bash
git add frontend/src/components/NotificationsPanel.tsx frontend/src/components/__tests__/NotificationsPanel.test.tsx
git commit -m "feat(profile): NotificationsPanel — state display"
```

---

### Task 18b: NotificationsPanel — device list + prefs toggle [IMPLEMENTED]

**Depends on:** Task 18a, Task 14

**Files:** Modify `frontend/src/components/NotificationsPanel.tsx`, extend its test

**Reuse check:** Mirrors the optimistic-toggle-with-revert pattern from the (deleted) `TelegramPanel.tsx:171-188` and copies the `role="switch"` toggle markup from `TelegramPanel.tsx:306-338` (source file removed in Task 7.7 — markup written in full here).

**Step 1: Imports** — Task 18a created the file with `import { useState } from 'react';` as the first line. **Replace that existing react import line** with the merged version below (do NOT add a second `from 'react'` line — a duplicate import is a TypeScript compile error), then add the three new module imports after it:

Replace:
```typescript
import { useState } from 'react';
```
With:
```typescript
import { useState, useCallback, useEffect } from 'react';
import { notificationsApi } from '../notifications/api';
import { getNotificationPrefs, updateNotificationPrefs } from '../api/client';
import type { NotificationPrefs, PushSubscriptionDto } from '../types/api';
```

**Step 2: State + load + handlers** inside the component:

```typescript
  const [subs, setSubs] = useState<PushSubscriptionDto[]>([]);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);

  const reloadSubs = useCallback(async () => {
    try { setSubs(await notificationsApi.listSubscriptions()); } catch { /* non-fatal */ }
  }, []);

  const reloadPrefs = useCallback(async () => {
    try { setPrefs(await getNotificationPrefs()); } catch { /* non-fatal */ }
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
    const previous = prefs?.web_push_enabled;
    setPrefs((p) => (p ? { ...p, web_push_enabled: value } : p));
    void updateNotificationPrefs({ web_push_enabled: value })
      .then(setPrefs)
      .catch(() => {
        if (previous !== undefined) setPrefs((p) => (p ? { ...p, web_push_enabled: previous } : p));
      });
  };
```

**Step 3: Markup** — append before `</section>`:

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
                <button type="button" onClick={() => handleDelete(s.id)}
                  aria-label={`Gerät ${s.device_label ?? s.id} entfernen`}
                  className="text-xs" style={{ color: 'rgba(248, 250, 252, 0.45)' }}>
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
          <button type="button" role="switch" aria-checked={prefs.web_push_enabled} aria-label="Push aktiv"
            onClick={() => handleTogglePush(!prefs.web_push_enabled)}
            className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200"
            style={{
              background: prefs.web_push_enabled
                ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                : 'rgba(255,255,255,0.1)',
              border: prefs.web_push_enabled
                ? '1px solid rgba(139,92,246,0.5)'
                : '1px solid rgba(255,255,255,0.15)',
            }}>
            <span className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
              style={{
                background: '#fff',
                transform: prefs.web_push_enabled ? 'translateX(18px)' : 'translateX(2px)',
                boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
              }}
              aria-hidden="true" />
          </button>
        </div>
      )}
```

**Step 4: Append tests** — at the **top of the file** (with the other module-level `vi.mock` calls from Task 18a, before any `import` of code under test) add mocks for the two new modules, then append the `describe` block below to the end of the file. Same mock pattern as Task 18a (and consistent with Task 16): explicit Vitest globals, `vi.fn()`-backed module mocks, `waitFor` for the async `useEffect` loads.

Add these two `vi.mock` calls next to the existing `vi.mock('../../notifications/useWebPushSubscription', …)` from Task 18a:

```typescript
vi.mock('../../notifications/api', () => ({
  notificationsApi: { listSubscriptions: vi.fn(), deleteSubscription: vi.fn() },
}));
vi.mock('../../api/client', () => ({
  getNotificationPrefs: vi.fn(),
  updateNotificationPrefs: vi.fn(),
}));
```

And import the mocked members alongside the Task 18a imports:

```typescript
import { notificationsApi } from '../../notifications/api';
import { getNotificationPrefs, updateNotificationPrefs } from '../../api/client';
```

Append the following `describe` block to the end of the file:

```typescript
describe('NotificationsPanel — device list + prefs toggle', () => {
  const mockList = notificationsApi.listSubscriptions as unknown as ReturnType<typeof vi.fn>;
  const mockDelete = notificationsApi.deleteSubscription as unknown as ReturnType<typeof vi.fn>;
  const mockGetPrefs = getNotificationPrefs as unknown as ReturnType<typeof vi.fn>;
  const mockUpdatePrefs = updateNotificationPrefs as unknown as ReturnType<typeof vi.fn>;

  const prefs = (web_push_enabled: boolean): NotificationPrefs => ({
    new_search_results: true,
    fav_sold: true,
    fav_price: true,
    fav_deleted: true,
    web_push_enabled,
  });

  beforeEach(() => {
    mockHook.mockReset();
    mockList.mockReset();
    mockDelete.mockReset();
    mockGetPrefs.mockReset();
    mockUpdatePrefs.mockReset();
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, supported: true, subscribe: vi.fn() });
    mockGetPrefs.mockResolvedValue(prefs(true));
  });

  it('shows device list when granted-subscribed and listSubscriptions returned rows', async () => {
    mockList.mockResolvedValue([
      { id: 1, endpoint: 'e1', device_label: 'Chrome auf Windows', user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
      { id: 2, endpoint: 'e2', device_label: null, user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
    ]);
    render(<NotificationsPanel />);
    await waitFor(() => expect(screen.getByText('Chrome auf Windows')).toBeInTheDocument());
    expect(screen.getByText('Unbekanntes Gerät')).toBeInTheDocument();
  });

  it('clicking Entfernen calls deleteSubscription and reloads', async () => {
    mockList
      .mockResolvedValueOnce([
        { id: 7, endpoint: 'e7', device_label: 'iPhone', user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
      ])
      .mockResolvedValueOnce([]);
    mockDelete.mockResolvedValue(undefined);
    render(<NotificationsPanel />);

    const removeBtn = await screen.findByRole('button', { name: /Gerät iPhone entfernen/ });
    fireEvent.click(removeBtn);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(7));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('toggling pref calls updateNotificationPrefs with web_push_enabled', async () => {
    mockList.mockResolvedValue([]);
    mockUpdatePrefs.mockResolvedValue(prefs(false));
    render(<NotificationsPanel />);

    const toggle = await screen.findByRole('switch', { name: 'Push aktiv' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(toggle);
    await waitFor(() => expect(mockUpdatePrefs).toHaveBeenCalledWith({ web_push_enabled: false }));
  });
});
```

**Step 5: Commit**

```bash
git add frontend/src/components/NotificationsPanel.tsx frontend/src/components/__tests__/NotificationsPanel.test.tsx
git commit -m "feat(profile): NotificationsPanel — devices + prefs toggle"
```

---

### Task 19: Mount FirstStartPushPrompt + replace TelegramPanel [IMPLEMENTED]

**Depends on:** Tasks 17, 18b

**Files:** Modify `frontend/src/App.tsx`, `frontend/src/pages/ProfilePage.tsx`

**Step 1: App.tsx** — after `<InstallPrompt />` (line 223) add `<FirstStartPushPrompt />`; add the import near the top:

```tsx
import { FirstStartPushPrompt } from './notifications/FirstStartPushPrompt';
```

```tsx
      <InstallPrompt />
      <FirstStartPushPrompt />
```

**Step 2: ProfilePage.tsx** — replace the `TelegramPanel` import (line 7) with:

```tsx
import { NotificationsPanel } from '../components/NotificationsPanel';
```

Replace Column 2 (lines 237-240):

```tsx
        <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
          <NotificationsPanel />
          {user.role === 'admin' && <LLMAdminPanel />}
        </div>
```

`NotificationsPanel` takes no props. The `onUserReload` prop on `ProfilePage` becomes unused — leave the `Props` interface as-is (it is still passed by the parent route); just stop forwarding it. (Verify no other use of `onUserReload` inside ProfilePage after this edit — there is none today.)

**Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/ProfilePage.tsx
git commit -m "feat(ui): mount FirstStartPushPrompt; replace TelegramPanel with NotificationsPanel"
```

---

### Task 20: Production build path — Dockerfile + GHA [IMPLEMENTED]

**Depends on:** Task 12

**Files:** Modify `frontend/Dockerfile`, `.github/workflows/deploy.yml`

**Step 1: `frontend/Dockerfile`** — insert before `RUN npm run build`:

```dockerfile
ARG VITE_VAPID_PUBLIC_KEY=""
ENV VITE_VAPID_PUBLIC_KEY=$VITE_VAPID_PUBLIC_KEY
```

**Step 2: `.github/workflows/deploy.yml`** — add `build-args` to the nginx/frontend build step (lines 39-47):

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

(VAPID public key is public → `vars.VAPID_PUBLIC_KEY` repo variable is correct.)

**Step 3: Commit**

```bash
git add frontend/Dockerfile .github/workflows/deploy.yml
git commit -m "chore(ci): wire VITE_VAPID_PUBLIC_KEY into frontend build"
```

---

### Task 21: Generate VAPID keypair [ ]

**Step 1: Run once, locally, outside the repo:**

```bash
npx web-push generate-vapid-keys
```

Output: two URL-safe base64 strings — the exact format the frontend hook (`urlBase64ToUint8Array`) and `pywebpush` (`vapid_private_key=…`) expect.

**Step 2: Populate `.env`** (NOT committed):

```bash
VAPID_PUBLIC_KEY=<public key>
VAPID_PRIVATE_KEY=<private key>
VAPID_SUBJECT=mailto:marco.roth1983@googlemail.com
```

**Step 3:** Set the GitHub repository **variable** `VAPID_PUBLIC_KEY` (public key only). The private key goes onto the VPS `.env` directly — never into CI.

**No commit** — secrets only.

---

### Task 22: Verification gate (no commit) [ ]

Placeholder — see `## Verification`.

---

### Task 23: Update definition.md [ ]

**Depends on:** All implementation tasks

**Files:** Modify `docs/definition.md`

Replace §F5 with:

```markdown
### F5: Web Push Alerts (active)

- Per-user opt-in via `/profile` notifications panel.
- Trigger: new listing matches for any **active** SavedSearch (existing pipeline via `notification_registry.dispatch(MatchResult)`).
- Also delivers favorites status changes (sold / price / deleted) via the favorites sweep.
- Multi-device: each browser install registers its own subscription; devices removable individually.
- Sole notification channel — Telegram was removed in PLAN-027.
- iOS: requires PWA install (Add to Home Screen) — see `limitations.md`.
```

```bash
git add docs/definition.md
git commit -m "docs(definition): activate F5 Web Push, note Telegram removal"
```

---

### Task 24: Update architektur.md [ ]

**Depends on:** All implementation tasks

**Files:** Modify `docs/architektur.md`

Remove any Telegram-subsystem references; append:

```markdown
## Notification Channel (Web Push)

`app/notifications/registry.py` holds a singleton `notification_registry`. Plugins implement `NotificationPlugin` (`is_configured()` + `send(MatchResult)`). `WebPushPlugin` is the sole delivery plugin (plus `LogPlugin`); it is registered in `app/main.py:lifespan()` when VAPID is configured. A shared helper `send_web_push_to_user(user_id, payload)` (in `web_push_plugin.py`) owns the per-subscription send loop, 404/410 stale-subscription garbage collection (scoped by `user_id`), and the per-delivered `last_used_at` bump. Both the plugin and the favorites status sweep (`app/notifications/fav_sweep.py`, scheduled every `FAV_SWEEP_INTERVAL_MIN` minutes) use this helper.

Subscriptions live in `push_subscriptions` (multi-device, `ON DELETE CASCADE` on the user). Per-user opt-in is `user_notification_prefs.web_push_enabled`, served via `GET/PUT /api/notifications/preferences` (the single source of truth). The frontend uses `vite-plugin-pwa` in `injectManifest` mode with a custom `src/sw.ts` (built to `dist/sw.js`, served `Cache-Control: no-cache` by `nginx.conf`) handling `push` + `notificationclick` (with an open-redirect-safe URL guard) and a `SKIP_WAITING` message. `index.html` is also served no-cache so redeploys are discovered.

Telegram was fully removed in PLAN-027 (modules, routes, settings, the `telegram_link_tokens` table, and the `users.telegram_chat_id`/`telegram_linked_at` columns).
```

```bash
git add docs/architektur.md
git commit -m "docs(arch): document Web Push channel; remove Telegram references"
```

---

### Task 25: Update limitations.md [ ]

**Files:** Modify `docs/limitations.md`

Append:

```markdown
---

## iOS Web Push requires PWA install

**What:** On iOS Safari, Web Push only works after the user adds the site to their Home Screen so it runs as a standalone PWA. In a regular Safari tab, `Notification.requestPermission()` is unavailable.

**Why:** Apple's policy since iOS 16.4 (March 2023). Cannot be worked around.

**Mitigation:** The frontend detects iOS-without-standalone and suppresses the push prompt. The InstallPrompt banner is shown first; once the user installs the PWA and reopens it, the push prompt becomes available.
```

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

Expected: existing suite passes; new `test_notifications_prefs.py`, `test_web_push_plugin.py`, `test_notifications_fav_sweep.py`, `test_notifications_api.py` pass; no `test_telegram_*.py` files remain; `grep -rn "app\.telegram" backend` returns nothing; nothing else regresses.

**Step 2: Frontend tests**

```bash
cd frontend
npm run test -- --run
```

Expected: existing suite passes; new tests for `pwa-detect`, `device-label`, `useWebPushSubscription`, `FirstStartPushPrompt`, `NotificationsPanel`, `notifications/api` pass; no `TelegramPanel.test.tsx`; `grep -rn "TelegramPanel\|linkTelegram\|telegram_chat_id" frontend/src` returns nothing.

**Step 3: Frontend build**

```bash
cd frontend
VITE_VAPID_PUBLIC_KEY=BDevPub npm run build
```

Expected: `tsc -b` passes (no telegram type leftovers), `dist/sw.js` + generated manifest produced, no error.

**Step 4: Backend startup smoke**

```bash
docker compose up --build -d
docker compose logs backend --tail=80
```

With VAPID populated: `Database initialised`, `web_push.plugin: registered`, the `fav_status_sweep` job scheduled, no `telegram.*` lines, no setWebhook traffic, no tracebacks. With VAPID empty: no `web_push.plugin: registered`, the sweep job still scheduled (no-op), no crash.

**Step 5: API smoke**

```bash
curl -s http://localhost:8002/api/notifications/vapid-public-key
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8002/api/telegram/prefs   # expect 404 (route gone)
```

Expected: `{"public_key": "..."}` (200) when VAPID set / `503` when unset; the telegram route returns 404.

**Step 6: Browser smoke (manual)**

1. `npm run dev` with VAPID populated in backend `.env`.
2. Login → mobile viewport → see FirstStartPushPrompt banner.
3. Click Aktivieren → browser permission prompt → accept.
4. `/profile` shows the device under "Registrierte Geräte" + Web-Push toggle on.
5. Trigger a SavedSearch match → push notification appears; clicking it opens `/?saved_search=…`.
6. Add a favorite, simulate a sold/price change, wait for / trigger the sweep → favorites push appears.
7. Toggle Web-Push off → next match/sweep produces no notification.
8. Click "Entfernen" → that device stops receiving.
9. iPhone Safari without Add-to-Home-Screen: banner hidden; after install + relaunch: banner appears. (HTTPS or `localhost` required.)

---

_Plan review closed 2026-05-30 (cycle 3): 4 blocking addressed across cycles, 5 non-blocking → backlog/dismissed._

## Notes for the Coder

- **DO NOT** introduce Alembic. Schema changes go into `app/db.py:init_db()` AND `tests/conftest.py` (Task 3).
- **DO NOT** modify `app/notifications/base.py` or `app/notifications/registry.py`. Add only.
- **`send_web_push_to_user` is the single delivery primitive** — the plugin and the fav sweep both call it. Do not duplicate the send/GC loop.
- **Telegram is gone** — no compatibility shims, no re-export of the old `app.telegram.prefs` path. Update importers, do not alias.
- **Vitest globals**: `vite.config.ts` keeps `globals: true`; new tests still import `describe, it, expect, vi` explicitly per CLAUDE.md.
- **Frontend build args**: `VITE_VAPID_PUBLIC_KEY` is optional in dev — the hook fetches the key at runtime via `/api/notifications/vapid-public-key`. The build-arg only spares prod a request on cold load.
- **Frequent commits** between sub-steps. Commit message prefixes: `feat(...)`, `fix(...)`, `chore(...)`, `test(...)`, `docs(...)`, `refactor(...)`.
