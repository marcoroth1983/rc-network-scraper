# PLAN 014 — LLM Listing Analysis, Price Correction & Price Indicator

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | pending | — |
| Human | pending | — |

## Context & Goal

RC-Network listings contain structured product data (manufacturer, model, drive type, completeness) buried in unstructured German free-text. We want to:

1. **Extract structured fields** from each listing via LLM (OpenRouter) — asynchronous background worker, decoupled from scraper
2. **Correct scraped prices** — LLM re-parses the price; if it finds a value, it overwrites `price_numeric` (the scraper has known bugs with German number formats like "VB. 4.500 Euro")
3. **Price indicator** — group listings by product and label each as Günstig / Mittel / Hoch based on price bands within its group
4. **Search filters** — expose `drive_type`, `completeness`, `model_subtype`, `shipping_available` as filter parameters in API and UI

## Breaking Changes

**No.** All new DB columns are nullable/additive. Existing API response fields are unchanged; new fields are added. No existing clients break.

## Architecture

### Model Strategy

| Use | Model | Cost | Notes |
|-----|-------|------|-------|
| Primary (ongoing) | `qwen/qwen3-30b-a3b:free` | $0 | Free tier, 200 req/day, supports structured output |
| Fallback | `mistralai/mistral-nemo` | $0.02/$0.04 per 1M | Kicks in if free model fails, ~$0.05 for full backfill |

Config in `backend/app/config.py`:
```python
OPENROUTER_API_KEY: str = ""
OPENROUTER_MODEL: str = "qwen/qwen3-30b-a3b:free"
OPENROUTER_FALLBACK_MODEL: str = "mistralai/mistral-nemo"
OPENROUTER_BATCH_MODEL: str = "google/gemini-2.5-flash-lite"  # kept for manual backfill if needed
```

### LLM Worker — Decoupled from Scraper

The DB itself is the queue: `llm_analyzed = false` means "not yet processed".

- Worker runs every **2 minutes**, picks up **3 listings** with `llm_analyzed = false`
- After processing (success or failure): sets `llm_analyzed = true`
- Scraper does not know about LLM — newly scraped listings default to `llm_analyzed = false`
- After each worker run: SQL price indicator recalculation (pure math, milliseconds)

### Price Indicator

Calculated entirely in SQL — no LLM involved. Groups listings and assigns price bands:

**Group hierarchy** (first that yields ≥ 5 listings wins):
1. `manufacturer + model_name` — most precise
2. `model_type + model_subtype + completeness` — broader fallback
3. No group found → `price_indicator = NULL` (show "Nicht genug Daten")

**Bands** (based on active non-sold listings with `price_numeric IS NOT NULL`):

| Band | Condition | Label |
|------|-----------|-------|
| `deal` | price < group median × 0.75 | Günstig |
| `fair` | within ±25% of median | Mittel |
| `expensive` | price > group median × 1.25 | Hoch |
| `NULL` | group < 5 listings | Nicht genug Daten |

## What Already Exists

The following was already implemented in prior sessions and does NOT need to be re-implemented:

- `backend/app/analysis/__init__.py`
- `backend/app/analysis/extractor.py` — `analyze_listing()` with `price_euros`, `shipping_available`, free + fallback model logic
- `backend/app/analysis/backfill.py` — manual backfill CLI
- `backend/app/config.py` — `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`, `OPENROUTER_BATCH_MODEL`
- `backend/app/scraper/orchestrator.py` — price parser bug fixed (`_parse_price_numeric`)
- `backend/requirements.txt` — `openai>=1.40` added

## Steps

### Step 1: DB & Model — Replace `analyzed_at`/`analysis_retries` with `llm_analyzed`

The old plan used `analyzed_at TIMESTAMPTZ` + `analysis_retries INTEGER`. The new design uses a single boolean flag.

