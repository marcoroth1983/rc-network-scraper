# RC-Markt Scout — Architecture

> **Scope:** Personal hobby project, invite-only. Multiple authenticated users via
> Google SSO with an admin approval whitelist (no public signup). VPS deployment is
> private (firewall/VPN restricted to the owner). Roles: `member` and `admin`.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI |
| Scraping | httpx + BeautifulSoup4 |
| Database | PostgreSQL 16 (dev and prod, via Docker) |
| ORM | SQLAlchemy (async) |
| Geodata | `plz_geodata` DB table (seeded once from CSV) |
| Frontend (PWA) | React 18+ with TypeScript, Vite, Tailwind CSS |
| Admin Console | React 19, Vite 8, TypeScript, Tailwind CSS 3, shadcn/ui, Recharts, lucide-react |
| Deployment | VPS, private access only |

## Project Structure

```
rc-markt-scout/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings
│   │   ├── models.py            # DB models
│   │   ├── scraper/
│   │   │   ├── crawler.py       # Page traversal, URL collection
│   │   │   └── parser.py        # Detail page extraction
│   │   ├── geo/
│   │   │   └── distance.py      # Haversine calculation
│   │   ├── seed_plz.py            # One-time PLZ CSV → DB import
│   │   ├── api/
│   │   │   ├── routes.py        # REST endpoints
│   │   │   └── schemas.py       # Pydantic models
│   │   └── db.py                # Database connection
│   ├── data/
│   │   └── plz_de.csv           # German PLZ geodata
│   ├── requirements.txt
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ListingCard.tsx
│   │   │   ├── ListingDetail.tsx
│   │   │   ├── SearchBar.tsx
│   │   │   └── FilterPanel.tsx
│   │   ├── hooks/
│   │   │   └── useListings.ts
│   │   ├── types/
│   │   │   └── listing.ts
│   │   └── api/
│   │       └── client.ts
│   ├── package.json
│   └── vite.config.ts
├── docs/
└── README.md
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/listings` | List listings with filters (distance, price, search, sort, category) |
| GET | `/api/listings/{id}` | Single listing detail |
| GET | `/api/categories` | All 7 categories with listing counts |
| POST | `/api/scrape` | Trigger a scrape run (admin) |
| GET | `/api/scrape/status` | Current scrape job status |
| GET | `/api/geo/plz/{plz}` | Resolve PLZ to coordinates |

### Query Parameters for `GET /api/listings`

- `plz` (string) — reference PLZ for distance calculation
- `max_distance` (int, km) — radius filter
- `sort` (enum: `distance`, `price`, `date`) — sort order
- `search` (string) — full-text search in title + description
- `page`, `per_page` — pagination

## Scraping Strategy

1. **Crawl phase:** Iterate over all 7 "Biete" categories sequentially; for each, paginate through overview pages collecting thread URLs and external IDs
2. **Parse phase:** For each new/updated thread, fetch detail page and extract structured fields; tag each listing with its source category
3. **Rate limiting:** 2 seconds between requests; no parallelism across categories (intentional — polite to the forum)
4. **Deduplication:** Use `external_id` (globally unique XenForo thread ID) as unique key; update existing records on re-scrape
5. **Incremental:** Stop-early per category when a full overview page contains only known IDs (listings are newest-first); hard cap of 40 pages per category
6. **Sold recheck:** Phase 2 re-fetches the 250 oldest non-sold listings per hourly run to detect sold status
7. **Outdated retention (Phase 3):** Listings with `posted_at` older than 8 weeks are marked `is_outdated = TRUE` instead of being deleted — history is preserved. The `GET /api/listings` default hides both sold and outdated rows; two independent query params (`show_outdated`, `only_sold`) opt into each group. `GET /api/favorites` is unaffected — pinned listings always appear regardless of status.

## Geodata

- Source: OpenGeoDB or GeoNames — free CSV with German PLZ, city name, latitude, longitude
- Imported once into a `plz_geodata` table via a seed script (`python -m app.seed_plz`)
- Lookup at scrape/query time via simple DB query (`SELECT lat, lon FROM plz_geodata WHERE plz = ?`)
- No in-memory loading — at 500ms+ between scrape requests, DB lookup latency is irrelevant
- Haversine formula for distance calculation (sufficient accuracy for this use case)

## Frontend Patterns

- Single-page app with React Router
- Client-side PLZ stored in localStorage
- API calls via fetch/axios with React Query for caching
- Responsive card grid layout (mobile-first)
- Auth-gated SPA — unauthenticated users hit `/login` (Google SSO redirect); the `useAuth` hook gates all routes
- Admin functions are accessed via the central **d2x-control-plane cockpit** (`admin.d2x-labs.de`) — the PWA does not expose `/admin` or `/admin/users` (removed PLAN-034; standalone SPA retired PLAN-037)

