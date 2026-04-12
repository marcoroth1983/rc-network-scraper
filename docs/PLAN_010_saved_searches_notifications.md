# PLAN_010 — Saved Searches & Notification Plugin System

## Context & Goal

Users want to save search criteria and get notified when new listings match.
Currently the app supports one-off browsing — there is no way to persist a
search and be alerted about new results.

This plan adds:
1. **Saved searches** — persist filter criteria (search term, PLZ, max distance,
   sort) per user
2. **Post-scrape matching** — after each scrape, check new listings against all
   saved searches
3. **Notification plugin interface** — abstract mechanism to dispatch "new matches"
   events; concrete implementations (Telegram, Firebase, etc.) come in future plans
4. **Frontend: Suchen tab** — FavoritesModal gets two tabs: "Merkliste" (existing
   favorites) and "Suchen" (saved searches), inspired by Kleinanzeigen's Favoriten UI
5. **Save search button** — floating button on the listings page to save the
   current filter state

Visual reference: Kleinanzeigen screenshots provided by the user (Favoriten →
Suchen tab, "Suche speichern" FAB on search results page).

**Hard prerequisite:** PLAN_008 must be implemented first. This plan depends on
the `users` table and `get_current_user` dependency introduced by PLAN_008.
The `saved_searches` table has a foreign key to `users.id`.

---

## Breaking Changes

**No.** New table, new endpoints, new UI elements. Nothing existing changes.

---

## Approval Table

| Approval | Status  | Date |
|----------|---------|------|
| Reviewer | approved | 2026-04-11 |
| Human    | approved | 2026-04-12 |

**Implementation gate:** Do NOT begin implementation until PLAN_008 (Google SSO
Auth) is approved, implemented, and merged to main. This plan depends on the
`users` table and `get_current_user` dependency introduced by PLAN_008.

---

## Reviewer Notes (incorporated into plan)

### Revision 1 fixes:
1. Auth dependency made explicit as hard prerequisite
2. Matcher uses `scraped_at >= scrape_start_time` instead of listing ID list
   (Phase 1 does not return IDs)
3. Added `last_viewed_at` column to separate processing cursor from read cursor
4. Query builder split into SQL predicates + Python-side distance filter
5. First-run behavior: set `last_checked_at = now()` without matching (no spam)
6. Added integration test for scraper→matcher chain
7. Step 8 split into 8a/8b/8c for agent-context granularity
8. `MatchResult.user_email` replaced with `user_id`
9. Registry singleton lives in `registry.py`, not `main.py`
10. Step ordering fixed: Step 4 (query builder) before Step 5 (matcher)

### Revision 2 fixes:
11. **`scraped_at` unreliable for "new listing" detection** — Phase 2
    (`_phase2_sold_recheck`) updates `scraped_at = now()` on every listing it
    rechecks, so old listings get fresh timestamps. Fix: Phase 1 already tracks
    `is_new` per listing (orchestrator.py line 377). Extend `_phase1_new_listings`
    to collect and return `new_ids` in its result dict. Matcher receives these IDs
    directly instead of time-based queries.
12. **Wrong file path + phantom `scrape_started_at` variable** — The scrape runner
    is at `backend/app/scrape_runner.py` (not `scraper/`). There is no
    `scrape_started_at` variable. Fixed: plan now references correct path and
    uses `new_ids` from Phase 1 result dict.
13. **`saved_search_id` URL param dropped by `writeFiltersToParams()`** — The
    function rebuilds URLSearchParams from scratch with only known filter keys,
    stripping any extra params. Fix: store active saved search ID in React state
    (lifted to App.tsx), not in URL params.
14. **Unread badge cannot sync between PlzBar and FavoritesModal** — They are
    siblings in App.tsx with no shared state. Fix: lift `useSavedSearches()` to
    App.tsx, pass state + callbacks down via props.
15. **`filter_by_distance()` return type discards distances** — The route needs
    `(listing, distance_km)` pairs for serialization and sorting. Fix: return
    `list[tuple[Listing, float]]` from the shared function.

### Revision 3 fixes:
16. **`_upsert_listing()` doesn't return DB ID** — The SQL `RETURNING` clause
    only has `(xmax = 0) AS is_insert`. Fix: change to
    `RETURNING id, (xmax = 0) AS is_insert` and update `_upsert_listing()` to
    return `tuple[bool, int]` (is_new, listing_id).
