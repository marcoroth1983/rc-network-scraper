# RC-Markt Scout — Architecture

> **Scope:** Personal hobby project — single user, no auth, no multi-tenancy.
> VPS deployment is private (only the owner has access).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI |
| Scraping | httpx + BeautifulSoup4 |
| Database | PostgreSQL 16 (dev and prod, via Docker) |
| ORM | SQLAlchemy (async) |
| Geodata | `plz_geodata` DB table (seeded once from CSV) |
| Frontend | React 18+ with TypeScript, Vite |
| Styling | Tailwind CSS |
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
- No auth required — read-only public interface

## Test Strategy

- **Backend:** pytest, focused on parser (known HTML fixtures) and geo calculations
- **Frontend:** Vitest + React Testing Library for component tests
- **Integration:** Scraper tests against saved HTML snapshots (no live requests in CI)

## Deployment (VPS)

- Docker Compose: backend + frontend (nginx) + PostgreSQL
- Cron job or background task for periodic scraping
- **Private access only** — no public exposure, firewall/VPN restricted to owner
- No auth layer needed (single user behind network restriction)

## Ähnliche Inserate (Vergleichs-Popup)

`GET /api/listings/{id}/comparables` liefert bis zu 30 Inserate gleicher Kategorie, gefiltert nach harten Attributen — `model_type`, `model_subtype`, `drive_type` (strikt, falls am Base gesetzt; Kandidaten mit NULL werden toleriert) und `wingspan_mm` ±25 % (ebenfalls NULL-tolerant). Sold + outdated Inserate werden eingeschlossen. Keine Median-/Similarity-Bewertung mehr — rein kategoriale Filterung.
