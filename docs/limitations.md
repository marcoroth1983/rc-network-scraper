# Limitations

Conscious deviations from the target vision, with justifications.

---

## PLZ: First GeoNames entry used for duplicate PLZ codes

**What:** The GeoNames `DE.txt` dataset contains multiple entries per PLZ (one PLZ can cover several districts/places). The seed script uses `ON CONFLICT (plz) DO NOTHING`, so only the first imported entry is stored.

**Why:** Acceptable approximation for Haversine distance calculation in a hobby project. Distance precision does not require the "best" coordinate per PLZ.

---

## POST /api/scrape is synchronous (blocking)

**What:** The `POST /api/scrape` endpoint blocks the HTTP connection until the full scrape completes. For `max_pages=2` with 1s rate limiting and ~20 listings per page, this is 40+ seconds.

**Why:** Async background execution (FastAPI `BackgroundTasks`, job queue) is deferred to a later plan. For single-user local use this is acceptable.

---

## Docker ports shifted due to host conflicts

**What:** The Docker Compose port mappings use non-standard ports:
- PostgreSQL: `5433:5432` (instead of `5432:5432`)
- Backend: `8002:8000` (instead of `8000:8000`)

**Why:** Ports 5432 and 8000 are occupied by another project (`tradecore`) on the development host. Container-internal communication is unaffected (uses Docker network hostnames).

**Note:** Adjust `docker-compose.yml` if deploying to a clean host or VPS where standard ports are available.

---

## Frontend uses React 19 / Vite 8 instead of plan-specified React 18 / Vite 5

**What:** `npm create vite@latest` installed the latest available versions: React 19.2, React Router 7.5, Vite 8.0, TypeScript 6.0. The plan specified React 18, Router 6, Vite 5.

**Why:** The `create vite` scaffolding tool always installs the latest stable versions. Downgrading would require manual version pinning. React 19 and Router 7 are fully backward-compatible with the `BrowserRouter`/`Routes`/`Route` API used in this project — no behavioral differences for our use case.

---

## Test database must be created manually before first test run

**What:** The integration tests connect to `rcscout_test` (separate from the dev DB `rcscout`). This database is not created automatically.

**Why:** Creating databases requires superuser privileges; the app user `rcscout` has only the privileges needed for `rcscout`. Manual one-time setup:

```bash
docker compose exec db psql -U rcscout -c "CREATE DATABASE rcscout_test;"
```

---

## eBay source: private seller filter not available

The eBay Browse API does not expose seller account type (Privatverkäufer vs.
Gewerblich). eBay listings are filtered to `conditionIds:3000` (Used) as a
best-effort proxy for private/used listings. After the first live run, inspect
the `seller` object in actual API responses — if `sellerAccountType` is
available, add a post-filter in `ebay_orchestrator._normalize_item()`.

---

## eBay source: LLM analysis quality

eBay `shortDescription` fields are typically short headlines (<200 chars),
unlike rc-network multi-paragraph posts. `model_type`/`model_subtype`
extraction quality may be lower for eBay listings. Mitigation: fetch the full
item via `get_item()` before analysis (future improvement).

---

## iOS Web Push requires PWA install

**What:** On iOS Safari, Web Push only works after the user adds the site to their Home Screen so it runs as a standalone PWA. In a regular Safari tab, `Notification.requestPermission()` is unavailable.

**Why:** Apple's policy since iOS 16.4 (March 2023). Cannot be worked around.

**Mitigation:** The frontend detects iOS-without-standalone and suppresses the push prompt. The InstallPrompt banner is shown first; once the user installs the PWA and reopens it, the push prompt becomes available.

---

## Favorites sweep always advances snapshots; opt-out events are not backfilled

**What:** The favorites status sweep (`app/notifications/fav_sweep.py`) always advances each favorite's `last_known_*` snapshot after a run, even for users whose `web_push_enabled` is currently `false`. Status changes (sold / price / deleted) that occur while a user has Web Push disabled are therefore detected against the (now-advanced) snapshot and are **not** delivered later when push is re-enabled — they are intentionally dropped, not queued.

**Why:** Deliberate decision, identical to the previous Telegram behavior. Keeping per-user pending event buffers would add state and complexity that a single-user hobby project does not need; the snapshot is the source of truth for "last seen state", independent of delivery preference.

---

## Standalone Admin Console built but frozen — to be replaced by the central d2x-control-plane cockpit

**What:** The standalone Admin Console (`admin/`, subdomain `admin.rcn-scout.d2x-labs.de`, built in PLAN-034) is fully implemented in the repo but is **intentionally NOT deployed to production, and will not be.** Decision 2026-07-17: the admin + analytics function is being centralized into a separate project, **`d2x-control-plane`** — a general admin/analytics cockpit for all d2x apps (Umami analytics already runs there). rc-scanner's admin capability is to become a module of that central cockpit instead of a per-app SPA.

**Why:** Avoids one-admin-console-per-app. Analytics (Umami) is already centralized; the admin side follows. Deploying the standalone console now would cost a Traefik/Let's-Encrypt cert setup plus a second cross-subdomain-cookie login-reset for all users — for a UI that is about to be superseded.

**Status & consequences:**
- The `admin/` Vite/React SPA is **frozen** — no further feature work. A future plan removes it once the control-plane cockpit covers its features.
- The backend `/api/admin/*` endpoints (`backend/app/api/admin.py`) stay, but their future auth path will differ. The current model — a shared session cookie on `COOKIE_DOMAIN=.rcn-scout.d2x-labs.de` — is an **app-local SSO that does NOT generalize across different app domains**. A central cockpit spanning multiple apps needs a real IdP (Keycloak/Authentik/Auth0) or a per-app service-token/read-API. That auth redesign is a `d2x-control-plane` concern and must be brainstormed there, not here.
- Production therefore deploys only the public frontend + backend. The `admin` service in `docker-compose.prod.yml` remains **defined-but-undeployed** (see `backlog.md` DEPLOY-01/-02).
