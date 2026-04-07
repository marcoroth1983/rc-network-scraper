# PLAN 001 — Scraper Core

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Build the foundational scraper that extracts RC airplane listings from rc-network.de and stores them in PostgreSQL with geodata enrichment.

**Architecture:** Python/FastAPI backend with async SQLAlchemy, PostgreSQL via Docker from day one. Scraper fetches overview pages, parses detail pages, enriches with lat/lon from a seeded PLZ table, and upserts into the listings table.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async), httpx, BeautifulSoup4, PostgreSQL 16, Docker Compose

**Breaking Changes:** No — greenfield project, nothing to break.

**Step status convention:** `[ ]` = open, `[x]` = done

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-06 |
| Human | approved | 2026-04-06 |

**Source:** `https://www.rc-network.de/forums/biete-flugmodelle.132/`

**Out of scope for this plan (deferred to later phases):**
- `GET /api/scrape/status` endpoint
- `GET /api/geo/plz/{plz}` endpoint
- Frontend
- Distance-based filtering/sorting in the API

---

### Step 1: Project Structure & Docker Setup [x]

Create the project skeleton:

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings via pydantic-settings
│   ├── db.py                # SQLAlchemy async engine + session + init_db()
│   ├── models.py            # Listing + PlzGeodata ORM models
│   ├── seed_plz.py          # One-time PLZ CSV → DB import
│   ├── geo/
│   │   ├── __init__.py
│   │   └── distance.py      # Haversine calculation
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # REST endpoints
│   │   └── schemas.py       # Pydantic response models
│   └── scraper/
│       ├── __init__.py
│       ├── crawler.py       # Overview page traversal
│       ├── parser.py        # Detail page extraction (pure function, no I/O)
│       └── orchestrator.py  # Scrape orchestration (created in Step 7)
├── data/
│   └── plz_de.csv           # German PLZ geodata source file
├── tests/
│   ├── conftest.py          # Shared fixtures (DB session, HTML fixtures)
│   ├── fixtures/            # Saved HTML files for testing
│   ├── test_crawler.py
│   ├── test_parser.py
│   ├── test_distance.py
│   └── test_orchestration.py
├── Dockerfile
└── requirements.txt
docker-compose.yml           # At project root
```

**Dockerfile (backend):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Source is provided via bind mount in dev; COPY not needed here
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**docker-compose.yml:**
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: rcscout
      POSTGRES_PASSWORD: rcscout_dev
      POSTGRES_DB: rcscout
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rcscout"]
      interval: 5s
      timeout: 3s
      retries: 5

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout
      SCRAPE_DELAY: 1.0

volumes:
  pgdata:
```

Note: `SCRAPE_DELAY` defaults to 1.0s to match the architecture's "max 1 request per second" rule.

**requirements.txt:**
```
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
httpx>=0.27
beautifulsoup4>=4.12
lxml>=5.0
pydantic-settings>=2.0
python-dateutil>=2.9
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
```

### Step 2: Database Models [x]

**Depends on:** Step 1

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/app/db.py`

**Listing model (SQLAlchemy):**

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, autoincrement |
| external_id | String | `unique=True, index=True` — thread ID from rc-network.de |
| url | String | Full URL to original listing |
| title | String | |
| price | String (nullable) | Raw text, e.g. "170€" |
| condition | String (nullable) | Raw text |
| shipping | String (nullable) | Raw text |
| description | Text | Full post body |
| images | JSONB | List of image URLs (`from sqlalchemy.dialects.postgresql import JSONB`) |
| author | String | |
| posted_at | DateTime(timezone=True) (nullable) | TZ-aware; parsed from XenForo `<time datetime="...">` ISO-8601 |
| posted_at_raw | String (nullable) | Original date string as fallback |
| plz | String (nullable) | Extracted from Artikelstandort |
| city | String (nullable) | Extracted from Artikelstandort |
| latitude | Float (nullable) | Populated from `plz_geodata` join after scrape |
| longitude | Float (nullable) | Populated from `plz_geodata` join after scrape |
| scraped_at | DateTime(timezone=True) | Timestamp of last scrape; add `index=True` for freshness queries |

**PlzGeodata model (SQLAlchemy):**

| Column | Type | Notes |
|--------|------|-------|
| plz | String(5) | PK |
| city | String | City name |
| lat | Float | Latitude |
| lon | Float | Longitude |

**`db.py` must expose an `init_db()` async helper** that calls `create_all`. Called from:
1. `main.py` startup event
2. `tests/conftest.py` before each test session

Create tables via `init_db()` (no Alembic needed for Phase 1).

### Step 3: PLZ Seed Script [x]

**Depends on:** Step 2

**Files:**
- Create: `backend/app/seed_plz.py`
- Provide: `backend/data/plz_de.csv`

**PLZ CSV source:** Download from OpenGeoDB via GeoNames mirror:
```bash
# Download and place at backend/data/plz_de.csv
curl -L "https://download.geonames.org/export/zip/DE.zip" -o /tmp/DE.zip
unzip /tmp/DE.zip DE.txt -d /tmp/
# DE.txt is tab-separated with no header; relevant columns:
# col 0: country_code, col 1: postal_code (PLZ), col 2: place_name,
# col 9: latitude, col 10: longitude
cp /tmp/DE.txt backend/data/plz_de.csv
```

**CSV column mapping (tab-separated, no header):**
| Index | Field | Maps to |
|-------|-------|---------|
| 1 | postal_code | `plz` |
| 2 | place_name | `city` |
| 9 | latitude | `lat` |
| 10 | longitude | `lon` |

Script reads the CSV and bulk-inserts into `plz_geodata`. Idempotent — uses `ON CONFLICT DO NOTHING`. Run once after first `docker compose up`:

```bash
docker compose exec backend python -m app.seed_plz
```

### Step 4: Overview Page Crawler (`crawler.py`) [x]

**Depends on:** Step 1

**Files:**
- Create: `backend/app/scraper/crawler.py`

**Responsibilities:**
- Accept a starting URL and `max_pages` parameter
- Fetch each overview page (`/page-1` through `/page-N`)
- Parse thread links from `div.structItem` elements
- Extract `external_id` from URL pattern `/threads/<slug>.<id>/`
- Return list of `{external_id, url}` dicts
- Respect configurable delay between requests (default 1.0s)
- Use `httpx.AsyncClient` with User-Agent: `"rc-markt-scout/0.1 (personal hobby project)"`

Note: The crawler does NOT filter by known IDs — that is the orchestrator's job (Step 7).

### Step 5: Detail Page Parser (`parser.py`) [x]

**Depends on:** Step 1

**Files:**
- Create: `backend/app/scraper/parser.py`

**The parser is a pure function** — it takes an HTML string and returns a dict. No network I/O. Fetching is handled by the orchestrator.

```python
def parse_detail(html: str) -> dict:
    ...
