# PLAN 014 — LLM Listing Analysis, Price Correction & Price Indicator

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-14 |
| Human | approved | 2026-04-14 |

## Context & Goal

RC-Network listings contain structured product data buried in unstructured German free-text. We want to:

1. **Extract structured fields** via LLM (OpenRouter) — decoupled background worker
2. **Correct scraped prices** — LLM re-parses the price; overwrites `price_numeric` when found
3. **Price indicator** — label listings as `deal` / `fair` / `expensive` (stored in DB, computed by SQL job)
4. **Search filters** — expose `drive_type`, `completeness`, `model_subtype`, `shipping_available`, `price_indicator` as filter params

## Breaking Changes

**Yes (minor).** `analyzed_at` and `analysis_retries` columns are dropped from `listings`. All nullable-additive new columns. No existing API clients break — only the `price_indicator` value name changes from `"bargain"` (old on-the-fly) to `"deal"` (new DB-stored).

## What Already Exists (do NOT re-implement)

- `backend/app/analysis/__init__.py`, `extractor.py` — complete, no changes needed
- `backend/app/config.py` — OpenRouter config already present
- `backend/requirements.txt` — `openai>=1.40` present
- `backend/app/models.py` — `manufacturer`, `model_name`, `drive_type`, `model_type`, `model_subtype`, `completeness`, `attributes` already present
- `backend/app/api/schemas.py` — `ListingSummary` and `ListingDetail` already have `manufacturer`, `model_name`, `model_type`, `model_subtype`; `ListingDetail` has `drive_type`, `completeness`, `attributes`
- `frontend/src/types/api.ts` — corresponding TypeScript types already present
- `frontend/src/pages/DetailPage.tsx` — LLM field grid (Antrieb, Vollständigkeit) already rendered

## Reviewer Notes

Fixes incorporated from review:
1. `bargain` → `deal` naming (routes.py line 140, api.ts, DetailPage.tsx) — plan wins
2. `analyzed_at`/`analysis_retries` → `llm_analyzed` migration explicitly listed for db.py + models.py
3. `get_session_context` doesn't exist — use `AsyncSessionLocal()` directly (already how job.py works)
4. `llm_analyzed = true` on failure is intentional (avoids infinite retry loops against a flaky free tier)
5. SQL `recalculate_price_indicators()` rewritten with CTE approach to fix cross-join bug
6. `backfill.py` impact listed explicitly
7. `price_indicator_median` / `price_indicator_sample` removed from schemas and types (not in plan spec)
8. On-the-fly price indicator helpers (`_compute_price_indicators`, `_apply_price_indicator`) removed from routes.py — replaced by DB column read

---

## Steps

### Step 1 — DB & Model `[open]`

**File: `backend/app/models.py`**

Replace `analyzed_at` and `analysis_retries` with:
```python
llm_analyzed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
price_indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
shipping_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

Also add `drive_type`, `completeness`, `shipping_available` to `ListingSummary` in `schemas.py` (they're missing there; `ListingDetail` already has them):
```python
drive_type: str | None = None
completeness: str | None = None
shipping_available: bool | None = None
```

Also remove `price_indicator_median: float | None = None` and `price_indicator_sample: int | None = None` from both `ListingSummary` and `ListingDetail` in `schemas.py`.

**File: `backend/app/db.py`**

In `init_db()`, add after existing migration lines:
```python
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS llm_analyzed BOOLEAN NOT NULL DEFAULT false"))
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_indicator VARCHAR(20)"))
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS shipping_available BOOLEAN"))
# Remove old columns (idempotent)
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS analyzed_at"))
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS analysis_retries"))
```

Also remove these lines from `init_db()` (they add columns that no longer exist in the model):
```python
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMPTZ"))
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS analysis_retries INTEGER NOT NULL DEFAULT 0"))
```

---

### Step 2 — Rewrite `job.py` `[open]`

**File: `backend/app/analysis/job.py`**

Complete rewrite:

```python
"""Scheduled analysis job: extract structured product data from unanalyzed listings."""

