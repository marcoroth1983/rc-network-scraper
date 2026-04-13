# PLAN 013 — Multi-Category Support

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-13 |
| Human | approved | 2026-04-13 |

---

## Context & Goal

The app currently scrapes only **Biete – Flugmodelle** (`/forums/biete-flugmodelle.132/`).
The rc-network.de "Biete" section has 7 categories total. This plan extends the app to scrape
and display all of them.

**User-facing change:** On first page load (no category stored), a full-screen modal prompts the
user to pick a category. The selection is stored in `localStorage`. The user can switch categories
at any time via a selector in the header. All other features (search, distance filter, saved
searches, scraping) continue to work per-category.

**Confirmed categories** (fetched from `https://www.rc-network.de/categories/biete/`):

| Key | Label | Forum URL |
|-----|-------|-----------|
| `flugmodelle` | Flugmodelle | `/forums/biete-flugmodelle.132/` |
| `schiffsmodelle` | Schiffsmodelle | `/forums/biete-schiffsmodelle.133/` |
| `antriebstechnik` | Antriebstechnik | `/forums/biete-antriebstechnik.134/` |
| `rc-elektronik` | RC-Elektronik & Zubehör | `/forums/biete-rc-elektronik-zubeh%C3%B6r.135/` |
| `rc-cars` | RC-Cars & Funktionsmodelle | `/forums/biete-rc-cars-funktionsmodelle.146/` |
| `einzelteile` | Einzelteile & Sonstiges | `/forums/biete-einzelteile-sonstiges.136/` |
| `verschenken` | Zu verschenken | `/forums/zu-verschenken.11779439/` |

---

## Breaking Changes

**Yes — DB schema change required.**

- A `category` column is added to `listings` (`VARCHAR(50) NOT NULL DEFAULT 'flugmodelle'`).
  Existing rows are backfilled automatically by the column default.
- A `category` column is added to `saved_searches` (`VARCHAR(50) NULL`). Existing rows retain
  `NULL`, which the API treats as "all categories" (backwards-compatible).
- No data loss. Both changes are non-destructive `ADD COLUMN IF NOT EXISTS`.

**Recovery:** Revert the `init_db()` changes and restart the backend. The added columns are
inert if the application code is rolled back.

---

## Assumptions & Risks

- XenForo thread IDs are globally unique across all forums on rc-network.de, so the existing
  `UNIQUE(external_id)` constraint remains valid across categories. *(Standard XenForo behaviour.
  Contingency: if a collision is discovered post-launch, migrate to `UNIQUE(category, external_id)`
  and add a `category` prefix to `external_id` lookups.)*
- Scraping all 7 categories increases phase-1 duration ~7x for the initial full scan (one-time
  ~3.9 hours). Incremental runs remain ~1–2 min.
- The "Zu verschenken" category has no price field — the parser already handles this (returns
  `None` for missing price).
- **Favorites are intentionally cross-category.** A user may favourite a listing from any
  category; `GET /api/favorites` returns all favourites regardless of active category. This is
  the simplest behaviour and appropriate for a single-user app.

---

## Steps

### Step 1 — Category config + scrape settings in `config.py`

**File:** `backend/app/config.py`