17. **Phase 1 has 3 return paths** — All three (`empty page`, `fully known page`,
    `MAX_PAGES cap`) must include `"new_ids": new_ids` in the return dict.
18. **SQL predicates vs in-memory filtering mismatch** — `build_text_filter()`
    returns SQLAlchemy `ColumnElement` clauses, which can't be applied to Python
    objects. Fix: matcher runs a SQL query `WHERE id IN (new_ids) AND <text_filter>`
    per saved search, not in-memory filtering.
19. **First-run skip no longer needed** — With `new_ids`, the matcher only sees
    genuinely new listings from the current scrape. There is no historical corpus
    risk. Remove the first-run guard.
20. **`handleResponse()` crashes on 204 No Content** — `res.json()` fails on
    empty body. Fix: `DELETE` endpoint returns 200 with `{"ok": true}` instead
    of 204, consistent with existing `toggle_sold` pattern.
21. **ListingsPage prop wiring unspecified** — `<Route element={<ListingsPage/>}>`
    passes no props. Fix: pass `savedSearchState` via Route element prop drilling
    (`<ListingsPage activeSavedSearchId={...} onSave={...} onUpdate={...} />`).

### Revision 4 fixes:
22. **PLZ auto-restore in PlzBar corrupts saved-search replay** — PlzBar's
    `useEffect` (line 27-34) auto-injects the last-used PLZ from localStorage
    when the URL has no `plz` param. If a saved search without PLZ navigates to
    `?search=Multiplex`, PlzBar silently adds PLZ → wrong results. Fix: when
    `activeSavedSearchId` is set, skip PLZ auto-restore. PlzBar receives a
    `suppressPlzRestore` prop from App.tsx (true when navigating from saved search).
23. **PLZ validation on save — invalid PLZ would crash matcher** — POST/PUT
    `/api/searches` must validate `plz` against `plz_geodata` table when PLZ is
    provided. Return 400 if PLZ not found. Additionally, matcher wraps each
    saved search in try/except for isolation — one broken search must not fail
    the entire scrape run.
24. **Cleanup fixture ordering** — Explicit DELETE order in conftest.py:
    `search_notifications` → `saved_searches` → `listings` → `plz_geodata`.
25. **PLAN_008 prerequisite status made explicit** — Added note below approval
    table that implementation must not begin until PLAN_008 is on main.
26. **`last_checked_at` description updated** — Data Model section now reflects
    that `last_checked_at` is informational only (not used for filtering).
27. **`backend/app/services/__init__.py`** — Mentioned in Step 4 as required.

### Revision 5 fixes:
28. **`suppressPlzRestore` cleared too early on route change** — DetailPage
    navigation nulls `activeSavedSearchId`, PlzBar re-injects stale PLZ. Fix:
    do NOT reset `activeSavedSearchId` on route change. Reset only on explicit
    user actions: clearing all filters, saving a new search, or clicking a
    different saved search. This keeps `suppressPlzRestore` active during
    detail-page navigation.
29. **try/except without transaction recovery** — A DB error in one saved search
    puts the SQLAlchemy session in aborted state, failing all subsequent searches.
    Fix: use `session.begin_nested()` (SAVEPOINT) per saved search. On error,
    the SAVEPOINT is rolled back without aborting the outer transaction.
30. **`filter_by_distance()` doesn't cover "display only" path** — The route has
    a path where PLZ is set but `max_distance` is None: distances are computed
    for display without filtering. Fix: make `max_distance` optional (`int | None`).
    When `None`, compute and return `(listing, distance)` pairs for ALL listings
    without filtering. When set, filter to only listings within range.
31. **Step 7 integration test: LogPlugin not registered** — Tests that call
    `check_new_matches()` need the plugin registered. Fix: test must explicitly
    register `LogPlugin` on `notification_registry` in setup, and clear after.
    Also add a test in `test_scrape_runner.py` verifying matcher is called when
    `new_ids` is non-empty.

### Revision 6 fixes:
32. **Missing `session.commit()` in matcher** — The codebase uses no autocommit.
    Without explicit commit, all `search_notifications` inserts and
    `last_checked_at` updates are rolled back when the session closes. Fix:
    `await session.commit()` after each `begin_nested()` block (per-search
    commit, so successful searches are persisted even if a later one fails).
33. **`filter_by_distance()` return type `float` vs `float | None`** — Existing
    route code uses `float | None` with `None` for no-coordinate listings
    (routes.py line 172-173). `float('inf')` is not valid JSON. Fix: return
    type is `list[tuple[Listing, float | None]]`. Listings without coordinates
    get `distance=None`, matching the established codebase pattern.