```

**Extraction rules:**
- `title`: from page/thread title
- `Preis:` → `price`
- `Zustand:` → `condition`
- `Versandart/-kosten:` → `shipping`
- `Artikelstandort:` → split into `plz` and `city` (format: `"92694, Etzenricht"`)
- Description text (full post body minus the structured fields)
- Image URLs from attachments
- Author name
- Post date → parse to `DateTime` where possible, keep raw string as fallback

**Critical: First-post isolation.** XenForo threads have replies. The parser MUST extract data only from the first post (`article.message--post:first-of-type` or by `data-author` matching the thread starter). Reply text must not contaminate the description or structured fields.

**Graceful handling of missing/malformed fields:**
- Missing price, condition, shipping → `null`
- Missing or malformed Artikelstandort (no comma, no PLZ, reversed order) → `plz=null`, `city=null`
- No images → empty list
- Unparseable date → `posted_at=null`, store raw string in `posted_at_raw`

### Step 6: Tests — Crawler & Parser [x]

**Depends on:** Steps 4, 5

**Files:**
- Create: `backend/tests/fixtures/overview_page.html`
- Create: `backend/tests/fixtures/detail_complete.html`
- Create: `backend/tests/fixtures/detail_missing_price.html`
- Create: `backend/tests/fixtures/detail_missing_location.html`
- Create: `backend/tests/fixtures/detail_malformed_location.html`
- Create: `backend/tests/fixtures/detail_no_images.html`
- Create: `backend/tests/test_crawler.py`
- Create: `backend/tests/test_parser.py`

**`conftest.py` setup:**
- Use `asyncio_mode = "auto"` in `pytest.ini` or `pyproject.toml` (`[tool.pytest.ini_options]`)
- DB fixture: create a separate test database (`rcscout_test`), call `init_db()` once per session, and drop/recreate tables between tests for isolation
- Add a `test_db_url` fixture that overrides `DATABASE_URL` for the duration of the test session

**Fixture collection:** Save real HTML from rc-network.de for realistic testing. Minimum fixtures:

1. One overview page (with ~20 listings)
2. One complete detail page (all fields populated)
3. Detail page with missing price
4. Detail page with missing Artikelstandort
5. Detail page with malformed location (e.g. just a city name, no PLZ)
6. Detail page with no images

**test_crawler.py:**
- Test URL extraction from overview HTML fixture
- Test `external_id` parsing from URLs
- Test empty page returns empty list

**test_parser.py:**
- Test all field extraction from complete detail fixture
- Test missing price → `price=null`
- Test missing Artikelstandort → `plz=null`, `city=null`
- Test malformed location → graceful fallback
- Test no images → empty list
- Test first-post isolation (fixture with replies should only extract from first post)
- Test date parsing to DateTime

### Step 7: Scrape Orchestration [x]

**Depends on:** Steps 2, 3, 4, 5

**Files:**
- Create: `backend/app/scraper/orchestrator.py`

**Flow:**
1. Crawler collects all `{external_id, url}` from overview pages
2. Query DB: find listings where `external_id` is known AND `scraped_at` is newer than a configurable threshold (default: 7 days) → these are "fresh", skip them
3. Remaining IDs (unknown + stale) get fetched and parsed
4. For each parsed listing:
   a. Look up `plz` in `plz_geodata` table → set `latitude`/`longitude` (null if PLZ not found)
   b. Upsert into `listings` table (`INSERT ... ON CONFLICT(external_id) DO UPDATE`)
5. Log progress: pages crawled, listings found, new vs updated counts
6. Return summary dict

This resolves the skip-vs-upsert question: **fresh listings are skipped, stale listings are re-scraped and upserted.**

### Step 8: Integration Test — Orchestration [x]

**Depends on:** Step 7

**Files:**
- Create: `backend/tests/test_orchestration.py`

Test the full orchestration flow against fixtures (no live HTTP):
- Mock `httpx` responses with saved HTML fixtures
- Run orchestrator against a test DB
- Assert: correct number of listings in DB
- Assert: fields correctly populated (including lat/lon from plz_geodata)
- Assert: re-running with same fixtures does NOT create duplicates (upsert works)
- Assert: stale listings get updated `scraped_at` timestamp

### Step 9: API Endpoints [x]

**Depends on:** Step 7

**Files:**
- Create: `backend/app/api/routes.py`
- Create: `backend/app/api/schemas.py`

**Endpoints:**
- `GET /health` — returns `{"status": "ok"}`
- `POST /api/scrape` — triggers scrape run synchronously, accepts `?max_pages=N`, returns summary (blocks until complete; async background execution deferred to later plans)
- `GET /api/listings` — returns all listings, paginated (`?page=1&per_page=20`)
- `GET /api/listings/{id}` — single listing detail

**Pydantic schemas** for response models (ListingSummary, ListingDetail, ScrapeSummary, PaginatedResponse).

**Deferred to later plans:**
- `GET /api/scrape/status` — scrape job status
- `GET /api/geo/plz/{plz}` — PLZ resolution endpoint
- Distance filtering/sorting query parameters

### Step 10: Haversine Distance Utility [x]

**Depends on:** Step 1

**Files:**
- Create: `backend/app/geo/distance.py`
- Create: `backend/tests/test_distance.py`

Simple Haversine function for later use in distance filtering. Included now to match the architecture's file structure.

```python
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    ...
```

Not wired into the API in this plan. `test_distance.py` must include at least:
- Known distance between two fixed coordinates (e.g. Berlin → Munich ≈ 504 km, tolerance ±2 km)
- Same point → 0.0 km

---

## Verification

```bash
# Start containers
docker compose up --build -d