Add a module-level `Category` dataclass and `CATEGORIES` list **outside** the `Settings` class
(not a pydantic field — it's static configuration):

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Category:
    key: str
    label: str
    url: str

CATEGORIES: list[Category] = [
    Category("flugmodelle",    "Flugmodelle",               "https://www.rc-network.de/forums/biete-flugmodelle.132/"),
    Category("schiffsmodelle", "Schiffsmodelle",            "https://www.rc-network.de/forums/biete-schiffsmodelle.133/"),
    Category("antriebstechnik","Antriebstechnik",           "https://www.rc-network.de/forums/biete-antriebstechnik.134/"),
    Category("rc-elektronik",  "RC-Elektronik & Zubehör",   "https://www.rc-network.de/forums/biete-rc-elektronik-zubeh%C3%B6r.135/"),
    Category("rc-cars",        "RC-Cars & Funktionsmodelle","https://www.rc-network.de/forums/biete-rc-cars-funktionsmodelle.146/"),
    Category("einzelteile",    "Einzelteile & Sonstiges",   "https://www.rc-network.de/forums/biete-einzelteile-sonstiges.136/"),
    Category("verschenken",    "Zu verschenken",            "https://www.rc-network.de/forums/zu-verschenken.11779439/"),
]

CATEGORY_KEYS: set[str] = {c.key for c in CATEGORIES}
```

Update `Settings` class:

| Setting | Old | New | Reason |
|---------|-----|-----|--------|
| `SCRAPE_DELAY` | `1.0` | `2.0` | Consistent with recheck; polite to forum |
| `RECHECK_DELAY` | `2.0` | `2.0` | No change |
| `RECHECK_BATCH_SIZE` | — (hardcoded 100) | `250` (new field) | ~10 min/run at 2s delay |

```python
SCRAPE_DELAY: float = 2.0
RECHECK_BATCH_SIZE: int = 250
```

**Runtime estimates:**

| Run type | Frequency | Estimated duration |
|----------|-----------|-------------------|
| Phase 1 — initial full scan (7 × 40 pages, one-time) | once | ~3.9 hours |
| Phase 1 — incremental (0–5 new listings/category) | every 30 min | ~1–2 min |
| Phase 2 — sold recheck (250 listings × 2.5s) | every 1 hour | ~10 min |

The initial full scan spans several 30-min scheduler windows — the scheduler skips correctly
when a job is already running.

---

### Step 2 — Wire `RECHECK_BATCH_SIZE` through `scrape_runner.py`

**File:** `backend/app/scrape_runner.py`

In `run_recheck_job()` (line ~190), change the call to `_phase2_sold_recheck()` to pass the
configured batch size:

```python
result = await _phase2_sold_recheck(
    session,
    update_progress=lambda p: _update(phase="phase2", progress=p),
    delay=settings.RECHECK_DELAY,
    batch_size=settings.RECHECK_BATCH_SIZE,   # was: default 100
)
```

---

### Step 3 — DB schema: add `category` column

**File:** `backend/app/db.py`

The project uses `init_db()` (no Alembic). Add two `ADD COLUMN IF NOT EXISTS` statements to
the existing migration block in `init_db()`:

```python
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS category VARCHAR(50) NOT NULL DEFAULT 'flugmodelle'"
))
await conn.execute(text(
    "CREATE INDEX IF NOT EXISTS ix_listings_category ON listings (category)"
))
await conn.execute(text(
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS category VARCHAR(50)"
))
```

**File:** `backend/app/models.py`

```python
# Listing — use server_default so raw-SQL inserts in tests also get the default
category: Mapped[str] = mapped_column(
    String(50), nullable=False, server_default="flugmodelle", index=True
)

# SavedSearch
category: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

`server_default` (not just `default`) is required because tests insert listings via raw SQL
that omits the `category` column — a Python-only `default` would not apply.

---

### Step 4 — Scraper: multi-category Phase 1

**File:** `backend/app/scraper/orchestrator.py`

Remove `_START_URL`. Refactor `_phase1_new_listings()` to loop over all categories sequentially
(**no parallelism** — intentional to avoid hammering the forum):

```python
async def _phase1_new_listings(session, update_progress, delay):
    total = {"pages_crawled": 0, "new": 0, "updated": 0, "new_ids": []}
    for cat in CATEGORIES:
        update_progress(f"Kategorie: {cat.label}…")
        stats = await _phase1_category(session, cat, update_progress, delay)
        total["pages_crawled"] += stats["pages_crawled"]
        total["new"]           += stats["new"]
        total["updated"]       += stats["updated"]
        total["new_ids"]       += stats["new_ids"]
    return total
```

`_phase1_category()` is the current `_phase1_new_listings()` body, with two changes:
1. Uses `cat.url` as start URL instead of `_START_URL`.
2. Passes `cat.key` to `_upsert_listing()`.

The stop-early logic (stop when a full page is fully known) works correctly **per category**
because `_phase1_category()` is its own loop that returns early independently.

**`_upsert_listing()`** — add `category: str` parameter and update `_UPSERT_SQL`:

The raw SQL statement at `orchestrator.py:71` must be updated in three places:
1. `INSERT` column list: add `category`
2. `VALUES` bind params: add `:category`
3. `ON CONFLICT DO UPDATE SET`: add `category = EXCLUDED.category`

