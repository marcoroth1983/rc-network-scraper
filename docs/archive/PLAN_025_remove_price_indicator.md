# PLAN 025 — Remove Median-Based Price Indicator; Simplify Comparables Popup

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Strip the complete median/price-indicator system (DB columns, Job, API field, Filter-Chip, Badge, Telegram-Pref) and rewrite the Comparables popup as a hard-attribute filter (`category` + progressive `model_type`/`drive_type`/`wingspan`). Popup is detail-page only — card-level trigger removed. Detail page prefetches the count and shows it as a badge on the button.

**Architecture:** Complete removal, no feature flag, no backward-compat. The `/api/listings/{id}/comparables` endpoint is rewritten from similarity-scored Top-N to a SQL-only hard-filter query. `similarity.py` (similarity_score + assess_homogeneity) becomes unused and is deleted. The popup component drops match_quality/median UI and renders only `title · price · [↗ link]`. On the detail page, the hook fires on mount so the button shows `Ähnliche Inserate (N)` and is disabled when `N = 0`.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind (frontend), PostgreSQL

**Breaking Changes:** Yes. Per CLAUDE.md rule 2, no migration code is provided.
- `GET /api/listings` no longer accepts `?price_indicator=deal|fair|expensive`. Requests that include it are ignored (Pydantic rejects unknown params only when `Extra.forbid` is set — current behavior is to silently ignore, unchanged).
- `GET /api/listings/{id}/comparables` response shape changes:
  - `match_quality`, `median` removed.
  - Per-listing `similarity_score`, `is_favorite`, `condition`, `city` no longer populated (response keeps only `id`, `title`, `url`, `price`, `price_numeric`, `posted_at`). The client renders `title`, `price`, and a link button → `url`.
  - Sold + outdated listings are now INCLUDED (user wants them for price comparison).
- `ListingSummary` and `ListingDetail` lose `price_indicator`, `price_indicator_median`, `price_indicator_count`. Frontend clients reading these fields must stop.
- DB columns `listings.price_indicator`, `listings.price_indicator_median`, `listings.price_indicator_count`, `user_favorites.last_known_price_indicator` are DROPPED.
- Telegram user preference `fav_indicator` is removed from the API and UI. Existing DB rows with the preference set are ignored.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-19 |
| Human | approved | 2026-04-19 |

---

## Reference Patterns

- Migration pattern: idempotent `ALTER TABLE ... DROP COLUMN IF EXISTS` in `backend/app/db.py` (follows the existing `ADD COLUMN IF NOT EXISTS` pattern in the same file, lines 200–238)
- `backend/app/api/routes.py:306–348` — current `/comparables` endpoint (to be rewritten)
- `backend/app/analysis/similarity.py` — entire file deleted
- `backend/app/analysis/job.py` — `recalculate_price_indicators()` deleted; `run_analysis_job` retained
- `frontend/src/components/ComparablesModal.tsx` — rewritten
- `frontend/src/components/ListingCard.tsx:140–174` — PriceIndicatorBadge + ComparablesModal trigger block (removed)
- `frontend/src/pages/DetailPage.tsx:717` — ComparablesModal trigger (stays; prefetch added)
- Filter pattern for mobile: `frontend/src/components/FilterPanel.tsx` pill-button chips
- Filter pattern for desktop: `frontend/src/components/PlzBar.tsx` pill-button chips

## Test Files

- Delete: `backend/tests/test_similarity_scorer.py`, `backend/tests/test_similarity_homogeneity.py`
- Rewrite: `backend/tests/test_comparables_route.py` (completely new scenarios per the new filter logic)
- Modify: `backend/tests/test_analysis_job.py` (remove `recalculate_price_indicators`-related tests), `backend/tests/test_api.py` (remove `TestPriceIndicator` class + the `price_indicator` filter test section), `backend/tests/test_telegram_fav_sweep.py` (remove indicator-change event tests), `backend/tests/test_telegram_prefs.py` (remove `fav_indicator` coverage), `backend/tests/conftest.py` (remove price_indicator-related fixture rows), `backend/tests/test_scheduler.py` (remove `price_indicator_recalc` scheduler test), `backend/tests/test_analysis_db.py` (remove `price_indicator*` column assertions)
- Modify frontend fixtures (every file constructing `ListingSummary`/`ListingDetail` inline): `FavoriteCard.test.tsx`, `ListingCard.test.tsx`, `FavoritesModal.test.tsx`, `DetailPage.test.tsx`, `ModalRouting.test.tsx`, `TelegramPanel.test.tsx`, `ComparablesModal.test.tsx`
- Add: new `ComparablesModal` tests covering the count-only / link-button render
- Add: new `DetailPage` test covering the prefetch + disabled-when-zero behavior

---

## Step 1 — DB migration: DROP price_indicator columns [x]

**Files:**
- Modify: `backend/app/db.py`

### 1a. Append idempotent DROPs to `init_db()`

After the existing `is_outdated` backfill block (line 238), add:

```python
        # PLAN-025: remove median-based price indicator system
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator_median"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator_count"
        ))
        await conn.execute(text(
            "ALTER TABLE user_favorites DROP COLUMN IF EXISTS last_known_price_indicator"
        ))
        # Telegram notification preference for price indicator changes — also gone.
        await conn.execute(text(
            "ALTER TABLE user_notification_prefs DROP COLUMN IF EXISTS fav_indicator"
        ))
```

`IF EXISTS` makes re-runs no-ops. No backfill: dropping data is the intent.

### 1b. Verify (DEFERRED until Step 6 is done)

**Do NOT run `docker compose up --build -d` after only Step 1.** `backend/app/main.py:120–128` still executes an `UPDATE listings SET price_indicator = NULL, …` inside the startup lifespan. Running the migration before Step 6c removes that block will drop the columns and then crash the app with `UndefinedColumn` on startup.

The verification commands below belong to Step 1 logically, but are executed once Steps 1–6 are all code-complete (i.e. the migration, ORM, schemas, routes, job, and main.py are all edited):

```bash
docker compose up --build -d
docker compose exec db psql -U rcscout rcscout -c "\d listings" | grep -i price_indicator
```

Expected: no matches (empty output).

```bash
docker compose exec db psql -U rcscout rcscout -c "\d user_favorites" | grep -i price_indicator
```

Expected: no matches.

---

## Step 2 — ORM model: drop columns [x]

**Depends on:** Step 1

**Files:**
- Modify: `backend/app/models.py`