import asyncio
import logging

from sqlalchemy import select, text, update

from app.analysis.extractor import analyze_listing
from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Listing

logger = logging.getLogger(__name__)

BATCH_SIZE = 3
DELAY_SECONDS = 3.0  # respects ~20 req/min free tier limit


async def run_analysis_job() -> None:
    """Pick up to BATCH_SIZE unanalyzed listings, run LLM, update DB."""
    if not settings.OPENROUTER_API_KEY:
        logger.info("Analysis job: OPENROUTER_API_KEY not set — skipping")
        return

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Listing)
            .where(Listing.llm_analyzed == False)  # noqa: E712
            .order_by(Listing.scraped_at.desc())
            .limit(BATCH_SIZE)
        )
        listings = rows.scalars().all()

    if not listings:
        logger.info("Analysis job: no unanalyzed listings")
        return

    logger.info("Analysis job: processing %d listings", len(listings))

    for listing in listings:
        result = await analyze_listing(
            title=listing.title,
            description=listing.description or "",
            price=listing.price,
            condition=listing.condition,
            category=listing.category or "",
        )
        update_vals: dict = {
            "llm_analyzed": True,
            "manufacturer": result.manufacturer,
            "model_name": result.model_name,
            "drive_type": result.drive_type,
            "model_type": result.model_type,
            "model_subtype": result.model_subtype,
            "completeness": result.completeness,
            "attributes": result.attributes,
            "shipping_available": result.shipping_available,
        }
        if result.price_euros is not None:
            update_vals["price_numeric"] = result.price_euros

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Listing).where(Listing.id == listing.id).values(**update_vals)
            )
            await session.commit()

        await asyncio.sleep(DELAY_SECONDS)

    if listings:
        await recalculate_price_indicators()
        logger.info("Analysis job: price indicators recalculated")


async def recalculate_price_indicators() -> None:
    """Assign price bands to active non-sold listings using two-level grouping.

    Level 1: manufacturer + model_name (min 5 listings)
    Level 2: model_type + model_subtype + completeness (min 5 listings)
    Bands: deal < median*0.75 <= fair <= median*1.25 < expensive
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            WITH medians_l1 AS (
                SELECT manufacturer, model_name,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median
                FROM listings
                WHERE price_numeric IS NOT NULL
                  AND is_sold = false
                  AND manufacturer IS NOT NULL
                  AND model_name IS NOT NULL
                GROUP BY manufacturer, model_name
                HAVING COUNT(*) >= 5
            ),
            medians_l2 AS (
                SELECT model_type, model_subtype, completeness,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median
                FROM listings
                WHERE price_numeric IS NOT NULL
                  AND is_sold = false
                  AND model_type IS NOT NULL
                  AND model_subtype IS NOT NULL
                  AND completeness IS NOT NULL
                GROUP BY model_type, model_subtype, completeness
                HAVING COUNT(*) >= 5
            ),
            new_indicators AS (
                SELECT
                    l.id,
                    CASE
                        WHEN m1.median IS NOT NULL AND l.price_numeric <= m1.median * 0.75 THEN 'deal'
                        WHEN m1.median IS NOT NULL AND l.price_numeric >= m1.median * 1.25 THEN 'expensive'
                        WHEN m1.median IS NOT NULL THEN 'fair'
                        WHEN m2.median IS NOT NULL AND l.price_numeric <= m2.median * 0.75 THEN 'deal'
                        WHEN m2.median IS NOT NULL AND l.price_numeric >= m2.median * 1.25 THEN 'expensive'
                        WHEN m2.median IS NOT NULL THEN 'fair'
                        ELSE NULL
                    END AS indicator
                FROM listings l
                LEFT JOIN medians_l1 m1
                    ON m1.manufacturer = l.manufacturer AND m1.model_name = l.model_name
                LEFT JOIN medians_l2 m2
                    ON m2.model_type = l.model_type
                   AND m2.model_subtype = l.model_subtype
                   AND m2.completeness = l.completeness
                WHERE l.price_numeric IS NOT NULL AND l.is_sold = false
            )
            UPDATE listings
            SET price_indicator = ni.indicator
            FROM new_indicators ni
            WHERE listings.id = ni.id
        """))
        await session.commit()
