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
| GET | `/api/listings` | List listings with filters (distance, price, search, sort) |
| GET | `/api/listings/{id}` | Single listing detail |
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

1. **Crawl phase:** Iterate overview pages (`/page-1` through `/page-N`), collect thread URLs and external IDs
2. **Parse phase:** For each new/updated thread, fetch detail page and extract structured fields
3. **Rate limiting:** Max 1 request per second, respect `robots.txt`
4. **Deduplication:** Use `external_id` (thread ID) as unique key, update existing records on re-scrape
5. **Incremental:** Track `scraped_at`, only re-scrape listings older than configurable threshold

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