Delete lines 51–53 of `models.py`:

```python
    # DELETE these three lines:
    price_indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_indicator_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_indicator_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Search `models.py` for `last_known_price_indicator` — it is NOT on the `UserFavorite` class in `models.py` (the column exists DB-side via a manual ALTER in `db.py` but there is no ORM mapping). **Verify by grep:** `grep -n "last_known_price_indicator" backend/app/models.py` → should return 0 matches. If matches appear, delete them.

---

## Step 3 — Schemas: drop price_indicator fields + rewrite Comparables [x]

**Depends on:** Step 2

**Files:**
- Modify: `backend/app/api/schemas.py`

### 3a. `ListingSummary` (remove lines 42–44):

```python
    # DELETE:
    price_indicator: str | None = None
    price_indicator_median: float | None = None
    price_indicator_count: int | None = None
```

### 3b. `ListingDetail` (remove lines 83–85):

```python
    # DELETE:
    price_indicator: str | None = None
    price_indicator_median: float | None = None
    price_indicator_count: int | None = None
```

### 3c. Rewrite `ComparableListing` (lines 133–145):

```python
class ComparableListing(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    price: str | None = None
    price_numeric: float | None = None
    posted_at: datetime | None = None
```

Removed: `condition`, `city`, `is_favorite`, `similarity_score`. The client renders only `title`, `price`, and a link to `url`; `posted_at` is kept so the server can sort by it and the client could show it if ever needed.

### 3d. Rewrite `ComparablesResponse` (lines 148–156):

```python
class ComparablesResponse(BaseModel):
    count: int
    listings: list[ComparableListing]
```

Removed: `match_quality`, `median`. `count` is kept so the client can render the button badge without counting array length client-side.

---

## Step 4 — Rewrite `/api/listings/{id}/comparables` endpoint [x]

**Depends on:** Step 3

**Files:**
- Modify: `backend/app/api/routes.py`

### 4a. Remove similarity imports (lines 11–15 area)

Delete the import block:

```python
from app.analysis.similarity import (
    score as similarity_score,
    assess_homogeneity,
)
```

Also delete whatever `ComparableListing` kwarg helper (`_to_comparable`) and `similarity_score` usage remains below the endpoint (routes.py:351–365).

### 4b. Rewrite `get_comparables` (replaces lines 306–365)

```python
@router.get("/listings/{listing_id}/comparables", response_model=ComparablesResponse)
async def get_comparables(
    listing_id: int,
    limit: int = Query(default=30, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),  # noqa: ARG001  — gates access, return data does not depend on user
) -> ComparablesResponse:
    """Return up to N comparable listings by hard-attribute filter.

    Filter rules:
    - `category` is always required (hard).
    - `model_type`, `model_subtype`, `drive_type`, `wingspan_mm` are applied ONLY if set on
      the base listing. Candidates with NULL on a filtered attribute are tolerated (included).
    - `model_subtype` is the discriminator the user cares about (e.g. jet vs. turbine within
      `model_type='airplane'`). Matching both `model_type` and `model_subtype` keeps the
      general class coherent AND the specialised variant coherent.
    - `wingspan_mm`: ±25 % range around the base value. Stored as a digit-only string under
      `attributes.wingspan_mm` (see `backend/app/analysis/extractor.py`; parser only accepts
      integer strings in 100–10000 mm — we inherit that constraint by requiring digits).
    - If NONE of {model_type, model_subtype, drive_type, wingspan_mm} is set on the base
      → return count=0. `category` alone is too coarse for meaningful price comparison.
    - Includes sold + outdated listings (user wants full price history).

    Order: posted_at DESC (newest first). Limit: 30 (hard upper bound via Query).
    """
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    base = result.scalar_one_or_none()
    if base is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    has_type = bool(base.model_type)
    has_subtype = bool(base.model_subtype)
    has_drive = bool(base.drive_type)
    # wingspan is stored as a digit-only string inside attributes JSONB under key "wingspan_mm".
    wingspan_raw = (base.attributes or {}).get("wingspan_mm")
    base_wingspan: int | None = None
    if isinstance(wingspan_raw, str) and wingspan_raw.isdigit():
        base_wingspan = int(wingspan_raw)
    has_wingspan = base_wingspan is not None

    if not (has_type or has_subtype or has_drive or has_wingspan):
        return ComparablesResponse(count=0, listings=[])

    stmt = (
        select(Listing)
        .where(Listing.category == base.category)
        .where(Listing.id != listing_id)
        .where(Listing.price_numeric.is_not(None))
    )
    if has_type:
        stmt = stmt.where(
            (Listing.model_type == base.model_type) | (Listing.model_type.is_(None))
        )
    if has_subtype:
        stmt = stmt.where(
            (Listing.model_subtype == base.model_subtype) | (Listing.model_subtype.is_(None))
        )
    if has_drive:
        stmt = stmt.where(
            (Listing.drive_type == base.drive_type) | (Listing.drive_type.is_(None))
        )
    if has_wingspan:
        low = int(base_wingspan * 0.75)
        high = int(base_wingspan * 1.25)
        # Guard the ::int cast from non-numeric strings using CASE. PostgreSQL does NOT
        # guarantee short-circuit evaluation on OR — using OR with a regex guard risks
        # `invalid input syntax for type integer` if the planner reorders. CASE is the
        # only construct guaranteed to short-circuit. NULL BETWEEN x AND y is NULL (falsy),
        # so non-digit / absent rows fall through to the `IS NULL` branch and are tolerated.
        stmt = stmt.where(
            text(
                "(CASE WHEN attributes->>'wingspan_mm' ~ '^[0-9]+$' "
                "      THEN (attributes->>'wingspan_mm')::int "
                "      ELSE NULL END) IS NULL "
                "OR (CASE WHEN attributes->>'wingspan_mm' ~ '^[0-9]+$' "
                "         THEN (attributes->>'wingspan_mm')::int "
                "         ELSE NULL END) BETWEEN :low AND :high"
            ).bindparams(low=low, high=high)
        )

    # Count (independent of limit) — used for the badge even if user never opens the popup
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = stmt.order_by(Listing.posted_at.desc().nullslast()).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    return ComparablesResponse(
        count=total,
        listings=[
            ComparableListing(
                id=row.id,
                title=row.title,
                url=row.url,
                price=row.price,
                price_numeric=float(row.price_numeric) if row.price_numeric is not None else None,
                posted_at=row.posted_at,
            )
            for row in rows
        ],
    )
```

**Note on `sold`/`outdated`:** the rewritten query does NOT filter `is_sold` or `is_outdated`. This is intentional per the product decision — sold listings carry the most useful price data for comparison.

### 4c. Remove `price_indicator` from `list_listings`

Delete the parameter (line 139) and filter clause (lines 187–188):

```python
# DELETE:
price_indicator: str | None = Query(default=None),
# DELETE (filter clause):
if price_indicator:
    stmt = stmt.where(Listing.price_indicator == price_indicator)
```

### 4d. Imports

Ensure `from sqlalchemy import func` is present near the top of `routes.py` (it is, verify). If `from app.analysis.similarity import …` was the only import from that module, remove the import.

---

## Step 5 — Remove `recalculate_price_indicators()` from the analysis job [x]

**Depends on:** Step 2

**Files:**
- Modify: `backend/app/analysis/job.py`

Delete the entire function (body starts at line 91, ends around line 161). The file has no `__all__` export list, so nothing to prune there.

Remove the `from collections import defaultdict` import if no other code in the file uses it (grep to verify). Remove any `assess_homogeneity`, `similarity_score` imports from `app.analysis.similarity` in this file.

---

## Step 6 — main.py: remove scheduler job + startup reset [x]

**Depends on:** Step 5

**Files:**
- Modify: `backend/app/main.py`

### 6a. Remove the import (line 26)

```python
# DELETE:
from app.analysis.job import run_analysis_job, recalculate_price_indicators
```

Replace with:

```python
from app.analysis.job import run_analysis_job
```

### 6b. Remove the scheduler registration (lines 101–107)

Delete the entire `scheduler.add_job(recalculate_price_indicators, …)` block.

### 6c. Remove the startup NULL-reset block (lines 120–128 area — the `UPDATE listings SET price_indicator = NULL …` statement inside the startup event)

Delete the entire `async with session` block that resets the three columns on startup. Since the columns will be dropped (Step 1), this block would raise `UndefinedColumn` otherwise.

### 6d. Update the log line (line 211)

```python
# Before:
"scheduler started — update every 30min, recheck every 1h, "
"analysis every 2min, llm_cascade_refresh every %gh, "
"price_indicator_recalc every 15min, ebay_fetch every 30min"
# After:
"scheduler started — update every 30min, recheck every 1h, "
"analysis every 2min, llm_cascade_refresh every %gh, "
"ebay_fetch every 30min"
```

---

## Step 7 — Delete `analysis/similarity.py` [x]

**Depends on:** Step 4, Step 5

**Files:**
- Delete: `backend/app/analysis/similarity.py`

After Steps 4 + 5 there are no more importers. Verify via:

```bash
grep -rn "from app.analysis.similarity" backend/app backend/tests
```

Expected: zero matches. If any remain, fix the caller before deleting the file.

---

## Step 8 — Telegram: remove price_indicator event + preference [x]

**Depends on:** Step 2, Step 3

**Files:**
- Modify: `backend/app/telegram/fav_sweep.py`
- Modify: `backend/app/telegram/prefs.py`
- Modify: `backend/app/api/telegram.py`

### 8a. `fav_sweep.py`

In `_detect_events` (lines 34–63):
- Remove the event line (lines 60–61): `if lk_ind is not None and ind is not None and lk_ind != ind and user_prefs.fav_indicator: events.append(...)`.
- Update the tuple unpack (line 37): remove `lk_ind` and `ind` from the destructuring.

In `run_fav_status_sweep` (lines 78–140):
- SQL (lines 81–92): drop `uf.last_known_price_indicator` from the SELECT and `l.price_indicator` from the SELECT.
- The row tuple is consumed by `_detect_events`; align the position indexes (the current code uses positional access `fav[8]`, `fav[9]`, etc. for the UPDATE). **After removing two SELECT columns, the indexes shift.** Rewrite the UPDATE to dict-access via a named CTE or re-number the positional reads. Recommended: switch the SELECT to fetch a mapping and rewrite `_detect_events` + `run_fav_status_sweep` to pass a dict instead of a tuple. This is the cleanest fix.
- UPDATE statement (lines 122–139): drop `last_known_price_indicator = :ind` and the `"ind": fav[10]` binding.

### 8b. `prefs.py`

Open `backend/app/telegram/prefs.py`. Find `NotificationPrefs` (likely a dataclass or Pydantic model). Remove the `fav_indicator` field. Remove any default / validation referencing it.

**Positional-args follow-up:** `prefs.py:38` constructs the dataclass positionally — `NotificationPrefs(user_id, r[0], r[1], r[2], r[3], r[4])`. After removing `fav_indicator` (the last field), rewrite that call to drop the final `r[4]` and re-check that the SELECT column order still matches the remaining positional args. If any SELECT referenced `fav_indicator`, remove that column from the query first. Similarly check `backend/app/api/telegram.py` for any positional construction of `NotificationPrefs`.

### 8c. `api/telegram.py`

Grep for `fav_indicator` in the file. Remove from request/response schemas (Pydantic) and from the handler that writes prefs to DB.

---

## Step 9 — Frontend types [x]

**Files:**
- Modify: `frontend/src/types/api.ts`

### 9a. `ListingSummary` — remove:

```typescript
price_indicator?: 'deal' | 'fair' | 'expensive' | null;
price_indicator_median?: number | null;
price_indicator_count?: number | null;
```

### 9b. `ListingDetail` — remove the same three.

### 9c. `ListingsQueryParams` — remove `price_indicator?`.

### 9d. `ComparablesResponse` / `ComparableListing` — rewrite to match Step 3c/3d:

```typescript
export interface ComparableListing {
  id: number;
  title: string;
  url: string;
  price: string | null;
  price_numeric: number | null;
  posted_at: string | null;
}

export interface ComparablesResponse {
  count: number;
  listings: ComparableListing[];
}
```

Remove the `MatchQuality` union type (no longer used).

### 9e. Telegram prefs type

Find the prefs interface (grep `fav_indicator` in `frontend/src/types`). Remove the field.

---

## Step 10 — Frontend: useListings + client [x]

**Depends on:** Step 9

**Files:**
- Modify: `frontend/src/hooks/useListings.ts`
- Modify: `frontend/src/hooks/useInfiniteListings.ts` (if it has `price_indicator`)
- Modify: `frontend/src/api/client.ts`

### 10a. `useListings.ts`

- Remove `price_indicator` from `ListingsFilter` type.
- Remove its read in `readFiltersFromParams`.
- Remove its write in `writeFiltersToParams`.
- Remove from `getListings` call args + the dependency array.

### 10b. `useInfiniteListings.ts`

Grep — if present, same cleanup as above.

### 10c. `client.ts` in `getListings`:

```typescript
// DELETE:
if (params.price_indicator) qs.set('price_indicator', params.price_indicator);
```

---

## Step 11 — Frontend: remove filter chip + badge + card trigger [x]

**Depends on:** Step 10

**Files:**
- Modify: `frontend/src/components/FilterPanel.tsx`
- Modify: `frontend/src/components/PlzBar.tsx`
- Modify: `frontend/src/components/ListingCard.tsx`

### 11a. `FilterPanel.tsx`

Grep `price_indicator` in the file. Remove the entire "Preis-Bewertung" section (the `<div>` with the `Nur Günstige` pill button). Update `hasSecondaryFilters` to drop the `!!filter.price_indicator` term.

### 11b. `PlzBar.tsx`

Same: remove the Preis-Bewertung section and the `!!filter.price_indicator` term in `hasActiveFilterBadge`.

### 11c. `ListingCard.tsx`

- Delete the `PriceIndicatorBadge` component (lines 26–82 inclusive: `interface PriceIndicatorBadgeProps`, `BADGE_CLASSES`, `BADGE_TOUCH_STYLE`, `function PriceIndicatorBadge`).
- Delete the `ComparablesModal` import (line 7) and the `<ComparablesModal … />` render (around line 296).
- Delete the `comparablesOpen` state + handler and any `badgeRef` / comparables-open trigger code.
- Verify the card still renders: title, price, location, date, favorite star, ALT / VERKAUFT / NEU badges — nothing else.

---

## Step 12 — Frontend: ComparablesModal rewrite (data via prop) [x]

**Depends on:** Step 9

**Files:**
- Modify: `frontend/src/components/ComparablesModal.tsx`

**Architecture decision — single source of truth:** The modal no longer owns the fetch. The page (Step 13) calls `useComparables(listing.id)` once on mount and passes the full response into the modal as a `data` prop. The modal is then a dumb renderer. This eliminates the duplicate `/comparables` network call that occurred with the previous "modal fetches when opened" pattern. No React Query is introduced — plain `useState`/`useEffect` at the page level is sufficient for a single-user hobby project.

### 12a. New prop interface (replaces the old one entirely)

Remove the existing props `listingId`, `currentListingId`. Keep `anchorRef` + `onClose`. Add `data`:

```tsx
import type { ComparablesResponse } from '../types/api';

interface Props {
  data: ComparablesResponse;
  anchorRef: React.RefObject<HTMLElement>;
  onClose: () => void;
}
```

**Removed feature:** the previous "current row highlight" tied to `currentListingId` is gone. The server-side query excludes the base listing (`Listing.id != listing_id`, Step 4b), so the modal never needed to highlight a current row — the prop was passed but never used visually. Confirm by grep: if `currentListingId` is actually used to render a highlighted row, revert and keep the prop. A first-hand check of the current `ComparablesModal.tsx` before editing is required.

### 12b. Remove the internal fetch

Delete the `import { useComparables } from '../hooks/useComparables'` import and the `const { data, loading, error } = useComparables(listingId);` call. The modal receives `data` via props now; there is no local loading / error state to manage — the page owns those states (Step 13).

### 12c. Strip match_quality / median UI

Delete `buildSubtitle`, `MatchQuality` import, `medianValue` + `medianInsertIdx` logic, and the median divider `<li>` in the list.

### 12d. New row layout

Each row renders `title` (flex-1 truncate), `price` (right-aligned, fixed width), and a small external-link button to `listing.url`:

```tsx
<li className="flex items-center gap-3 px-4 py-2 border-b last:border-0 border-white/5">
  <span className="flex-1 truncate text-sm text-white/90">{listing.title}</span>
  <span className="shrink-0 text-sm tabular-nums text-white/70">
    {listing.price ?? '—'}
  </span>
  <a
    href={listing.url}
    target="_blank"
    rel="noopener noreferrer"
    className="shrink-0 p-1.5 rounded hover:bg-white/10 text-white/50 hover:text-white/90 transition"
    aria-label="Zum Inserat öffnen"
    onClick={(e) => e.stopPropagation()}
  >
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M14 3h7v7M10 14L21 3M21 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h5" />
    </svg>
  </a>
</li>
```

### 12e. Subtitle

Replace with: `{data.count} ähnliche Inserate` (no median, no match_quality wording).

### 12f. Empty state

When `data.count === 0` OR `data.listings.length === 0`: render `<p>Keine vergleichbaren Inserate.</p>`. No spinner (loading is gone — data always exists when the modal renders) and no error UI (errors surface at the page-level button, which stays disabled). If a future contributor wants loading/error in the modal, they can add it via new props; not in this plan.

### 12g. Delete the `useComparables` hook if no longer used

After Step 13 rewrites DetailPage to use a local `useState`/`useEffect` (see the next step), `useComparables` is likely orphaned. Grep for remaining importers across `frontend/src`; if zero matches, delete the file `frontend/src/hooks/useComparables.ts`. If matches remain, keep the hook intact. This is a cleanup, not a hard requirement — document via grep.

---

## Step 13 — Frontend: DetailPage prefetch + count badge [x]

**Depends on:** Step 9, Step 12

**Files:**
- Modify: `frontend/src/pages/DetailPage.tsx`

### 13a. Local data fetch on mount (no shared hook)

Inside DetailPage, once the `listing` is loaded, fire a single `/comparables` call. Use a local `useState` + `useEffect` — the old `useComparables` hook either gets reused here OR is inlined directly. Recommended: inline here to keep the page self-contained; `useComparables` will be deleted in Step 12g if no other callers.

```tsx
import { useState, useEffect } from 'react';
import { getComparables } from '../api/client';
import type { ComparablesResponse } from '../types/api';

// inside the DetailPage component body, after `listing` state:
const [comparables, setComparables] = useState<ComparablesResponse | null>(null);
const [comparablesLoading, setComparablesLoading] = useState(false);

useEffect(() => {
  if (!listing?.id) { setComparables(null); return; }
  let cancelled = false;
  setComparablesLoading(true);
  getComparables(listing.id)
    .then((res) => { if (!cancelled) { setComparables(res); setComparablesLoading(false); } })
    .catch(() => { if (!cancelled) { setComparables({ count: 0, listings: [] }); setComparablesLoading(false); } });
  return () => { cancelled = true; };
}, [listing?.id]);

const [comparablesOpen, setComparablesOpen] = useState(false);
const comparablesCount = comparables?.count ?? 0;
```

**Error fallback rationale:** On fetch failure we set `count=0` and leave the button disabled. For a single-user hobby project this is acceptable (no error toast / no retry UI), and it matches the intended UX: no data → no vergleich.

### 13b. Button rendering

Wherever the current page has the compare button (grep `ComparablesModal` in `DetailPage.tsx`):

```tsx
<button
  type="button"
  onClick={() => setComparablesOpen(true)}
  disabled={comparablesLoading || comparablesCount === 0}
  className="px-3 py-1.5 rounded-full text-sm transition bg-white/10 text-white/80 hover:bg-white/20 disabled:opacity-40 disabled:cursor-not-allowed"
>
  Ähnliche Inserate ({comparablesLoading ? '…' : comparablesCount})
</button>
```

### 13c. Modal mount (data flows in as prop)

```tsx
{comparablesOpen && comparables && (
  <ComparablesModal
    data={comparables}
    anchorRef={/* keep existing anchor pattern from the current code */}
    onClose={() => setComparablesOpen(false)}
  />
)}
```

No `listingId`, no `currentListingId` — those props are gone (Step 12a). The modal only renders what's in `data`. Result: one network call per detail-page open, modal open/close has zero network cost.

---

## Step 14 — Frontend: Telegram prefs UI cleanup [x]

**Depends on:** Step 9

**Files:**
- Modify: `frontend/src/components/TelegramPanel.tsx`

Grep `fav_indicator` in the file. Remove the toggle (checkbox/switch) + any state field that references it. Also remove the matching line in the prefs payload sent to the backend.

---

## Step 15 — Tests [x]

**Depends on:** Steps 1–14

### 15a. Delete obsolete backend tests

```bash
rm backend/tests/test_similarity_scorer.py
rm backend/tests/test_similarity_homogeneity.py
```

### 15b. `backend/tests/test_comparables_route.py` — rewrite from scratch

Delete all existing tests in the file. New scenarios (all `@pytest.mark.integration`, using `db_session` + the existing `authenticated_client` fixture — defined at `backend/tests/conftest.py:303`).

**Attribute vocabulary reminder** (`backend/app/analysis/vocabulary.py`): valid `model_type` values are `{airplane, helicopter, multicopter, glider, boat, car}`. Values like `jet`/`turbine`/`trainer` are `model_subtype`, not `model_type`. All scenarios below use domain-valid values.

1. **No discriminating attribute on base → count=0:**
   - Insert a base listing with `category='flugmodelle'`, all of `model_type`/`model_subtype`/`drive_type` NULL, `attributes={}`.
   - `GET /api/listings/{id}/comparables` → assert `count == 0`, `listings == []`.

2. **Only model_type set → candidates with same type or NULL type match:**
   - Base: `category='flugmodelle'`, `model_type='airplane'`, subtype/drive NULL, `attributes={}`.
   - Candidate A: same category + `model_type='airplane'` → match.
   - Candidate B: same category, `model_type='glider'` → NO match (different type).
   - Candidate C: same category, `model_type=NULL` → match (tolerated).
   - Candidate D: different category → NO match.
   - Assert `count == 2`, listings include A + C.

3. **model_subtype hard when set (jet vs. turbine stays strict):**
   - Base: `category='flugmodelle'`, `model_type='airplane'`, `model_subtype='jet'`.
   - Candidate A: `model_type='airplane'`, `model_subtype='jet'` → match.
   - Candidate B: `model_type='airplane'`, `model_subtype='turbine'` → NO match (different subtype).
   - Candidate C: `model_type='airplane'`, `model_subtype=NULL` → match (tolerated).
   - Assert exactly A and C in listings.

4. **wingspan_mm ±25 % + NULL tolerance:**
   - Base: `attributes={'wingspan_mm': '2000'}`, model_type/subtype/drive all NULL.
     Range: `int(2000*0.75)..int(2000*1.25)` = `1500..2500`, inclusive (`BETWEEN`).
   - Candidate wingspan_mm=`'1499'` → NO (below 1500 inclusive bound).
   - Candidate wingspan_mm=`'1500'` → YES (boundary — `BETWEEN` is inclusive).
   - Candidate wingspan_mm=`'2500'` → YES (upper boundary).
   - Candidate wingspan_mm=`'2501'` → NO.
   - Candidate with `attributes = {}` (no key) → YES (tolerated).
   - Candidate with `attributes = {'wingspan_mm': 'ca. 2000'}` → YES (regex guard on `^[0-9]+$` tolerates non-numeric → treated as NULL via the CASE expression).

5. **drive_type hard when set:**
   - Base: `model_type='airplane'`, `drive_type='electric'`, `category='flugmodelle'`.
   - Candidate drive_type='combustion', same model_type → NO.
   - Candidate drive_type=NULL, same model_type → YES (tolerated).

6. **Sold + outdated listings included (explicit):**
   - Base: `model_type='airplane'`, `category='flugmodelle'`.
   - Candidate A: same model_type, `is_sold=TRUE` → included.
   - Candidate B: same model_type, `is_outdated=TRUE` → included.
   - Assert both appear in `listings`. This locks the product decision that sold/outdated must stay visible for price comparison.

7. **Order by posted_at DESC:**
   - Two matching candidates with different `posted_at`.
   - Assert `listings[0].posted_at > listings[1].posted_at`.

8. **Limit clamped at 30:**
   - Insert 35 matching candidates.
   - Request with default limit: assert `count == 35` AND `len(listings) == 30`.
   - Request with `?limit=999`: assert **422** Unprocessable Entity (Pydantic/FastAPI rejects the out-of-range Query param; matches the `le=30` bound added in Step 4b).
   - Request with `?limit=5`: assert `len(listings) == 5`.

9. **Base listing not found:**
   - `GET /api/listings/99999/comparables` → 404.

10. **Response shape:**
    - A successful response has exactly the top-level keys `count`, `listings`. Each listing item has exactly `id`, `title`, `url`, `price`, `price_numeric`, `posted_at`.
    - No `match_quality`, `median`, `similarity_score`, `is_favorite`, `condition`, `city`.

### 15c. `backend/tests/test_analysis_job.py`

- Delete all tests that call `recalculate_price_indicators`. Retain `run_analysis_job` tests.
- Delete the import: `from app.analysis.job import recalculate_price_indicators`.

### 15d. `backend/tests/test_api.py`

- Delete the entire `TestPriceIndicator` test class.
- Delete the `test_filter_by_price_indicator_*` tests if they live in another class.

### 15e. `backend/tests/test_scheduler.py`

Delete the test that asserts `price_indicator_recalc` is in the scheduler's job list.

### 15f. `backend/tests/test_analysis_db.py`

Delete assertions referencing `price_indicator`, `price_indicator_median`, `price_indicator_count` columns.

### 15g. `backend/tests/test_telegram_fav_sweep.py`

Delete tests that exercise the `price_indicator` diff event.

### 15h. `backend/tests/test_telegram_prefs.py`

Delete coverage of `fav_indicator`.

### 15i. `backend/tests/conftest.py`

If the `_make_listing` / seed helper writes `price_indicator=...`, remove it. Verify by grep.

### 15j. Frontend fixtures

Grep `price_indicator` across `frontend/src/**/__tests__/`:
- `FavoriteCard.test.tsx`, `ListingCard.test.tsx`, `FavoritesModal.test.tsx`, `DetailPage.test.tsx`, `ModalRouting.test.tsx` — remove `price_indicator`, `price_indicator_median`, `price_indicator_count` from every inline fixture.
- `TelegramPanel.test.tsx` — remove `fav_indicator` from preference fixtures.
- `ComparablesModal.test.tsx` — rewrite in Step 15k.

### 15k. Rewrite `ComparablesModal.test.tsx`

Scenarios (no `useComparables` mock, data passed as prop):

- Renders each listing with title + price + link button.
- Renders `{count} ähnliche Inserate` subtitle.
- Link button has `target="_blank"` and `rel="noopener noreferrer"`.
- Empty `listings` + `count=0` → `Keine vergleichbaren Inserate.` message.
- Click on a row does NOT navigate (no `<Link>` wrapper — only the `<a>` on the link icon).

### 15l. New `DetailPage.test.tsx` case

- Render DetailPage with a listing whose ID has `count=7` comparables (mock `useComparables` to return `{ count: 7, listings: […] }`).
- Assert button text: `Ähnliche Inserate (7)`.
- Mock `useComparables` to return `{ count: 0, listings: [] }`.
- Assert button is `disabled` AND label is `Ähnliche Inserate (0)`.
- While loading (`comparablesLoading === true`), button is `disabled` and label is `Ähnliche Inserate (…)`.

Note: the existing `DetailPage.test.tsx` has pre-existing `useConfirm`-provider failures (documented in PLAN-024 review). Those remain out of scope — if the new test must share the render tree with broken tests, mock `useConfirm` locally in the new test case instead of fixing the global gap.

---

## Step 16 — Docs update [x]

**Depends on:** Steps 1–15

**Files:**
- Modify: `docs/architektur.md`
- Modify: `docs/definition.md`

### 16a. `architektur.md`

**Delete lines 120–138 entirely** (the `## Preisvergleich & Similarity-Ranking` section: header + scoring weights + homogeneity thresholds + scheduling paragraph). Replace with a new 3–4 line section:

```markdown
## Ähnliche Inserate (Vergleichs-Popup)

`GET /api/listings/{id}/comparables` liefert bis zu 30 Inserate gleicher Kategorie, gefiltert nach harten Attributen — `model_type`, `model_subtype`, `drive_type` (strikt, falls am Base gesetzt; Kandidaten mit NULL werden toleriert) und `wingspan_mm` ±25 % (ebenfalls NULL-tolerant). Sold + outdated Inserate werden eingeschlossen. Keine Median-/Similarity-Bewertung mehr — rein kategoriale Filterung.
```

Keep all other sections intact. Also grep the file for any lingering `price_indicator` / `median` / `similarity` references outside the deleted section and delete those standalone sentences.

### 16b. `definition.md`

Grep `price_indicator` / `Preis-Bewertung` / `Nur Günstige` / `Preisbewertung`. Remove the feature claim. Document that the "Ähnliche Inserate" popup is the remaining comparison mechanism, filtering by category + model_type + drive_type + wingspan (±25 %).

### 16c. `backlog.md`

Remove any pending items that referenced re-calibrating the price indicator — that body of work is out. If `backlog.md:7` (or any line) specifically references PLAN-020 as a follow-up item, either delete it or rewrite to: _"PLAN-020 (Similarity-Ranking + Median-Indicator) reverted by PLAN-025 — the scoring/homogeneity system was removed and replaced by hard-attribute filtering."_ This leaves a trail for future readers who wonder why the archived PLAN-020 no longer has corresponding code.

---

## Step 17 — CHANGELOG [x]

**Depends on:** Step 16

**Files:**
- Modify: `CHANGELOG.md`

Add a new `## [2.3.0] - YYYY-MM-DD` section (replace date with implementation day). Sections:

```markdown
### Removed

**Preisbewertung (Median-System) entfernt**
- Badge "Günstig / Fair / Teuer" auf Listing-Karten entfernt
- Filter-Chip "Nur Günstige" entfernt (mobile + desktop)
- DB-Spalten `price_indicator`, `price_indicator_median`, `price_indicator_count` gelöscht
- Hintergrund-Job `recalculate_price_indicators` entfernt
- Telegram-Benachrichtigung "Preisbewertung geändert" + Preference `fav_indicator` entfernt
- `similarity.py` + Homogeneity-Bewertung entfernt — wurde nur vom Preis-Job gebraucht

### Changed

**Vergleichs-Popup ("Ähnliche Inserate") vereinfacht**
- Nur noch auf der Detailseite aufrufbar, nicht mehr aus der Karten-Übersicht
- Harte Filter statt Similarity-Score: gleiche Kategorie + (falls am Inserat gesetzt) Modelltyp, Subtyp, Antrieb, Spannweite ±25 %
- Sold + Outdated Inserate werden jetzt mit angezeigt (Preisvergleich)
- Zeigt pro Treffer nur Titel + Preis + Link zur Original-Annonce
- Max. 30 Treffer, nach Datum absteigend
- Count wird beim Öffnen der Detailseite geladen und als Badge am Button angezeigt; Button ist disabled bei 0 Treffern

### Breaking

- `GET /api/listings?price_indicator=…` wird ignoriert (Param entfernt)
- `GET /api/listings/{id}/comparables` liefert neues Response-Schema (`count` + `listings[]` mit `id/title/url/price/price_numeric/posted_at`). Keine `match_quality`, `median`, `similarity_score` mehr.
- `ListingSummary` / `ListingDetail` haben `price_indicator*` nicht mehr
```

---

## Verification

```bash
# 1. Backend rebuild + schema drop
docker compose up --build -d

# 2. Verify columns gone
docker compose exec db psql -U rcscout rcscout -c "\d listings" | grep -i price_indicator
# Expected: (empty)
docker compose exec db psql -U rcscout rcscout -c "\d user_favorites" | grep -i price_indicator
# Expected: (empty)

# 3. Backend tests (all)
docker compose exec backend pytest tests/ -v
# Expected: all green. Specifically verify:
#   - test_comparables_route.py: 10 new scenarios pass
#   - No ImportError from deleted similarity.py
#   - No AttributeError on models.Listing.price_indicator

# 4. Frontend type-check (zero errors)
cd frontend && npx tsc --noEmit

# 5. Frontend tests — targeted (files this plan touches, green = clean signal)
cd frontend && npx vitest run \
  src/components/__tests__/ComparablesModal.test.tsx \
  src/pages/__tests__/DetailPage.test.tsx \
  src/components/__tests__/ListingCard.test.tsx \
  src/components/__tests__/FavoriteCard.test.tsx \
  src/components/__tests__/FavoritesModal.test.tsx \
  src/__tests__/ModalRouting.test.tsx \
  src/components/__tests__/TelegramPanel.test.tsx
# Expected: all green. The DetailPage file has pre-existing useConfirm-provider failures
# (documented in PLAN-024 review). Those must be resolved locally inside the new test case
# added by this plan (e.g. wrap in a ConfirmProvider mock), NOT globally. If the pre-existing
# failures still block the new test from running, mock useConfirm in the new test block only.

# 6. Frontend full test run (informational only — known-red files allowed)
cd frontend && npx vitest run
# Expected: no NEW failures beyond the pre-existing useConfirm/useAuth gaps. Compare failing
# file list against the baseline documented in PLAN-024 review (3 files, 14 tests).

# 7. Frontend production build
cd frontend && npm run build
# Expected: success, no type or bundling errors.

# 8. Runtime smoke (manual — read the backend logs)
docker compose logs --tail=40 backend | grep -i "price_indicator\|recalculate"
# Expected: no mentions.

# 9. Runtime smoke (UI)
#   - Open http://localhost:4200/
#   - Assert: no "Nur Günstige" chip in filter panel (mobile + desktop).
#   - Assert: no "Günstig / Fair / Teuer" badge on cards.
#   - Assert: no compare button on cards.
#   - Open any listing detail page.
#   - Assert: "Ähnliche Inserate (N)" button with the count badge.
#     N == 0 for listings without model_type/model_subtype/drive_type/wingspan_mm
#       → button disabled.
#     N > 0 otherwise → click opens popup with title + price + link button per row.
#   - Verify browser network tab: exactly one `/api/listings/{id}/comparables` call on page load;
#     no second call when the popup opens (confirms the lift-data architecture in Step 12/13).
```

---

_Plan review closed 2026-04-19: all 7 blocking + 8 non-blocking findings addressed inline. Wingspan key corrected to `wingspan_mm`, `model_subtype` added as fourth hard filter, Step 1b verification deferred to post-Step-6, Step 12/13 merged into a single lift-data-to-page architecture, `limit` clamped via `Query(ge=1, le=30)`, fixture renamed to `authenticated_client`, SQL short-circuit via `CASE`, `fav_indicator` DB column drop added, NotificationPrefs positional-args note added, boundary math corrected (1499/2501), architektur.md lines explicit, backlog.md note specified, targeted vitest command added._

---

_Code review closed 2026-04-19 (backend + frontend, cycle 1): 0 blocking, 3 medium (non-blocking, pre-existing or cosmetic), 3 low (optional cleanups), 1 security note on pre-existing `set_prefs` f-string (confirmed safe — hardcoded allowlist)._

<!-- dglabs.agent.review-frontend — 2026-04-19, cycle 1 (archived section below) -->

<!--
## Code Review (archived)

**Files Reviewed:**
- `frontend/src/types/api.ts`
- `frontend/src/api/client.ts`
- `frontend/src/hooks/useListings.ts`
- `frontend/src/components/ListingCard.tsx`
- `frontend/src/components/ComparablesModal.tsx`
- `frontend/src/components/FilterPanel.tsx`
- `frontend/src/components/PlzBar.tsx`
- `frontend/src/pages/DetailPage.tsx`
- `frontend/src/components/__tests__/ComparablesModal.test.tsx`
- `frontend/src/components/__tests__/ListingCard.test.tsx`
- `frontend/src/components/__tests__/FavoriteCard.test.tsx`
- `frontend/src/components/__tests__/FavoritesModal.test.tsx`
- `frontend/src/components/__tests__/ScrapeLog.test.tsx`
- `frontend/src/__tests__/ModalRouting.test.tsx`
- `frontend/src/pages/__tests__/DetailPage.test.tsx`

**Overall:** Approved w/ reservations

### 🔴 CRITICAL

No critical findings.

### 🟠 HIGH

No high-severity findings.

### 🟡 MEDIUM

**[M1] DetailPage: comparables `useEffect` fires before listing is fully settled** — `DetailPage.tsx:281–289`

Problem: The comparables effect depends on `listing?.id`. The `listing` state is set inside a `.then()` chain on the main fetch (line 267). This means React will re-render once when `listing` goes from `null` to the loaded value, which triggers the comparables effect. That is the correct behavior. However, if the component is unmounted before the main fetch resolves (e.g. the user navigates away quickly), the `.then()` will still call `setListing()`, causing the comparables effect to fire on a dead component. The `cancelled` flag on the main-fetch effect does not propagate to `setListing` — it only guards `setError`/`setLoading`. The state setter itself is still called, which in React 18 is harmless (setState on an unmounted component is a no-op and does not cause the "can't perform state update" warning anymore), but it means the comparables fetch will never be triggered, so `comparablesLoading` stays `true` indefinitely even though the component is gone. This is not a user-visible bug but is a minor state leak.

Fix: This is low-risk for a single-user hobby app. If desired, add a cleanup to the main `useEffect` that resets `comparables` and `comparablesLoading` on unmount by adding them to the cleanup function — but this is genuinely a no-op in React 18 so it can be left as-is without any practical consequence.

**[M2] `ComparablesModal`: two `role="dialog"` elements in the same portal** — `ComparablesModal.tsx:112–146`

Problem: The component renders both a mobile bottom-sheet AND a desktop popover simultaneously in a single portal, both with `role="dialog" aria-modal="true"`. ARIA spec requires that only one `dialog` is active at a time. Assistive technologies will present two overlapping modal dialogs to screen reader users. The mobile sheet is hidden via `sm:hidden` (Tailwind responsive class), which controls visibility via CSS `display:none` at `≥640px`. `display:none` does remove content from the accessibility tree, so in practice screen readers at desktop widths will only see the desktop dialog and vice versa — but this is a reliance on responsive CSS for a11y correctness, which is a fragile coupling.

Fix: This pattern predates PLAN-025 and is not introduced by it (pre-existing architecture). Flag as a question for the Human: is this acceptable given the single-user context? If yes, add a comment explaining the reliance on `sm:hidden` for a11y. Not a blocker for this plan.

**[M3] `DetailPage.test.tsx` Case 17: loading test does not assert button is disabled before listing loads** — `DetailPage.test.tsx:427–445`

Problem: The "while loading" test mocks `getComparables` to never resolve, then waits for the listing to appear and checks the comparables button. However, while `getComparables` is pending, `comparablesLoading` is `true` and `comparablesCount` is `0` (from the `?? 0` fallback). The `disabled` attribute is set by `comparablesLoading || comparablesCount === 0`. The test finds the button via `btns.find(b => b.textContent?.includes('Ähnliche Inserate'))` and asserts it is disabled. This works but is fragile: if the button label changes, the find breaks silently. A `getByRole('button', { name: /ähnliche inserate/i })` would be more robust.

Fix: Minor. Replace the manual `find` with `screen.getByRole('button', { name: /ähnliche inserate \(…\)/i })` for alignment with the test patterns used in the other case-17 sub-tests. Does not affect pass/fail.

### 🟢 LOW

**[L1] `ComparablesModal`: `useEffect` for `overflow:hidden` body lock also runs on desktop popover** — `ComparablesModal.tsx:39–43`

Problem: `document.body.style.overflow = 'hidden'` is set unconditionally when the modal mounts. On desktop the popover does not cover the full viewport, so locking scroll is unnecessary and prevents the user from scrolling the page while the popover is open. Pre-existing behavior — not introduced by this plan.

Fix: A future cleanup could gate the body-scroll lock on `window.innerWidth < 640`. Out of scope for this plan; flagging as a known minor UX issue.

**[L2] `ModalRouting.test.tsx`: `getComparables` not mocked** — `ModalRouting.test.tsx` entire file

Problem: The test file mocks `api/client` as a module-level vi.mock but the mock factory does not include `getComparables`. The `DetailPage` component is itself mocked (`vi.mock('../pages/DetailPage', ...)`) so the real `DetailPage` — which calls `getComparables` — is never executed. This means no missing-mock error occurs today. However, if the `DetailPage` mock is ever removed, `getComparables` calls will hit the undefined mock and silently return `undefined`, causing TypeScript errors or runtime crashes in tests.

Fix: Add `getComparables: vi.fn().mockResolvedValue({ count: 0, listings: [] })` to the `ModalRouting.test.tsx` vi.mock factory for completeness. Non-blocking.

**[L3] `ComparablesModal`: `anchorRef` type is `React.RefObject<HTMLElement | null>` but DetailPage passes `useRef<HTMLButtonElement>` which produces `RefObject<HTMLButtonElement | null>`** — `ComparablesModal.tsx:7`, `DetailPage.tsx:257`

Problem: `useRef<HTMLButtonElement>(null)` produces `RefObject<HTMLButtonElement | null>`. The prop type on the modal is `React.RefObject<HTMLElement | null>`. Since `HTMLButtonElement extends HTMLElement`, this is a covariant assignment and TypeScript accepts it without error (confirmed by `tsc --noEmit` passing). No runtime issue. The inconsistency is cosmetic.

Fix: None required. The type is correct. Noting for completeness.

### Architecture Observations

**Lift-data pattern is correct and well-executed.** The single `getComparables` call in `DetailPage` on mount (Step 13), with the modal as a pure renderer (Step 12), eliminates the double-fetch that existed previously. The `cancelled` flag pattern matches the existing codebase conventions.

**`useComparables.ts` confirmed deleted.** Glob search returns no file. Zero residual references to `price_indicator`, `fav_indicator`, `useComparables`, `PriceIndicatorBadge`, or `MatchQuality` anywhere in `frontend/src/**/*.{ts,tsx}`.

**Step 9 types fully compliant.** `ListingSummary`, `ListingDetail`, and `ListingsQueryParams` in `types/api.ts` contain no `price_indicator*` fields. `ComparableListing` and `ComparablesResponse` match the Step 3c/3d schema exactly. `NotificationPrefs` has no `fav_indicator`.

**Test coverage for the 5 plan-specified ComparablesModal scenarios** — all present in `ComparablesModal.test.tsx`: titles/prices rendered, count subtitle, link attributes, empty state, no row-level navigation links.

**Test coverage for the 3 plan-specified DetailPage comparables scenarios** — all present as case 17 sub-tests: count=7 button enabled, count=0 button disabled, loading state shows `…` and is disabled.

**Pre-existing Case 16 failure (`lg:grid-cols-12`)** is confirmed pre-existing (the `DetailPage` component has no 12-column grid wrapper in its current implementation). This is not introduced by PLAN-025 and matches the reported 1 pre-existing failure.

### Verdict

No blocking issues. M1 is a benign React 18 no-op, M2 is pre-existing architecture. M3 and L1–L3 are optional cleanups. Implementation is approved to proceed to Step 16 (Docs update).
-->

---

## Out of scope (do NOT do in this plan)

- React Query introduction (ad-hoc `useState` + `useEffect` is fine for a single user / hobby project).
- Fixing the pre-existing `useConfirm`-provider and `useAuth`-mock gaps in `DetailPage.test.tsx` / `ScrapeLog.test.tsx` / `ModalRouting.test.tsx`. Those were flagged in PLAN-024 and remain out of scope.
- Rethinking the similarity algorithm. The user explicitly wants hard filters; there will be no re-introduction of scoring.
- Re-adding a price-indicator feature later. If the user ever changes their mind, a new plan can reintroduce the columns — but this plan's goal is full removal, not a soft-deprecate.