```

---

### Step 3 — API: Filter params + schema cleanup `[open]`

**File: `backend/app/api/routes.py`**

1. **Remove** the on-the-fly price indicator helpers entirely:
   - Delete `_MIN_SAMPLE_SIZE`, `_compute_price_indicators()`, `_apply_price_indicator()`
   - Remove all calls to these functions in `list_listings`, `get_listing`, `get_listings_by_author`, `get_favorites`

2. **Add** filter params to `list_listings` (`GET /api/listings`):
```python
drive_type: str | None = Query(default=None)
completeness: str | None = Query(default=None)
model_subtype: str | None = Query(default=None)
shipping_available: bool | None = Query(default=None)
price_indicator: str | None = Query(default=None)
```

3. **Apply** filters in the query (only when not None):
```python
if drive_type:
    stmt = stmt.where(Listing.drive_type == drive_type)
if completeness:
    stmt = stmt.where(Listing.completeness == completeness)
if model_subtype:
    stmt = stmt.where(Listing.model_subtype == model_subtype)
if shipping_available is not None:
    stmt = stmt.where(Listing.shipping_available == shipping_available)
if price_indicator:
    stmt = stmt.where(Listing.price_indicator == price_indicator)
```

4. `price_indicator` is now a DB column and flows through `model_validate(from_attributes=True)` automatically — no manual injection needed.

---

### Step 4 — Frontend `[open]`

**File: `frontend/src/types/api.ts`**

1. Change `price_indicator: 'bargain' | 'fair' | 'expensive' | null` → `'deal' | 'fair' | 'expensive' | null` in both `ListingSummary` and `ListingDetail`.
2. Remove `price_indicator_median: number | null` and `price_indicator_sample: number | null` from both interfaces.
3. Add to `ListingSummary` (missing there, already in `ListingDetail`):
```typescript
drive_type: string | null;
completeness: string | null;
shipping_available: boolean | null;
```

**File: `frontend/src/pages/DetailPage.tsx`**

1. Change `type PriceIndicator = 'bargain' | 'fair' | 'expensive' | null` → `'deal' | 'fair' | 'expensive' | null`
2. Change `if (indicator === 'bargain')` → `if (indicator === 'deal')`
3. Remove the `price_indicator_median`/`price_indicator_sample` display block (the `Ø X€ bei Y Verkäufen` line).

**File: `frontend/src/hooks/useInfiniteListings.ts`**

Read the file first. Find the `ListingsFilter` type (likely in `useListings.ts` — check both). Add new filter fields:
```typescript
drive_type?: string;
completeness?: string;
shipping_available?: boolean;
price_indicator?: string;
```

Update the query params construction to include these fields (only when truthy/non-null).

**File: `frontend/src/components/FilterPanel.tsx`**

Add filter chip sections after the existing price range filter. Inside the filter modal (bottom sheet) and the desktop popover (if it exists — check `App.tsx` or `FilterBar.tsx`):

```tsx
{/* Versand */}
<div>
  <div className={sectionLabel} style={sectionLabelColor}>Versand</div>
  <button
    className={`px-3 py-1.5 rounded-full text-sm transition ${
      filter.shipping_available === true
        ? 'bg-aurora-indigo text-white'
        : 'bg-white/10 text-white/70 hover:bg-white/20'
    }`}
    onClick={() => onChange({
      ...filter,
      shipping_available: filter.shipping_available === true ? undefined : true,
    })}
  >
    Versand möglich
  </button>