---

## Reference Patterns

- Scraper orchestrator: `backend/app/scraper/orchestrator.py` — Phase 1 tracks
  `is_new` per listing (line 377) and collects `new_count`. This plan extends it
  to also collect and return `new_ids` (list of newly inserted listing IDs).
- Scrape runner: `backend/app/scrape_runner.py` — `run_update_job()` calls
  Phase 1 within an `AsyncSessionLocal()` context (line 132). Matcher must be
  called inside this context, using the `new_ids` from Phase 1's result dict.
- Listings query: `backend/app/api/routes.py` — `GET /api/listings` has two
  execution paths: SQL-side for simple queries, Python-side for distance
  filtering (Haversine computed in Python, not SQL). Distance pairs
  `list[tuple[Listing, float]]` are needed for both serialization and sorting.
- FavoritesModal: `frontend/src/components/FavoritesModal.tsx` — will host tabs
- FilterPanel: `frontend/src/components/FilterPanel.tsx` — source of filter state
- useListings hook: `frontend/src/hooks/useListings.ts` — `writeFiltersToParams()`
  rebuilds URL params from scratch (only known filter keys). Do NOT use URL
  params for saved_search_id — use React state instead.

---

## Data Model

### `saved_searches` table

```python
class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))  # auto-generated from criteria
    search: Mapped[str | None] = mapped_column(String(255))  # text search term
    plz: Mapped[str | None] = mapped_column(String(10))
    max_distance: Mapped[int | None] = mapped_column(Integer)  # km
    sort: Mapped[str] = mapped_column(String(20), server_default="date")
    sort_dir: Mapped[str] = mapped_column(String(4), server_default="desc")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

**Cursor semantics:**
- `last_checked_at` — informational timestamp. Updated by the matcher after each
  scrape run. NOT used for filtering (the matcher uses `new_ids` from Phase 1
  instead). Useful for display ("Zuletzt geprüft: ...") and debugging.
- `last_viewed_at` — read cursor. Updated when the user views the Suchen tab
  in the frontend. Used to compute `match_count` (unread matches).

### `search_notifications` table

Tracks which matches were already notified to avoid duplicates:

```python
class SearchNotification(Base):
    __tablename__ = "search_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    saved_search_id: Mapped[int] = mapped_column(
        ForeignKey("saved_searches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("saved_search_id", "listing_id", name="uq_search_listing"),
    )
```

---

## Notification Plugin Interface

Abstract interface that future plans (Telegram, Firebase, etc.) implement.
The matching service calls `dispatch()` with match results — it doesn't know
or care how notifications are delivered.

```python
# backend/app/notifications/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MatchResult:
    """Result of matching new listings against a saved search."""
    saved_search_id: int
    search_name: str
    user_id: int
    new_listing_ids: list[int]
    new_listing_titles: list[str]
    total_new: int


class NotificationPlugin(ABC):
    """Base class for notification delivery plugins."""

    @abstractmethod
    async def is_configured(self) -> bool:
        """Return True if this plugin has all required config to send."""
        ...

    @abstractmethod
    async def send(self, match: MatchResult) -> bool:
        """Send a notification for a match result. Return True on success."""
        ...
```

```python
# backend/app/notifications/registry.py

class NotificationRegistry:
    """Registry of active notification plugins. Singleton — import from here."""

    def __init__(self) -> None:
        self._plugins: list[NotificationPlugin] = []

    def register(self, plugin: NotificationPlugin) -> None:
        self._plugins.append(plugin)

    async def dispatch(self, match: MatchResult) -> None:
        """Send match result to all configured plugins."""
        for plugin in self._plugins:
            if await plugin.is_configured():
                try:
                    await plugin.send(match)
                except Exception:
                    logger.exception("Plugin %s failed for search %s",
                                     plugin.__class__.__name__, match.search_name)

# Module-level singleton — import this, not from main.py
notification_registry = NotificationRegistry()
```

A `LogPlugin` is included as the initial (and only) implementation — it logs
matches to stdout. This validates the plugin interface works end-to-end without
requiring external services.

```python
# backend/app/notifications/log_plugin.py

class LogPlugin(NotificationPlugin):
    """Logs match results to stdout. Default plugin, always configured."""

    async def is_configured(self) -> bool:
        return True

    async def send(self, match: MatchResult) -> bool:
        logger.info(
            "🔔 %d new listings for saved search '%s': %s",
            match.total_new, match.search_name,
            ", ".join(match.new_listing_titles[:5]),
        )
        return True