**`backend/app/models.py`** — replace `analyzed_at` and `analysis_retries` with:
```python
llm_analyzed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
price_indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
shipping_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

Also verify these columns exist (added by coder agent in previous session):
`manufacturer`, `model_name`, `drive_type`, `model_type`, `model_subtype`, `completeness`, `attributes JSONB`

**`backend/app/db.py`** — in `init_db()`, replace/add migrations:
```python
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS llm_analyzed BOOLEAN NOT NULL DEFAULT false"))
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_indicator VARCHAR(20)"))
await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS shipping_available BOOLEAN"))
# Remove analyzed_at / analysis_retries if they exist (from old plan):
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS analyzed_at"))
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS analysis_retries"))
```

### Step 2: Analysis Job — background worker

**`backend/app/analysis/job.py`** — rewrite to use `llm_analyzed` flag:

```python
BATCH_SIZE = 3
DELAY_SECONDS = 3.0  # respects 20 req/min free tier limit

async def run_analysis_job() -> None:
    """Pick up to BATCH_SIZE unanalyzed listings, run LLM, update DB."""
    async with get_session_context() as session:
        rows = await session.execute(
            select(Listing)
            .where(Listing.llm_analyzed == False)
            .order_by(Listing.scraped_at.desc())
            .limit(BATCH_SIZE)
        )
        listings = rows.scalars().all()

    for listing in listings:
        result = await analyze_listing(
            title=listing.title,
            description=listing.description or "",
            price=listing.price,
            condition=listing.condition,
            category=listing.category or "",
        )
        async with get_session_context() as session:
            update_vals = {
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
            # LLM price overwrites price_numeric when available
            if result.price_euros is not None:
                update_vals["price_numeric"] = result.price_euros

            await session.execute(
                update(Listing).where(Listing.id == listing.id).values(**update_vals)
            )
            await session.commit()
        await asyncio.sleep(DELAY_SECONDS)

    if listings:
        await recalculate_price_indicators()
```

**`backend/app/analysis/job.py`** — `recalculate_price_indicators()`:

```python
async def recalculate_price_indicators() -> None:
    """Assign price bands to all analyzed listings using two-level grouping."""
    async with get_session_context() as session:
        # Level 1: manufacturer + model_name (min 5 listings)
        # Level 2: model_type + model_subtype + completeness (min 5 listings)
        # Uses median ±25% for band thresholds
        await session.execute(text("""
            WITH medians_l1 AS (
                SELECT manufacturer, model_name,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median,
                    COUNT(*) AS cnt
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
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median,
                    COUNT(*) AS cnt
                FROM listings
                WHERE price_numeric IS NOT NULL
                  AND is_sold = false
                  AND model_type IS NOT NULL
                  AND model_subtype IS NOT NULL
                  AND completeness IS NOT NULL
                GROUP BY model_type, model_subtype, completeness
                HAVING COUNT(*) >= 5
            )
            UPDATE listings SET price_indicator = CASE
                WHEN l1.median IS NOT NULL AND listings.price_numeric <= l1.median * 0.75 THEN 'deal'
                WHEN l1.median IS NOT NULL AND listings.price_numeric >= l1.median * 1.25 THEN 'expensive'
                WHEN l1.median IS NOT NULL THEN 'fair'
                WHEN l2.median IS NOT NULL AND listings.price_numeric <= l2.median * 0.75 THEN 'deal'
                WHEN l2.median IS NOT NULL AND listings.price_numeric >= l2.median * 1.25 THEN 'expensive'
                WHEN l2.median IS NOT NULL THEN 'fair'
                ELSE NULL
            END
            FROM listings AS l
            LEFT JOIN medians_l1 l1
                ON l1.manufacturer = listings.manufacturer
               AND l1.model_name = listings.model_name
            LEFT JOIN medians_l2 l2
                ON l2.model_type = listings.model_type
               AND l2.model_subtype = listings.model_subtype
               AND l2.completeness = listings.completeness
            WHERE listings.price_numeric IS NOT NULL
              AND listings.is_sold = false
        """))
        await session.commit()
```

**`backend/app/main.py`** — change analysis job schedule from every 2h to every 2min:
```python
scheduler.add_job(
    run_analysis_job,
    trigger="interval",
    minutes=2,
    id="auto_analysis",
    replace_existing=True,
)
```

### Step 3: API — expose new fields and filters

**`backend/app/api/schemas.py`** — add to `ListingSummary`:
```python
manufacturer: str | None = None
model_name: str | None = None
model_type: str | None = None
model_subtype: str | None = None
drive_type: str | None = None
completeness: str | None = None
shipping_available: bool | None = None
price_indicator: str | None = None  # "deal" | "fair" | "expensive" | null
```

Add to `ListingDetail` (same fields, already has `attributes`).

**`backend/app/api/routes.py`** — add filter params to `GET /api/listings`:
```python
drive_type: str | None = Query(default=None)
completeness: str | None = Query(default=None)
model_subtype: str | None = Query(default=None)
shipping_available: bool | None = Query(default=None)
price_indicator: str | None = Query(default=None)  # "deal" | "fair" | "expensive"
```

Apply filters in the query (only when not None):
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

### Step 4: Frontend — Filter chips + Price indicator

**`frontend/src/types/api.ts`** — add to `ListingSummary` and `ListingDetail`:
```typescript
manufacturer: string | null;
model_name: string | null;
model_type: string | null;
model_subtype: string | null;
drive_type: string | null;
completeness: string | null;
shipping_available: boolean | null;
price_indicator: 'deal' | 'fair' | 'expensive' | null;
```

**`frontend/src/hooks/useInfiniteListings.ts`** — add new filter fields:
```typescript
drive_type: string;       // "" = no filter
completeness: string;     // "" = no filter
shipping_available: string; // "" | "true" | "false"
price_indicator: string;  // "" = no filter
```

**`frontend/src/components/FilterPanel.tsx`** — add filter chips below existing filters:

- **Versand**: toggle chip "Versand möglich" (sets `shipping_available=true`)
- **Schnäppchen**: toggle chip (sets `price_indicator=deal`)
- **Antrieb**: chips for each available drive_type in current results (Elektro / Nitro / Gas)
- **Zustand**: chips for ARF / RTF / BNF / PNP / Kit

Chips only appear when at least one listing in the current category has the field populated. Use the existing chip styling pattern from the category filter.

**`frontend/src/pages/DetailPage.tsx`** — add price indicator section:

Below the price field, add:
```
PREISINDIKATOR
[🟢 Günstig] basierend auf X ähnlichen Anzeigen
```
- `deal` → green badge "Günstig"
- `fair` → yellow badge "Marktüblich"
- `expensive` → red badge "Hoch"
- `null` → grey text "Nicht genug Daten"

Also add to the metadata grid (only when field not null):
- Hersteller, Modell, Typ, Bauform, Antrieb, Vollständigkeit, Versand

## Verification

```bash
# 1. Migration
docker compose exec db psql -U rcscout -d rcscout -c "\d listings" | grep -E "llm_analyzed|price_indicator|shipping_available"

# 2. Analysis job picks up listings
docker compose exec backend python -c "
import asyncio
from app.analysis.job import run_analysis_job
asyncio.run(run_analysis_job())
"
# Check logs for: "analyzed N listings"

# 3. Price indicator recalculated
docker compose exec db psql -U rcscout -d rcscout -c \
  "SELECT price_indicator, COUNT(*) FROM listings GROUP BY price_indicator;"

# 4. API filter works
curl "http://localhost:4200/api/listings?price_indicator=deal&per_page=5"
curl "http://localhost:4200/api/listings?drive_type=electric&per_page=5"
curl "http://localhost:4200/api/listings?shipping_available=true&per_page=5"

# 5. Tests
docker compose exec backend pytest tests/ -v

# 6. Frontend build
cd frontend && npm run build
```