# Wait for healthy DB (should be automatic via depends_on + healthcheck)
docker compose ps

# Seed PLZ data
docker compose exec backend python -m app.seed_plz

# Verify services are running
curl http://localhost:8000/health

# Run all tests
docker compose exec backend pytest tests/ -v

# Trigger a small scrape (first 2 pages only, for verification)
curl -X POST "http://localhost:8000/api/scrape?max_pages=2"

# Check results
curl "http://localhost:8000/api/listings?page=1"

# Verify a listing has lat/lon populated
curl http://localhost:8000/api/listings/1
```

## Assumptions & Risks

- **HTML structure may change:** rc-network.de runs XenForo forum software. A major update could break the parser. Mitigation: HTML fixtures in tests make breakage immediately visible.
- **Rate limiting / IP blocking:** 1.0s delay should be safe. If blocked, increase delay or add proxy support later.
- **Field format variations:** `Artikelstandort` may not always follow `PLZ, City` format. Parser handles missing/malformed location gracefully (set plz/city to null).
- **First-post isolation:** XenForo post structure must be verified against real HTML. If the selector changes, only the parser fixture tests break — easy to fix.
- **PLZ coverage:** The CSV may not cover all German PLZ codes. Listings with unknown PLZ get `latitude=null, longitude=null`.

## Reviewer Findings (incorporated)

All 7 blocking issues and 7 non-blocking notes from the initial review have been addressed:

1. **Skip vs. upsert** → Resolved: skip fresh listings (scraped within threshold), re-scrape stale ones, upsert on conflict (Step 7)
2. **Missing lat/lon** → Added `latitude`/`longitude` to Listing model, populated from `plz_geodata` during orchestration (Steps 2, 7)
3. **Incomplete file structure** → Full skeleton with all files: `seed_plz.py`, `plz_de.csv`, `api/routes.py`, `api/schemas.py`, `geo/distance.py` (Step 1)
4. **Docker race condition** → Added `healthcheck` on db service + `condition: service_healthy` (Step 1)
5. **No orchestration test** → Added dedicated integration test (Step 8)
6. **`mvp.md` outdated** → Flagged for separate update (see below)
7. **Missing status fields** → Added `[ ]` markers to all steps
8. **Rate limit** → Default changed to 1.0s
9. **`posted_at` as string** → Now `DateTime` with raw string fallback
10. **Parser I/O** → Pure function `parse_detail(html: str)`, no network I/O
11. **First-post isolation** → Explicitly specified in parser requirements
12. **Thin fixtures** → Expanded to 6 fixtures covering known edge cases
13. **Missing endpoints** → Explicitly marked as deferred to later phases
14. **Approval table** → Present and correct

**Note:** `docs/mvp.md` already reflects PostgreSQL-from-day-one — no update required.
