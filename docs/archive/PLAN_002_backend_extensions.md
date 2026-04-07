# PLAN 002 — Backend API Extensions

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Extend the API with PLZ resolution, text search, distance filtering, and multi-field sorting on listings — everything the frontend needs to be functional.

**Architecture:** All changes are additive to existing `routes.py` and `schemas.py`. Distance filtering and price sorting are done in Python after DB fetch (listing count is small, < 5k rows). The existing `haversine_km` utility in `geo/distance.py` is used directly. Search uses PostgreSQL `ILIKE` in SQL. PLZ geodata must be seeded before the geo endpoint is useful. API tests use `httpx.AsyncClient` with `ASGITransport` + `app.dependency_overrides` to redirect `get_session` to the test DB.

**Tech Stack:** FastAPI, SQLAlchemy (async), existing `haversine_km`, Python `re` for price extraction.

**Breaking Changes:** No — additive query parameters and new endpoint only. `ListingSummary` gains an optional `distance_km: float | None = None` field (null when no `plz` param given).

**Step status convention:** `[ ]` = open, `[x]` = done

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-06 |
| Human | approved | 2026-04-06 |

---

### Step 1: Seed PLZ Geodata [ ]

**Prerequisite — run manually before the rest of this plan.**

Download and seed the PLZ database into the running container. The seed script only writes to the **dev DB** (`rcscout`). Tests seed their own PLZ rows inline and do not rely on this data.

```bash
# Download GeoNames DE dataset
curl -L "https://download.geonames.org/export/zip/DE.zip" -o /tmp/DE.zip
unzip /tmp/DE.zip DE.txt -d /tmp/
cp /tmp/DE.txt backend/data/plz_de.csv

# Seed into dev DB (container must be running)
docker compose exec backend python -m app.seed_plz
```

Expected output: `Seeded XXXXX PLZ rows` (approximately 16 000 rows).

Verify:
```bash
docker compose exec db psql -U rcscout -c "SELECT COUNT(*) FROM plz_geodata;"
```
Expected: `~16000`

---

### Step 2: Test Infrastructure — `api_client` Fixture [ ]

**Files:**
- Modify: `backend/tests/conftest.py`

Add a reusable `api_client` fixture that:
1. Overrides FastAPI's `get_session` dependency to yield sessions bound to `test_engine` (the test DB, not the production DB)
2. Returns an `httpx.AsyncClient` with `ASGITransport` pointing at the app
3. Cleans up `dependency_overrides` after each test

Also move the `clean_listings` autouse fixture from `test_orchestration.py` into `conftest.py` so it applies to all integration test modules (including the new `test_api.py`).

```python
# In conftest.py — add these fixtures:

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

@pytest_asyncio.fixture()
async def api_client(test_engine):
    """AsyncClient wired to the test DB via dependency_overrides."""
    from app.main import app
    from app.db import get_session

    factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
```

Also move `clean_listings` from `test_orchestration.py` to `conftest.py` (keep `autouse=True`). Update `test_orchestration.py` to remove its local copy.

---

### Step 3: `GET /api/geo/plz/{plz}` Endpoint [ ]

**Depends on:** Step 2

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_api.py`

**Add to `schemas.py`:**

```python
class PlzResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plz: str
    city: str
    lat: float
    lon: float
```

**Add to `routes.py`:**

```python
from app.models import PlzGeodata

@router.get("/geo/plz/{plz}", response_model=PlzResponse)
async def resolve_plz(
    plz: str,
    session: AsyncSession = Depends(get_session),
) -> PlzResponse:
    """Resolve a German PLZ to coordinates. Returns 404 if PLZ not found."""
    result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PLZ not found")
    return PlzResponse.model_validate(row)
```

**`PlzGeodata` model fields** (for reference): `plz: str`, `city: str`, `lat: float`, `lon: float` — these match `PlzResponse` exactly.

**Tests in `backend/tests/test_api.py`:**

```python
async def test_resolve_plz_found(api_client, db_session):
    # Seed one PLZ row via db_session
    await db_session.execute(
        text("INSERT INTO plz_geodata (plz, city, lat, lon) VALUES ('80331', 'München', 48.1374, 11.5755)")
    )
    await db_session.commit()
    response = await api_client.get("/api/geo/plz/80331")
    assert response.status_code == 200
    data = response.json()
    assert data["plz"] == "80331"
    assert data["city"] == "München"
    assert isinstance(data["lat"], float)

async def test_resolve_plz_not_found(api_client):
    response = await api_client.get("/api/geo/plz/00000")
    assert response.status_code == 404
```

---

### Step 4: `GET /api/listings` — Text Search [ ]

**Depends on:** Step 3

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`

Add `search: str | None = Query(default=None)` parameter. When provided, filter listings in SQL before count and fetch:

```python
from sqlalchemy import or_

if search:
    stmt = stmt.where(
        or_(
            Listing.title.ilike(f"%{search}%"),
            Listing.description.ilike(f"%{search}%"),
        )
    )
```