```

Plugin registration happens in `backend/app/main.py` at lifespan startup.
Use a guard to prevent duplicate registration on uvicorn `--reload`:

```python
from app.notifications.registry import notification_registry
from app.notifications.log_plugin import LogPlugin

# In lifespan startup (or at module level with guard):
if not notification_registry._plugins:
    notification_registry.register(LogPlugin())
# Future: notification_registry.register(TelegramPlugin())
# Future: notification_registry.register(FirebasePlugin())
```

---

## Steps

---

### Step 1 — Data model: SavedSearch + SearchNotification [ open ]

**File:** `backend/app/models.py`

Add `SavedSearch` and `SearchNotification` models as defined in the Data Model
section above (including both `last_checked_at` and `last_viewed_at`). Both
tables are created automatically via `metadata.create_all()`.

---

### Step 2 — Notification plugin interface [ open ]

**New files:**
- `backend/app/notifications/__init__.py`
- `backend/app/notifications/base.py` — `MatchResult` dataclass (with `user_id`,
  not `user_email`) + `NotificationPlugin` ABC
- `backend/app/notifications/registry.py` — `NotificationRegistry` + module-level
  `notification_registry` singleton
- `backend/app/notifications/log_plugin.py` — `LogPlugin` (stdout logging)

**File:** `backend/app/main.py` — import `notification_registry` from
`registry.py` and register `LogPlugin` at startup.

---

### Step 3 — Saved search API endpoints [ open ]

**File:** `backend/app/api/routes.py`

Add 5 endpoints (all protected via `Depends(get_current_user)`):

```
GET    /api/searches          — list saved searches for current user
POST   /api/searches          — create saved search from filter criteria
PUT    /api/searches/{id}     — update search criteria (user refined their search)
DELETE /api/searches/{id}     — delete a saved search (returns 200 with `{"ok": true}`,
                                not 204, because `handleResponse()` in client.ts calls
                                `res.json()` which fails on empty 204 bodies)
PATCH  /api/searches/{id}?is_active=true|false — toggle is_active (query param,
                                consistent with existing `PATCH /api/listings/{id}/sold?is_sold=...`)
```

Also add:
```
POST   /api/searches/mark-viewed — set last_viewed_at = now() for all user's searches
```

**Route declaration order:** `mark-viewed` must be declared BEFORE the `{id}`
routes, otherwise FastAPI may capture "mark-viewed" as an `{id}` path parameter.

**POST body:**
```json
{
  "search": "Multiplex",
  "plz": "49356",
  "max_distance": 100,
  "sort": "date",
  "sort_dir": "desc"
}
```

The `name` field is auto-generated from the criteria:
- If `search` is set: `"«search»"` (e.g. `"Multiplex"`)
- If `search` + `plz`: `"«search» in «plz»"` (e.g. `"Multiplex in 49356"`)
- If only `plz` + `max_distance`: `"Alles in «plz» (+«max_distance»km)"`
- Fallback: `"Alle Anzeigen"`

**GET response** includes `match_count` per search: count of rows in
`search_notifications` where `notified_at > last_viewed_at` (or all rows if
`last_viewed_at` is NULL).

**PLZ validation:** POST and PUT must validate `plz` against the `plz_geodata`
table when provided. Return 400 if PLZ not found. Also validate that
`max_distance` is only accepted when `plz` is provided — a search with
`max_distance=100` but no PLZ would silently degrade to text-only matching.
This prevents invalid criteria from reaching the background matcher.

**Note:** `sort` and `sort_dir` are stored for replaying the search in the
frontend. They are NOT used by the matcher — matching only cares about
search/PLZ/distance criteria.

**Also touch:**
- `backend/app/api/schemas.py` — add Pydantic request/response models for saved
  searches (`SavedSearchCreate`, `SavedSearchResponse` with `match_count` field)
- `frontend/src/api/client.ts` — add 6 new API functions (list, create, update,
  delete, toggle, markViewed)
- `frontend/src/types/api.ts` — add `SavedSearch` and `SearchCriteria` TypeScript
  types

---

### Step 4 — Extract shared query/filter logic [ open ]

**New files:**
- `backend/app/services/__init__.py` (empty)
- `backend/app/services/listing_filter.py`

The current `GET /api/listings` in `routes.py` has two execution paths:
1. SQL-only path: when no distance filtering (no PLZ or no max_distance)
2. Python-side path: fetches all matching listings, computes Haversine distances
   in Python, filters by max_distance, sorts in Python

Extract into two reusable functions:

```python
def build_text_filter(search: str | None) -> list[ColumnElement]:
    """Return SQLAlchemy filter clauses for text search (title/description/tags).
    Returns empty list if search is None."""

