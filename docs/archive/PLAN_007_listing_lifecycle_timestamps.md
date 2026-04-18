# PLAN 007 — Listing Lifecycle Timestamps

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-18 |
| Human | approved | 2026-04-18 |

## Context & Goal

When debugging why a listing wasn't updated or marked as sold, the only available timestamp is `scraped_at` — which gets overwritten on every phase 2 check. It's impossible to tell when a listing was first seen or when its sold status changed.

Add two new DB columns for full lifecycle visibility:

- `created_at` — when the listing was first inserted into the DB (never overwritten)
- `sold_at` — when `is_sold` first flipped to TRUE (NULL if never sold)

No frontend changes. Internal debugging via direct DB queries only.

## Breaking Changes

**No.** Additive DB changes only — new nullable/defaulted columns. Existing data gets sensible backfill.

## Design Decisions

**Reactivation behaviour (`is_sold` flips back to FALSE):** `sold_at` is retained even if a listing is manually un-marked as sold. It records "when it was first seen as sold", not "is it currently sold". This is intentional — useful for debugging, harmless for the single-user context.

## Steps

### Step 1 — ORM model

In `backend/app/models.py`, add two columns to `Listing`:

```python
from sqlalchemy import func

created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), nullable=False, server_default=func.now()
)
sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### Step 2 — `init_db()` migration

In `backend/app/db.py`, append to the idempotent block in `init_db()` (after the last existing `ALTER TABLE` statement):

```python
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
))
# One-time backfill: only runs when created_at was just added (default = now() would be wrong
# for existing rows). Guard: only update rows where created_at is newer than scraped_at,
# which can only happen for rows that just received the column default.
await conn.execute(text(
    "UPDATE listings SET created_at = scraped_at WHERE created_at > scraped_at"
))
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sold_at TIMESTAMPTZ"
))
```

**Why this is idempotent:** `ADD COLUMN IF NOT EXISTS` is a no-op if the column exists. The `UPDATE` guard `WHERE created_at > scraped_at` can only match rows where `created_at` was just stamped with `now()` by the ADD COLUMN default and is therefore newer than `scraped_at`. On subsequent startups, all existing rows have `created_at <= scraped_at`, so the UPDATE matches nothing. New rows inserted after the migration get `created_at` set explicitly (Step 3), so they also won't match.

### Step 3 — Orchestrator: set `created_at` on INSERT only

In `backend/app/scraper/orchestrator.py`, update `_UPSERT_SQL`:

1. Add `created_at` to the INSERT column list and VALUES
2. In the ON CONFLICT UPDATE SET block, **omit `created_at`** — it must never be overwritten
3. Add `sold_at` with a CASE guard — only set when `is_sold` flips to TRUE for the first time:

```sql
INSERT INTO listings (
    external_id, url, title, price, price_numeric, condition, shipping,
    description, images, tags, author, posted_at, posted_at_raw,
    plz, city, latitude, longitude, scraped_at, is_sold, category, created_at
) VALUES (
    :external_id, :url, :title, :price, :price_numeric, :condition, :shipping,
    :description, :images, :tags, :author, :posted_at, :posted_at_raw,
    :plz, :city, :latitude, :longitude, :scraped_at, :is_sold, :category, :created_at
)
ON CONFLICT (external_id) DO UPDATE SET
    url           = EXCLUDED.url,
    title         = EXCLUDED.title,
    price         = EXCLUDED.price,
    price_numeric = EXCLUDED.price_numeric,
    condition     = EXCLUDED.condition,
    shipping      = EXCLUDED.shipping,
    description   = EXCLUDED.description,
    images        = EXCLUDED.images,
    tags          = EXCLUDED.tags,
    author        = EXCLUDED.author,
    posted_at     = EXCLUDED.posted_at,
    posted_at_raw = EXCLUDED.posted_at_raw,
    plz           = EXCLUDED.plz,
    city          = EXCLUDED.city,
    latitude      = EXCLUDED.latitude,
    longitude     = EXCLUDED.longitude,
    scraped_at    = EXCLUDED.scraped_at,
    is_sold       = EXCLUDED.is_sold OR listings.is_sold,
    sold_at       = CASE
                      WHEN (EXCLUDED.is_sold OR listings.is_sold) AND listings.sold_at IS NULL
                      THEN EXCLUDED.scraped_at
                      ELSE listings.sold_at
                    END,
    category      = EXCLUDED.category
    -- created_at intentionally omitted — never overwritten on conflict
RETURNING id, (xmax = 0) AS is_insert
```

Pass `created_at=now` in the params dict (alongside `scraped_at`). Both now and scraped_at carry the same timestamp per run.

### Step 4 — Orchestrator Phase 2: set `sold_at` when marking sold

Two places in `_phase2_sold_recheck` set `is_sold = TRUE`. Both need `sold_at`:

**Path A — HTTP 403/404/410** (currently: `UPDATE listings SET is_sold = TRUE, scraped_at = :now WHERE id = :id`):
```sql
UPDATE listings
SET is_sold = TRUE,
    sold_at = CASE WHEN sold_at IS NULL THEN :now ELSE sold_at END,
    scraped_at = :now