Apply the same `search` filter to both the `count()` query and the `select()` query so `total` reflects the filtered set.

**Tests:**

```python
async def test_search_filters_by_title(api_client, db_session):
    # Insert listing with title "Multiplex EasyStar", another with "Unrelated"
    # GET /api/listings?search=Multiplex
    # Assert response total=1, items[0].title contains "Multiplex"

async def test_search_no_match_returns_empty(api_client, db_session):
    # GET /api/listings?search=xyzzy_no_match
    # Assert total=0, items=[]

async def test_search_matches_description(api_client, db_session):
    # Insert listing with description containing unique keyword
    # GET /api/listings?search=<keyword>
    # Assert total=1
```

Helper for inserting test listings — add to `test_api.py`:

```python
async def _insert_listing(session, *, external_id, title, description="", price=None,
                          plz=None, lat=None, lon=None):
    from datetime import datetime, timezone
    await session.execute(text("""
        INSERT INTO listings (external_id, url, title, price, condition, shipping,
            description, images, author, posted_at, posted_at_raw, plz, city,
            latitude, longitude, scraped_at)
        VALUES (:eid, :url, :title, :price, NULL, NULL,
            :desc, '[]', 'TestUser', NOW(), NULL, :plz, NULL,
            :lat, :lon, NOW())
    """), {"eid": external_id, "url": f"https://example.com/{external_id}",
           "title": title, "price": price, "desc": description,
           "plz": plz, "lat": lat, "lon": lon})
    await session.commit()
```

---

### Step 5: `GET /api/listings` — Sorting [ ]

**Depends on:** Step 4

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`

**Add `distance_km` to `ListingSummary`:**

```python
class ListingSummary(BaseModel):
    ...
    distance_km: float | None = None  # populated only when ?plz is provided
```

**Sort modes:**

| `sort` value | Behaviour |
|---|---|
| `date` (default) | `ORDER BY posted_at DESC NULLS LAST` in SQL |
| `price` | All rows fetched, sorted in Python ascending by extracted numeric value; nulls last |
| `distance` | Requires `plz`; all rows fetched, Haversine calculated per row, sorted ascending; listings without lat/lon sort last |

**Updated query param signature** (use `Literal` — cleaner than `pattern=`):

```python
from typing import Literal

sort: Literal["date", "price", "distance"] = Query(default="date"),
plz: str | None = Query(default=None),
```

**Validation:** If `sort="distance"` and `plz` is `None` → `HTTP 400 "plz is required when sort=distance"`.

**Price sort helper** (put inside `routes.py`, not exported):

```python
import re

def _price_numeric(price: str | None) -> float:
    """Extract the first integer from a price string. Returns inf for non-numeric."""
    if not price:
        return float("inf")
    # Strip thousands separators (.) but keep decimal comma → take integer part only
    cleaned = price.split(",")[0].replace(".", "")
    m = re.search(r"\d+", cleaned)
    return float(m.group()) if m else float("inf")
```

**Distance sort key** (handles `None` lat/lon):

```python
def _dist_key(listing, ref_lat: float, ref_lon: float) -> float:
    if listing.latitude is None or listing.longitude is None:
        return float("inf")
    return haversine_km(ref_lat, ref_lon, listing.latitude, listing.longitude)
```

**Populating `distance_km` in response items:**

`model_validate` does not know `distance_km` from the ORM object. Build items explicitly:

```python
summary = ListingSummary.model_validate(row)
summary = summary.model_copy(update={"distance_km": dist})  # dist is float | None
items.append(summary)
```

**For `sort=date`:** Use SQL `ORDER BY posted_at DESC NULLS LAST`, then validate directly with `ListingSummary.model_validate(row)` (no Python sort needed). Compute `total` with SQL `count()`.

**For `sort=price` and `sort=distance`:** Fetch all rows from DB (applying only the `search` SQL filter), sort in Python, then:
- `total = len(all_rows)` — computed *before* slice
- `items = all_rows[offset : offset + per_page]`

**Tests:**

```python
async def test_sort_by_date_returns_newest_first(api_client, db_session):
    # Insert 2 listings with different posted_at
    # GET /api/listings?sort=date
    # Assert response items ordered newest first

async def test_sort_by_price_ascending(api_client, db_session):
    # Insert listings with prices "300€", "50€", None
    # GET /api/listings?sort=price
    # Assert order: 50, 300, None-last

async def test_sort_distance_without_plz_returns_400(api_client):
    response = await api_client.get("/api/listings?sort=distance")
    assert response.status_code == 400

async def test_sort_by_distance_with_plz(api_client, db_session):
    # Seed plz_geodata for two PLZs (München ~0km from ref, Hamburg ~612km)
    # Insert two listings with those coords
    # GET /api/listings?sort=distance&plz=80331
    # Assert München listing first, distance_km populated
```

---

### Step 6: `GET /api/listings` — Distance Filter [ ]

**Depends on:** Step 5

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`