async def filter_by_distance(
    listings: list[Listing],
    plz: str,
    max_distance: int | None,
    session: AsyncSession,
) -> list[tuple[Listing, float | None]]:
    """Compute Haversine distances from PLZ for each listing.
    Looks up PLZ coords from plz_geodata table.
    Returns (listing, distance_km) pairs.

    When max_distance is set: only returns listings within range.
    Listings without coordinates are excluded when max_distance is set.
    When max_distance is None: returns ALL listings with computed distances
    (for display purposes — the route shows distance on cards even without
    a max_distance filter). Listings without coordinates get distance=None
    (not inf — inf is not valid JSON). Matches existing pattern in
    routes.py lines 168-176."""
```

Update `routes.py` to use these shared functions instead of inline logic.
The route has two distance-related paths:
- PLZ + max_distance: filter and compute distances → `filter_by_distance(listings, plz, max_distance, session)`
- PLZ only (no max_distance): compute distances for display → `filter_by_distance(listings, plz, None, session)`

The search matcher (Step 5) also uses these functions but only needs the
listing IDs from the result (ignores distances).

---

### Step 5 — Post-scrape matching service [ open ]

**Depends on:** Step 4 (shared filter logic).

**New file:** `backend/app/services/search_matcher.py`

Called after Phase 1 of the scraper completes. Receives `new_ids` — the list
of newly inserted listing IDs returned by Phase 1 (see Step 5a below).

**Why `new_ids` instead of `scraped_at`?** Phase 2 (`_phase2_sold_recheck`)
updates `scraped_at = now()` on every listing it rechecks — including old
listings. A time-based query (`scraped_at >= last_checked_at`) would match
those old listings too, causing false notification spam. Phase 1 already
tracks `is_new` per listing (orchestrator.py line 377), so we extend it to
collect and return the IDs of genuinely new listings.

Logic:

1. If `new_ids` is empty: return 0 (nothing to match)
2. Get all saved searches where `is_active = true`
3. For each saved search (wrapped in `async with session.begin_nested()` +
   `try/except` — uses a SAVEPOINT so a DB error in one search is rolled back
   without aborting the outer transaction; log the error and continue):
   a. Build a SQL query: `SELECT * FROM listings WHERE id IN (:new_ids)`
      plus `build_text_filter()` clauses from Step 4. This keeps filtering
      in SQL (not in-memory) — `build_text_filter()` returns SQLAlchemy
      `ColumnElement` predicates which can only be used in SQL queries.
   b. Execute the query to get candidate listings
   c. If PLZ + max_distance set: apply `filter_by_distance()` from Step 4
      on the candidates (only the listing IDs from the tuples are needed,
      distances are ignored by the matcher)
   d. Exclude listing IDs already in `search_notifications` for this search
   e. Insert new matches into `search_notifications`
   f. Call `notification_registry.dispatch()` if matches > 0
   g. Update `last_checked_at = now()`
   h. `await session.commit()` — per-search commit after each `begin_nested()`
      block. This ensures successful searches are persisted even if a later
      search fails. The codebase uses no autocommit (see `db.py`).

**No first-run guard needed.** With `new_ids`, the matcher only ever sees
genuinely new listings from the current scrape run. There is no risk of
matching the entire historical corpus. The `last_checked_at` column is still
updated for informational purposes (knowing when the search was last checked)
but is not used for filtering.

```python
async def check_new_matches(
    session: AsyncSession,
    new_ids: list[int],
) -> int:
    """Check all active saved searches for new matches.
    Returns total number of new matches across all searches."""