WHERE id = :id
```

**Path B — Parser detects sold** (currently: `UPDATE listings SET is_sold = :is_sold, scraped_at = :now WHERE id = :id`):
```sql
UPDATE listings
SET is_sold = :is_sold,
    sold_at = CASE WHEN :is_sold AND sold_at IS NULL THEN :now ELSE sold_at END,
    scraped_at = :now
WHERE id = :id
```

The `CASE` guard in both paths ensures `sold_at` is only written once (the first time `is_sold` becomes TRUE). If `is_sold` reverts to FALSE (Path B), `sold_at` is retained (see Design Decisions above).

### Step 5 — Manual PATCH endpoint

In `backend/app/api/routes.py`, update `toggle_sold` to set `sold_at` when `is_sold` is set to TRUE:

```python
sold_at_expr = func.now() if is_sold else None  # retain existing value; see note
result = await session.execute(
    update(Listing)
    .where(Listing.id == listing_id)
    .values(
        is_sold=is_sold,
        sold_at=case(
            (and_(is_sold, Listing.sold_at == None), func.now()),
            else_=Listing.sold_at,
        ),
    )
    .returning(Listing.id)
)
```

Alternatively, use raw SQL for consistency with the orchestrator:
```python
result = await session.execute(
    text("""
        UPDATE listings
        SET is_sold = :is_sold,
            sold_at = CASE WHEN :is_sold AND sold_at IS NULL THEN now() ELSE sold_at END
        WHERE id = :id
        RETURNING id
    """),
    {"is_sold": is_sold, "id": listing_id},
)
```

Use the raw SQL approach — it matches the orchestrator style exactly.

### Step 6 — Tests

**Test file:** `backend/tests/test_orchestrator_phases.py`

Add/update tests:

1. **`created_at` set on insert, never overwritten on upsert conflict:**
   - Insert a listing via Phase 1 upsert, capture `created_at`
   - Re-upsert same `external_id` with different title — assert `created_at` unchanged

2. **Phase 1 upsert sets `sold_at` when is_sold flips TRUE:**
   - Pre-insert a non-sold listing
   - Re-upsert with `is_sold=True` — assert `sold_at IS NOT NULL`

3. **Phase 2 Path A (403/404) sets `sold_at`:**
   - Pre-insert non-sold listing, mock HTTP 404 response
   - Run phase 2 — assert `is_sold=True` and `sold_at IS NOT NULL`

4. **Phase 2 Path A idempotent: existing `sold_at` not overwritten:**
   - Pre-insert listing with `is_sold=True, sold_at=<past_time>`
   - Run phase 2 with 404 — assert `sold_at` unchanged

5. **Phase 2 Path B (parser) sets `sold_at`:**
   - Pre-insert non-sold listing, mock response with "verkauft" in title
   - Run phase 2 — assert `sold_at IS NOT NULL`

6. **Reactivation: `sold_at` retained when is_sold flips back to FALSE:**
   - Pre-insert listing with `is_sold=True, sold_at=<past_time>`
   - Run phase 2 with non-sold page — assert `sold_at` still set, `is_sold=False`

Also add a test for the PATCH endpoint in `backend/tests/test_routes.py` (or equivalent):
7. **PATCH /listings/{id}/sold?is_sold=true sets `sold_at`**
8. **PATCH twice: second call does not overwrite `sold_at`**

## Reference Patterns

- `backend/app/db.py` — `init_db()` idempotent ALTER TABLE pattern (lines 26–50)
- `backend/app/scraper/orchestrator.py` — `_UPSERT_SQL` (line 72), Phase 2 update statements (~488, ~523)
- `backend/app/api/routes.py` — `toggle_sold` endpoint (line 378)
- `backend/tests/test_orchestrator_phases.py` — existing phase test structure

## Verification

```bash
# Apply migration (restart triggers init_db)
docker compose up --build -d

# Verify columns exist
docker compose exec db psql -U postgres rcn_scraper -c "\d listings" | grep -E "created_at|sold_at"

# Verify backfill: no row should have created_at IS NULL
docker compose exec db psql -U postgres rcn_scraper -c \
  "SELECT COUNT(*) FROM listings WHERE created_at IS NULL"
# Expected: 0

# Verify idempotency: created_at must be <= scraped_at for all existing rows
docker compose exec db psql -U postgres rcn_scraper -c \
  "SELECT COUNT(*) FROM listings WHERE created_at > scraped_at"
# Expected: 0

# Run tests
docker compose exec backend pytest tests/test_orchestrator_phases.py -v

# Spot-check a real listing
docker compose exec db psql -U postgres rcn_scraper -c \
  "SELECT id, is_sold, sold_at, created_at, scraped_at FROM listings ORDER BY id DESC LIMIT 5"
```