```sql
INSERT INTO listings (
    external_id, url, title, price, price_numeric, condition, shipping,
    description, images, tags, author, posted_at, posted_at_raw,
    plz, city, latitude, longitude, scraped_at, is_sold, category   -- added
) VALUES (
    :external_id, :url, :title, :price, :price_numeric, :condition, :shipping,
    :description, :images, :tags, :author, :posted_at, :posted_at_raw,
    :plz, :city, :latitude, :longitude, :scraped_at, :is_sold, :category   -- added
)
ON CONFLICT (external_id) DO UPDATE SET
    ...existing fields...,
    category = EXCLUDED.category   -- added
RETURNING id, (xmax = 0) AS is_insert
```

---

### Step 5 — Search matcher: category filter

**File:** `backend/app/services/search_matcher.py`

In `_match_search()` (or wherever the candidate listing query is built), add a category filter
when `saved_search.category` is not `NULL`:

```python
if saved_search.category:
    query = query.where(Listing.category == saved_search.category)
```

Without this, a saved search scoped to "Antriebstechnik" would match listings from all
categories.

---

### Step 6 — API: category filter + categories endpoint

**File:** `backend/app/api/routes.py`

1. **`GET /api/listings`** — add optional `category` query param:

```python
category: str | None = Query(None)
```

When `category` is a valid key (in `CATEGORY_KEYS`), add WHERE clause:
```python
.where(Listing.category == category)
```
When `category` is `None` or `"all"`, no filter.
Return HTTP 400 for unknown category keys.
The `"all"` string from the frontend is never stored in the DB — it is treated as `None` at the
API boundary.

2. **New endpoint `GET /categories`** (note: no `/api` prefix — the router already has
`prefix="/api"`):

```python
@router.get("/categories")
async def get_categories(
    session: AsyncSession = Depends(get_session),
    _user = Depends(get_current_user),   # consistent with all other endpoints
):
    counts = await session.execute(
        select(Listing.category, func.count()).group_by(Listing.category)
    )
    count_map = dict(counts.all())
    return [
        {"key": c.key, "label": c.label, "count": count_map.get(c.key, 0)}
        for c in CATEGORIES
    ]
```

**File:** `backend/app/api/schemas.py`

- Add `category: str` to `ListingSummary` and `ListingDetail`
- Add `category: str | None` to `SavedSearch` and `SearchCriteria`

---

### Step 7 — Tests: update existing + add new

**Target test files:**
- `backend/tests/test_api.py`
- `backend/tests/test_orchestrator_phases.py`
- `backend/tests/test_search_matcher.py`
- `backend/tests/test_saved_searches.py`

**Required changes:**

1. Any fixture or helper that inserts a `Listing` via raw SQL or factory must include a
   `category` value (e.g. `'flugmodelle'`). With `server_default` this is only needed for
   raw-SQL inserts that bypass SQLAlchemy.

2. Add tests for `GET /categories` endpoint: returns all 7 categories, counts reflect DB state.

3. Add test for `GET /api/listings?category=flugmodelle`: only returns listings with that category.

4. Add test for `GET /api/listings?category=unknown`: returns 400.

5. Add test for search matcher category filter: a saved search with `category='rc-cars'` does
   not match a listing with `category='flugmodelle'`.

6. Add test for `_phase1_new_listings()` with multi-category: verifies that each listing is
   tagged with the correct category key.

---

### Step 8 — Frontend: types, API client, hook

**File:** `frontend/src/types/api.ts`

```typescript
export interface Category {
  key: string;
  label: string;
  count: number;
}

// Add to ListingSummary / ListingDetail:
category: string;

// Add to SearchCriteria / SavedSearch:
category?: string;   // undefined = all categories

// Add to ListingsFilter:
category: string;    // "all" or a category key
```

**File:** `frontend/src/api/client.ts`

```typescript
export async function getCategories(): Promise<Category[]>

// Update getListings() — omit category param entirely when value is "all" or undefined
```

**File:** `frontend/src/hooks/useInfiniteListings.ts`

- On mount: read `category` from URL params; fall back to `localStorage.getItem("rcn_category")`
  or `"all"`.