```

**Step 5a — Extend Phase 1 to return `new_ids`**

**File:** `backend/app/scraper/orchestrator.py`

Two changes:

1. **Change `_UPSERT_SQL` RETURNING clause** (line 100): from
   `RETURNING (xmax = 0) AS is_insert` to
   `RETURNING id, (xmax = 0) AS is_insert`.
   Update `_upsert_listing()` (line 262) to return `tuple[bool, int]`
   (`is_new, listing_id`) instead of just `bool`. Change line 296-297:
   ```python
   row = result.fetchone()
   return (bool(row[1]), int(row[0])) if row else (False, 0)
   ```

2. **Collect `new_ids` in `_phase1_new_listings()`**: add `new_ids: list[int] = []`
   alongside `new_count` (line 313). Update the upsert call (line 366) to
   unpack `is_new, listing_id = await _upsert_listing(...)`. When `is_new` is
   True, append `listing_id` to `new_ids`.

   **All three return paths** must include `"new_ids": new_ids`:
   - Line 326 (empty page early stop)
   - Line 336 (fully known page early stop)
   - Line 400 (MAX_PAGES cap)

**Step 5b — Call matcher from scrape runner**

**File:** `backend/app/scrape_runner.py`

In `run_update_job()`, after Phase 1 completes (line 137): if
`result.get("new_ids")` is non-empty, call `check_new_matches(session, new_ids)`
inside the same `async with AsyncSessionLocal()` block. This requires moving
the matcher call inside the `async with` context (before line 138).

```python
async with AsyncSessionLocal() as session:
    result = await _phase1_new_listings(
        session,
        update_progress=lambda p: _update(phase="phase1", progress=p),
        delay=settings.SCRAPE_DELAY,
    )
    new_ids = result.get("new_ids", [])
    if new_ids:
        matches = await check_new_matches(session, new_ids)
        logger.info("Matcher found %d new matches", matches)
