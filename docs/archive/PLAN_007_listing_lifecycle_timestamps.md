# PLAN 007 — Listing Lifecycle Timestamps

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | pending | — |
| Human | pending | — |

## Context & Goal

When debugging why a listing wasn't updated or marked as sold, the only available timestamp is `scraped_at` — which gets overwritten on every phase 2 check, making it impossible to tell when a listing was first seen or when its sold status changed.

Add two new DB columns for full lifecycle visibility:

- `created_at` — when the listing was first inserted into the DB
- `sold_at` — when `is_sold` flipped to TRUE (NULL if not sold)

No frontend changes. For internal debugging via direct DB queries only.

## Breaking Changes

**No.** Additive DB migration only — new nullable columns with defaults. Existing data gets sensible fallback values.

## Steps

### Step 1 — Alembic migration

Add migration that:
- Adds `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` — backfills existing rows with `scraped_at` as approximation
- Adds `sold_at TIMESTAMPTZ NULL DEFAULT NULL`

```sql
ALTER TABLE listings
  ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN sold_at TIMESTAMPTZ NULL;

-- Backfill: use scraped_at as best-effort creation time for existing rows
UPDATE listings SET created_at = scraped_at;
```

Migration file: `backend/alembic/versions/XXXX_add_lifecycle_timestamps.py`

### Step 2 — ORM model

In `backend/app/models.py`, add to `Listing`:

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), nullable=False, server_default=func.now()
)
sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### Step 3 — Orchestrator: set `created_at` on insert

The upsert SQL in `_UPSERT_SQL` (`orchestrator.py:66`) uses `ON CONFLICT DO UPDATE`. Add `created_at` to the INSERT but **not** to the UPDATE SET — so it's only written once on first insert:

```sql
INSERT INTO listings (
    ..., created_at, is_sold
) VALUES (
    ..., :created_at, :is_sold
)
ON CONFLICT (external_id) DO UPDATE SET
    ...
    -- created_at intentionally omitted — never overwritten
    is_sold = EXCLUDED.is_sold OR listings.is_sold
```

Pass `created_at=now` in the params dict alongside `scraped_at`.

### Step 4 — Orchestrator: set `sold_at` when marking sold

Two places in Phase 2 (`orchestrator.py`) set `is_sold = TRUE`:

1. **HTTP 403/404/410** (line ~449):
   ```sql
   UPDATE listings SET is_sold = TRUE, sold_at = :now, scraped_at = :now WHERE id = :id
   ```

2. **Parser detects sold** (line ~479–482):
   ```sql
   UPDATE listings SET is_sold = :is_sold,
     sold_at = CASE WHEN :is_sold AND sold_at IS NULL THEN :now ELSE sold_at END,
     scraped_at = :now
   WHERE id = :id
   ```
   The CASE guard ensures `sold_at` is only set once (first time is_sold becomes TRUE).

Also handle `PATCH /api/listings/{id}/sold` in `routes.py` — set `sold_at = now()` there too.

### Step 5 — Tests

Update `backend/tests/test_orchestrator_phases.py`:
- Verify `sold_at` is set when Phase 2 marks a listing as sold via 404
- Verify `sold_at` is set when Phase 2 marks via parser detection
- Verify `sold_at` is NOT overwritten if already set (idempotent)
- Verify `created_at` is not overwritten on upsert conflict

## Reference Patterns

- `backend/app/scraper/orchestrator.py` — `_UPSERT_SQL`, `_phase2_sold_recheck`
- `backend/app/models.py` — existing column definitions
- `backend/app/api/routes.py` — `PATCH /sold` endpoint
- `backend/alembic/versions/` — existing migration for style reference

## Verification

```bash
# Run migration
docker compose exec backend alembic upgrade head

# Check columns exist
docker compose exec db psql -U postgres rcn_scraper -c "\d listings"

# Check no existing row has NULL created_at
docker compose exec db psql -U postgres rcn_scraper -c \
  "SELECT COUNT(*) FROM listings WHERE created_at IS NULL"

# Run tests
docker compose exec backend pytest tests/test_orchestrator_phases.py -v

# Manual: mark one listing sold, check sold_at
docker compose exec db psql -U postgres rcn_scraper -c \
  "SELECT id, is_sold, sold_at, created_at, scraped_at FROM listings ORDER BY id DESC LIMIT 5"
```