- **Fetch gate:** when `localStorage.getItem("rcn_category") === null`, do not call
  `getListings()` — wait until the user selects a category in the modal. This prevents loading
  all listings behind the modal on first visit.
- When category changes: write to URL params, reset to page 1, clear item list.

---

### Step 9 — Frontend: `CategoryModal` + header selector

**File:** `frontend/src/components/CategoryModal.tsx` (new)

```tsx
interface CategoryModalProps {
  open: boolean;
  categories: Category[];
  onSelect: (categoryKey: string) => void;  // "all" | category key
}
```

**Behaviour:**
- Full-screen overlay (same aurora dark backdrop as existing modals in `FavoritesModal.tsx`)
- Title: "Was suchst du?"
- Grid: 2 columns on mobile, 3–4 on desktop
- Each button: category label + listing count from `/api/categories`
- "Alle Kategorien" always first
- On click: `localStorage.setItem("rcn_category", key)` → `onSelect(key)` → modal closes
- No close-without-selecting on first visit; re-opening via header always closeable

**Header selector** — add to `frontend/src/components/PlzBar.tsx`:
- A clickable chip showing the active category label (or "Alle Kategorien")
- Desktop: inline in top bar; Mobile: full-width row above filter panel
- Click → open `CategoryModal`

---

### Step 10 — Frontend: wire into `App.tsx` and `ListingsPage.tsx`

**File:** `frontend/src/App.tsx`

- Fetch categories once on mount via `getCategories()`, store in state
- Pass `categories` + `onCategorySelect` down to `ListingsPage`

**File:** `frontend/src/pages/ListingsPage.tsx`

- Show `CategoryModal` when `localStorage.getItem("rcn_category") === null`
- Pass active category to `useInfiniteListings`
- Show category chip in header via `PlzBar` update

### Step 11 — Saved searches: include category

**File:** `frontend/src/hooks/useSavedSearches.ts`

When creating or updating a saved search, include `category` from the current filter state.
Pass `undefined` (not `"all"`) when no specific category is selected — the backend stores
`NULL` for "all categories".

**File:** `frontend/src/components/FavoritesModal.tsx`

Display the category label next to each saved search that has a category set.

---

## Verification

```bash
# 1. Schema
docker compose exec db psql -U rcscout -d rcscout \
  -c "\d listings" | grep category
docker compose exec db psql -U rcscout -d rcscout \
  -c "\d saved_searches" | grep category

# 2. Backfill — all existing listings should be 'flugmodelle'
docker compose exec db psql -U rcscout -d rcscout \
  -c "SELECT category, count(*) FROM listings GROUP BY category"

# 3. Backend tests pass
docker compose exec backend pytest tests/ -v

# 4. Categories endpoint returns all 7 (with correct auth cookie/token)
curl -s http://localhost:8002/api/categories | python -m json.tool

# 5. Category filter works
curl -s "http://localhost:8002/api/listings?category=flugmodelle&per_page=1" | python -m json.tool

# 6. Unknown category → 400
curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8002/api/listings?category=unknown"

# 7. Frontend: open app → category modal appears on first visit (no localStorage value)
# 8. Select category → listings load, modal closes
# 9. Reload → modal does NOT reappear
# 10. Click category chip → modal reopens, is closeable this time
# 11. Trigger scrape, watch log — phase 1 cycles through all 7 categories sequentially
```

---

## Doc Updates (after successful verification)

- `docs/definition.md`: expand scope from "Biete Flugmodelle only" to all 7 "Biete" categories
- `docs/architektur.md`: update project structure (new `CategoryModal.tsx`), API table (new
  `/api/categories` endpoint), scraping strategy (multi-category loop)

---

## Reference Patterns

- `backend/app/scraper/orchestrator.py` — existing `_phase1_new_listings()` to adapt
- `backend/app/db.py` — existing `ADD COLUMN IF NOT EXISTS` pattern in `init_db()`
- `backend/app/config.py` — existing `Settings` pattern
- `frontend/src/components/FavoritesModal.tsx` — modal style reference for `CategoryModal`
- `frontend/src/hooks/useInfiniteListings.ts` — filter/URL param pattern