</div>

{/* Schnäppchen */}
<div>
  <div className={sectionLabel} style={sectionLabelColor}>Preis</div>
  <button
    className={`px-3 py-1.5 rounded-full text-sm transition ${
      filter.price_indicator === 'deal'
        ? 'bg-aurora-indigo text-white'
        : 'bg-white/10 text-white/70 hover:bg-white/20'
    }`}
    onClick={() => onChange({
      ...filter,
      price_indicator: filter.price_indicator === 'deal' ? undefined : 'deal',
    })}
  >
    Nur Schnäppchen
  </button>
</div>
```

Also update `hasSecondaryFilters` to include `!!filter.shipping_available || !!filter.price_indicator`.

**File: `frontend/src/api/client.ts`** (or wherever query params are built for `GET /api/listings`)

Add the new filter fields to the query params. Read the file first to understand the pattern.

---

### Step 5 — Scheduler `[open]`

**File: `backend/app/main.py`**

Change analysis job interval from `hours=2` to `minutes=2`:
```python
scheduler.add_job(
    run_analysis_job,
    trigger="interval",
    minutes=2,
    id="auto_analysis",
    replace_existing=True,
)
```

Update the log message accordingly.

---

### Step 6 — Update `backfill.py` `[open]`

**File: `backend/app/analysis/backfill.py`**

1. Replace `WHERE analyzed_at IS NULL AND analysis_retries < :max_retries` with `WHERE llm_analyzed = false`
2. Replace `COUNT` query accordingly
3. In `_save_analysis`: replace `analyzed_at = :analyzed_at, analysis_retries = 0` with `llm_analyzed = true`; add `shipping_available = :shipping_available`
4. In `_increment_retries`: replace with `llm_analyzed = true` (mark as done, no retry)
5. Remove `_MAX_RETRIES` constant

---

## Verification

```bash
# 1. Migration: new columns exist, old gone
docker compose exec db psql -U rcscout -d rcscout -c "\d listings" | grep -E "llm_analyzed|price_indicator|shipping_available|analyzed_at|analysis_retries"
# Expected: llm_analyzed, price_indicator, shipping_available present; analyzed_at/analysis_retries absent

# 2. Backend tests
docker compose exec backend pytest tests/ -v

# 3. API filter works (requires auth token in real use — just check route is reachable)
docker compose exec backend python -c "
import asyncio
from app.analysis.job import recalculate_price_indicators
asyncio.run(recalculate_price_indicators())
print('recalculate done')
"

# 4. Frontend build
cd frontend && npm run build
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/models.py` | Replace `analyzed_at`/`analysis_retries` with `llm_analyzed`, `price_indicator`, `shipping_available` |
| `backend/app/db.py` | Remove old ADD COLUMN lines, add new migration lines, DROP old columns |
| `backend/app/api/schemas.py` | Remove `price_indicator_median`/`price_indicator_sample`; add `drive_type`, `completeness`, `shipping_available` to `ListingSummary` |
| `backend/app/analysis/job.py` | Complete rewrite (llm_analyzed flag, batch=3, recalculate_price_indicators with fixed CTE SQL) |
| `backend/app/analysis/backfill.py` | Update to use `llm_analyzed` flag |
| `backend/app/api/routes.py` | Remove on-the-fly helpers; add 5 new filter params |
| `backend/app/main.py` | Change analysis job to `minutes=2` |
| `frontend/src/types/api.ts` | `bargain`→`deal`, remove `_median`/`_sample`, add missing ListingSummary fields |
| `frontend/src/pages/DetailPage.tsx` | `bargain`→`deal`, remove `_median`/`_sample` display block |
| `frontend/src/hooks/useInfiniteListings.ts` | Add new filter fields |
| `frontend/src/components/FilterPanel.tsx` | Add Versand + Schnäppchen filter chips |
| `frontend/src/api/client.ts` | Pass new filter params to API |