Add `max_distance: int | None = Query(default=None, ge=1)`.

**Behaviour when `max_distance` is provided:**
- `plz` must also be provided → 400 if missing
- Fetch all rows (with search filter applied in SQL)
- Calculate distance for each row that has `latitude`/`longitude`
- Keep rows where `distance_km <= max_distance` **OR** `latitude IS NULL` (no coordinates → always include, cannot rule out)
- `total = len(filtered_rows)` — NOT a SQL count (Python-side filter changes the set)

**Rationale:** Listings without coordinates still have a city name or description that may be relevant. Excluding them silently would hide potentially interesting results. Future plan: city-name based distance approximation.

**Important:** `total` must be derived from the post-filter Python list, not from a SQL `count()`. SQL count only reflects the `search` filter; the distance filter happens in Python.

```python
# After fetching all rows and computing distances:
filtered = []
for row in all_rows:
    if row.latitude is not None and row.longitude is not None:
        dist = haversine_km(ref_lat, ref_lon, row.latitude, row.longitude)
        if dist <= max_distance:
            filtered.append((row, dist))
    else:
        filtered.append((row, None))  # no coords → always include, distance_km=None
total = len(filtered)
page_items = filtered[offset : offset + per_page]
```

**Tests:**

```python
async def test_max_distance_filters_far_listings(api_client, db_session):
    # Seed plz_geodata for München (ref) and Hamburg (~612km)
    # Insert near listing (München), far listing (Hamburg)
    # GET /api/listings?plz=80331&max_distance=100
    # Assert total=1, only near listing returned

async def test_max_distance_includes_listings_without_coords(api_client, db_session):
    # Insert listing with latitude=None, longitude=None
    # GET /api/listings?plz=80331&max_distance=100
    # Assert listing IS included (total=1), distance_km=None

async def test_max_distance_requires_plz(api_client):
    response = await api_client.get("/api/listings?max_distance=100")
    assert response.status_code == 400

async def test_total_reflects_distance_filter(api_client, db_session):
    # Insert 3 listings: 2 near, 1 far
    # GET /api/listings?plz=80331&max_distance=100
    # Assert total=2 (not 3)
```

---

### Step 7: Verification — API Smoke Tests [ ]

**Depends on:** Steps 1–6 (requires running Docker containers + seeded PLZ data from Step 1)

```bash
# Run unit tests first
docker compose exec backend pytest tests/ -v
# Expected: all tests pass

# 1. PLZ resolution — known PLZ
curl -s "http://localhost:8002/api/geo/plz/80331" | python -m json.tool
# Expected: {"plz":"80331","city":"...","lat":...,"lon":...}

# 2. PLZ resolution — unknown PLZ
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8002/api/geo/plz/00000"
# Expected: 404

# 3. Text search (use a word you know exists from the prior scrape)
curl -s "http://localhost:8002/api/listings?search=Flugzeug&per_page=3" | python -m json.tool
# Expected: all items have "Flugzeug" in title or description

# 4. Sort by date (default) — newest first
curl -s "http://localhost:8002/api/listings?per_page=3" | python -m json.tool
# Expected: posted_at descending

# 5. Sort by price — lowest first
curl -s "http://localhost:8002/api/listings?sort=price&per_page=5" | python -m json.tool
# Expected: price values ascending (non-numeric last)

# 6. Sort by distance without plz — must fail
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8002/api/listings?sort=distance"
# Expected: 400

# 7. Sort by distance with PLZ
curl -s "http://localhost:8002/api/listings?sort=distance&plz=80331&per_page=5" | python -m json.tool
# Expected: distance_km populated on each item, ascending order

# 8. Distance filter
curl -s "http://localhost:8002/api/listings?plz=80331&max_distance=200&per_page=5" | python -m json.tool
# Expected: every item has distance_km <= 200

# 9. Combined: search + distance + sort
curl -s "http://localhost:8002/api/listings?plz=80331&max_distance=400&sort=distance&per_page=5" | python -m json.tool
# Expected: all items within 400km, ordered nearest first, distance_km populated
```

---

## Assumptions & Risks

- **Price string format varies:** "150€", "150 EUR", "VB", "auf Anfrage". The `_price_numeric` helper extracts the first integer from the integer part only (splits on comma). Non-numeric prices sort to the end. This is intentional and documented.
- **Distance filter includes no-location listings:** Listings without `latitude`/`longitude` are always included when `max_distance` is set (`distance_km=null` in response). They cannot be ruled out by distance, and city-name search is planned for a future phase.
- **`total` is computed in Python when distance filter is active:** SQL `count()` is only used for `sort=date` (no Python-side filtering). For `sort=price`/`sort=distance`, `total = len(all_rows_after_python_filter)`.
- **Python-side sort/filter:** All matching rows fetched from DB before distance/price sort. Acceptable for < 5k listings.
- **PLZ lookup for distance features:** If the user's PLZ is not in the seed data, returns 400. Consistent behaviour for both `sort=distance` and `max_distance`.