## Auth & Admin

- **Login:** Google OAuth2. Callback `/api/auth/google/callback` upserts the user by `google_id`, gates on an `is_approved` whitelist flag, and issues a JWT session cookie. Unapproved users are redirected to `/login?error=not_approved`. 2FA is enforced at the Google-account level (no app-side TOTP).
- **Roles:** `member` (read-only browsing + saved searches/favorites/push) and `admin`. `require_admin` guards every `/api/admin/*` endpoint.
- **Admin endpoints:** `GET /admin/users`, `PATCH /admin/users/{id}/approval`, `DELETE /admin/users/{id}` (DSGVO hard-delete — cascades to saved searches, favorites, push subscriptions, login events; self-deletion blocked), `GET /admin/users/{id}/stats`, `GET /admin/metrics/summary`, `GET /admin/metrics/timeseries`, plus LLM cascade management.
- **Telemetry:** `login_events` table records one row per successful approved login (backend-only, no external analytics). The "Aktiv (7/30 T)" metric is derived from `users.last_seen_at`, which is updated on every authenticated API call (`/api/auth/me`) — so it approximates users who made API requests in the window, not raw login counts (those come from `login_events`).
- **Cockpit auth (PLAN-036/PLAN-037):** The d2x-control-plane cockpit authenticates to `/api/admin/*` via RS256/JWKS JWT (`COCKPIT_AUTH_ENABLED=true`, `COCKPIT_JWKS_URL=https://admin.d2x-labs.de/.well-known/jwks.json`) over the private `d2x-internal` Docker network. The session cookie break-glass path is preserved. `COOKIE_DOMAIN` and `ADMIN_URL` have been removed from the backend env (standalone console retired). Session cookie in dev remains host-only.

## Test Strategy

- **Backend:** pytest (async), focused on parser (known HTML fixtures), geo calculations, and the admin API. Admin tests use the `admin_client` fixture (seeds an `admin` role, yields `(client, admin_id)`) and `authenticated_client` (member role). No live external requests.
- **Frontend:** Vitest + React Testing Library for component tests. **Vitest globals are NOT enabled** — every test imports them explicitly (`import { describe, it, expect, vi } from 'vitest'`).
- **Integration:** Scraper tests against saved HTML snapshots (no live requests in CI).

## Deployment (VPS)

- Docker Compose: backend + frontend (nginx) + PostgreSQL
- Cron job or background task for periodic scraping
- **Private access only** — no public exposure, firewall/VPN restricted to owner
- No auth layer needed (single user behind network restriction)

## Ähnliche Inserate (Vergleichs-Popup)

`GET /api/listings/{id}/comparables` liefert bis zu 30 Inserate gleicher Kategorie, gefiltert nach harten Attributen — `model_type`, `model_subtype`, `drive_type` (strikt, falls am Base gesetzt; Kandidaten mit NULL werden toleriert) und `wingspan_mm` ±25 % (ebenfalls NULL-tolerant). Sold + outdated Inserate werden eingeschlossen. Keine Median-/Similarity-Bewertung mehr — rein kategoriale Filterung.

## Notification Channel (Web Push)

`app/notifications/registry.py` holds a singleton `notification_registry`. Plugins implement `NotificationPlugin` (`is_configured()` + `send(MatchResult)`). `WebPushPlugin` is the sole delivery plugin (plus `LogPlugin`); it is registered in `app/main.py:lifespan()` when VAPID is configured. A shared helper `send_web_push_to_user(user_id, payload)` (in `web_push_plugin.py`) owns the per-subscription send loop, 404/410 stale-subscription garbage collection (scoped by `user_id`), and the per-delivered `last_used_at` bump. Both the plugin and the favorites status sweep (`app/notifications/fav_sweep.py`, scheduled every `FAV_SWEEP_INTERVAL_MIN` minutes) use this helper.

Subscriptions live in `push_subscriptions` (multi-device, `ON DELETE CASCADE` on the user). Per-user opt-in is `user_notification_prefs.web_push_enabled`, served via `GET/PUT /api/notifications/preferences` (the single source of truth). The frontend uses `vite-plugin-pwa` in `injectManifest` mode with a custom `src/sw.ts` (built to `dist/sw.js`, served `Cache-Control: no-cache` by `nginx.conf`) handling `push` + `notificationclick` (with an open-redirect-safe URL guard) and a `SKIP_WAITING` message. The frontend fetches the VAPID public key at runtime from `GET /api/notifications/vapid-public-key` (no build-time arg). `index.html` is also served no-cache so redeploys are discovered.

Telegram was fully removed in PLAN-027 (modules, routes, settings, the `telegram_link_tokens` table, and the `users.telegram_chat_id`/`telegram_linked_at` columns).