```

---

### Step 6 — Test: conftest + saved search API [ open ]

**File:** `backend/tests/conftest.py` — update `clean_listings` fixture to delete
in FK-safe order: `search_notifications` → `saved_searches` → `listings` →
`plz_geodata`. The current fixture (line 67-68) only deletes `listings` and
`plz_geodata`. Add the two new DELETEs before the existing ones:
```python
await db_session.execute(text("DELETE FROM search_notifications"))
await db_session.execute(text("DELETE FROM saved_searches"))
await db_session.execute(text("DELETE FROM listings"))
await db_session.execute(text("DELETE FROM plz_geodata"))
```

**New file:** `backend/tests/test_saved_searches.py`

Tests:
- POST `/api/searches` with valid criteria → 201, returns saved search with
  auto-generated name
- GET `/api/searches` → returns list for current user, includes `match_count`
- PUT `/api/searches/{id}` with updated criteria → 200, name re-generated
- DELETE `/api/searches/{id}` → 200 with `{"ok": true}`
- PATCH `/api/searches/{id}` toggle active → updated is_active
- POST `/api/searches/mark-viewed` → updates `last_viewed_at` on all searches
- POST duplicate criteria → allowed (no unique constraint on criteria)
- Auto-generated name logic for different filter combinations

---

### Step 7 — Test: search matcher [ open ]

**New file:** `backend/tests/test_search_matcher.py`

Unit tests:
- Match by search term: saved search "Multiplex" matches listing with
  "Multiplex BK Funray" in title
- Match by PLZ + distance: saved search PLZ 49356 +20km matches listing at
  PLZ 49393 (within range), does not match PLZ 80331 (out of range)
- No duplicate notifications: running matcher twice with same listings
  produces notifications only on first run
- `last_checked_at` is updated after matching
- Inactive search (`is_active=false`) is skipped
- Empty `new_ids` list → returns 0, no DB queries

Integration test:
- **Setup:** Register `LogPlugin` on `notification_registry` singleton before
  the test. Clear plugins after the test (`notification_registry._plugins.clear()`).
- Seed a saved search + listings, call `check_new_matches(session, new_ids)`
  directly, verify `search_notifications` rows are created and `LogPlugin`
  output appears in captured logs (`caplog` fixture).

Runner integration test (in `test_scrape_runner.py` or same file):
- Mock `_phase1_new_listings` to return `{"new": 2, "new_ids": [1, 2], ...}`
- Mock `check_new_matches` to record calls
- Call `run_update_job()`, verify `check_new_matches` was called with `new_ids=[1, 2]`
- Also test: when `new_ids` is empty, `check_new_matches` is NOT called

---

--- BREAK ---
Backend complete. Before frontend:
1. Run `docker compose exec backend pytest tests/ -v` — must be green
2. Create a test saved search: `POST /api/searches` with `{"search": "Multiplex"}`
3. Trigger a scrape and verify log output shows match notification

Wait for Human confirmation before proceeding to frontend steps.

---

### Step 8a — Frontend: useSavedSearches hook + App.tsx state lifting [ open ]

**File:** `frontend/src/hooks/useSavedSearches.ts`

New hook with all API functions:
```ts
export function useSavedSearches() {
  const [searches, setSearches] = useState<SavedSearch[]>([])
  const load = async () => { /* GET /api/searches */ }
  const save = async (criteria: SearchCriteria) => { /* POST /api/searches */ }
  const update = async (id: number, criteria: SearchCriteria) => { /* PUT /api/searches/{id} */ }
  const remove = async (id: number) => { /* DELETE /api/searches/{id} */ }
  const toggleActive = async (id: number) => { /* PATCH /api/searches/{id} */ }
  const markViewed = async () => { /* POST /api/searches/mark-viewed */ }
  const totalUnread: number  // sum of match_count across all ACTIVE searches only
  return { searches, totalUnread, load, save, update, remove, toggleActive, markViewed }
}
// load() is called on mount in App.tsx (to populate totalUnread for PlzBar badge)
// and again when FavoritesModal opens (to get fresh data)
```

**File:** `frontend/src/App.tsx`

**State lifting:** Call `useSavedSearches()` in `App.tsx` (or `AuthenticatedApp`
after PLAN_008), not inside FavoritesModal. This is required because both
`PlzBar` (unread badge) and `FavoritesModal` (tab content, markViewed) need
the same state. Pass the hook's return value as props:
- To `PlzBar`: `totalUnread` (for badge display)
- To `FavoritesModal`: `searches`, `load`, `remove`, `toggleActive`, `markViewed`,
  `totalUnread`
- To `ListingsPage` (via route or context): `save`, `update`

Also add `activeSavedSearchId: number | null` state in App.tsx. This replaces
the URL-param approach (see Step 9).

**File:** `frontend/src/components/FavoritesModal.tsx`

Add tab navigation to the modal:
- Two tab buttons at the top, below the title: "Merkliste" and "Suchen"
- Active tab has a bottom border accent
- Default tab: "Merkliste"
- Tab state is local (not persisted)
- "Merkliste" tab shows the existing favorites list (unchanged behavior)
- "Suchen" tab shows a placeholder for now ("Suchen werden geladen...")

---

### Step 8b — Frontend: Suchen tab content [ open ]

**File:** `frontend/src/components/FavoritesModal.tsx`

Replace the Suchen placeholder with the actual saved search list:
- Each saved search shown as a card with:
  - Name (auto-generated, e.g. "Multiplex in 49356")
  - Filter summary (PLZ, distance — as subtle secondary text)
  - Match count badge (if > 0 unread matches)
- Empty state: "Noch keine Suchen gespeichert." with hint text
- On tab switch to "Suchen": call `markViewed()` after the search list renders
  successfully (not before), to avoid clearing unread state if the load fails

---

### Step 8c — Frontend: Suchen tab interactions [ open ]

**File:** `frontend/src/components/FavoritesModal.tsx`

Add interactive behaviors to saved search cards:
- **Click card** → navigate to listings page with filters pre-applied via URL
  search params (`?search=Multiplex&plz=49356&max_distance=100`). Additionally,
  set `activeSavedSearchId` in App.tsx state (passed down as `onActivateSearch`
  callback prop). Close modal.
  **Important:** Do NOT put `saved_search_id` in the URL — `writeFiltersToParams()`
  in `useListings.ts` rebuilds params from scratch and would strip it. Use React
  state instead.
- **Active/inactive toggle** → small switch, calls `toggleActive()`; inactive
  searches shown with muted style
- **Delete button** → trash icon, confirmation prompt, calls `remove()`

---

### Step 9 — Frontend: "Suche speichern" / "Suche aktualisieren" FAB [ open ]

**File:** `frontend/src/pages/ListingsPage.tsx`

Add a floating action button (FAB) in the bottom-right corner. The button has
two modes depending on how the user arrived at the listings page:

**Mode 1: "Suche speichern" (new search)**
- Active when: user is on the main listings page with active filters (search
  term, PLZ, or max_distance is set) AND `activeSavedSearchId` is null
- On click: call `save()` (from `useSavedSearches`, passed as prop) with
  current filter state
- Visual: bookmark icon + "Suche speichern" label

**Mode 2: "Suche aktualisieren" (edit existing)**
- Active when: `activeSavedSearchId` is set (user navigated via a saved search
  card in the Suchen tab — the ID is stored in App.tsx React state, NOT in URL
  params, because `writeFiltersToParams()` would strip it)
- On click: call `update(activeSavedSearchId, ...)` with current filter state
- Visual: refresh icon + "Suche aktualisieren" label
- Only shown if the current filters differ from the saved search's criteria

**Clearing `activeSavedSearchId`:** Do NOT reset on route changes (navigating
to DetailPage and back must preserve the saved-search context). Reset only on
explicit user actions:
- User clears all filters (search + PLZ empty)
- User saves a new search (switches to a fresh context)
- User clicks a different saved search (replaces the active one)

**Prop wiring:** In `App.tsx`, pass props through the Route element:
```tsx
<Route path="/" element={
  <ListingsPage
    activeSavedSearchId={activeSavedSearchId}
    activeSavedSearchCriteria={searches.find(s => s.id === activeSavedSearchId)}
    onSaveSearch={savedSearches.save}
    onUpdateSearch={savedSearches.update}
  />
} />
```
`ListingsPage` receives these as props. It compares current filter state with
`activeSavedSearchCriteria` to decide which FAB mode to show.

**Shared behavior:**
- Position: `fixed bottom-6 right-6`, z-index above content but below modal
- Style: prominent but not obtrusive — rounded-full, brand accent background
- On success: brief visual feedback (checkmark, "Gespeichert"/"Aktualisiert")
- On mobile: icon-only (no text label)

---

### Step 10 — Frontend: Suchen badge on Favorites button [ open ]

**File:** `frontend/src/components/PlzBar.tsx`

The existing Favorites button (heart icon) gets a small badge showing the total
number of unread matches across all active saved searches. This tells the user
"there are new results for your saved searches".

- Badge: small red/accent dot or number, positioned top-right on the heart icon
- Only shown when total match count > 0
- Data source: `totalUnread` prop passed from App.tsx (computed by
  `useSavedSearches()` hook as sum of `match_count` across all ACTIVE searches).
  **Do NOT create a separate hook instance in PlzBar** — the state must be shared
  with FavoritesModal so it synchronizes when `markViewed()` is called.
- Cleared when user opens the FavoritesModal and views the Suchen tab
  (which calls `markViewed()` → `useSavedSearches` reloads → `totalUnread`
  updates → PlzBar badge disappears)

**Also in this step:** Add `suppressPlzRestore` prop to PlzBar (passed from
App.tsx, true when `activeSavedSearchId` is set). When true, the `useEffect`
that auto-restores PLZ from localStorage (PlzBar.tsx line 27-34) must be
skipped. This prevents PlzBar from injecting a stale PLZ into saved-search
replay URLs that intentionally have no PLZ.

---

## Verification

```bash
# 1. Backend tests
docker compose exec backend pytest tests/ -v

# 2. Manual: save a search
curl -s -b cookie.txt http://localhost:8002/api/searches \
  -X POST -H "Content-Type: application/json" \
  -d '{"search":"Multiplex","plz":"49356","max_distance":100}'

# 3. Manual: list saved searches (should show match_count)
curl -s -b cookie.txt http://localhost:8002/api/searches

# 4. Trigger scrape → check backend logs for match notification
docker compose logs backend --tail=20
# Look for: "new listings for saved search" in output

# 5. Manual: mark as viewed
curl -s -b cookie.txt http://localhost:8002/api/searches/mark-viewed -X POST

# 6. Frontend checks (browser at http://localhost:4200):
#    - FavoritesModal has two tabs: "Merkliste" and "Suchen"
#    - Clicking "Suchen" shows saved searches list
#    - Match count badge shows on search cards (if new matches exist)
#    - Badge on heart icon in PlzBar shows total unread count
#    - "Suche speichern" FAB appears on listings page when filters are active
#    - Clicking FAB saves the search and shows confirmation
#    - Clicking a saved search navigates to listings with those filters
#    - Modifying filters shows "Suche aktualisieren" button
#    - Delete and active toggle work
#    - Viewing Suchen tab clears the badge

# 7. Type check
cd frontend && npx tsc --noEmit

# 8. Run frontend tests
cd frontend && npx vitest run
```

---

## Future Plans (not in scope)

- **Telegram notification plugin** — implements `NotificationPlugin`, sends
  match results via Telegram Bot API
- **Firebase push notifications** — alternative plugin for mobile/PWA push
- **Notification preferences per search** — choose which plugin(s) per search
- **Email digest** — daily/weekly summary plugin
