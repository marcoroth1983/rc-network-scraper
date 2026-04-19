# PLAN 024 — Outdated & Sold Filter Toggles

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Replace Phase 3 hard-delete with a soft `is_outdated` flag, and add two filter toggles — "Ältere anzeigen" and "Nur Verkaufte" — to both the mobile filter sheet and the desktop PlzBar dropdown.

**Architecture:** New `is_outdated` boolean column on `listings`. Phase 3 marks listings older than 8 weeks as outdated instead of deleting them. The API defaults to hiding both outdated and sold listings; two independent query params opt into each group. Frontend wires these params through `ListingsFilter` → `useListings` → `client.ts`. Mobile toggles live in the `FilterPanel` bottom sheet; desktop toggles live in the `PlzBar` filter dropdown (the existing `hidden sm:block` sticky bar — NOT FilterPanel, which is mobile-only). Outdated listings get an "ALT" badge in `ListingCard`.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind (frontend), PostgreSQL

**Breaking Changes:** Yes.
- `GET /api/listings` previously returned all listings (including sold). New default: `is_sold = FALSE AND is_outdated = FALSE`. Existing clients that expected sold listings in the main feed will no longer see them.
- `ScrapeSummary.deleted_stale` renamed to `marked_outdated` in both backend and frontend. The ScrapeLog display in the admin UI will show the new field name.
- `GET /api/favorites` is intentionally NOT changed — favorites always show everything (user explicitly pinned the listing; hiding it by default would be surprising). No `is_outdated`/`is_sold` filter is applied there.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-19 |
| Human | approved | 2026-04-19 |

---

## Reference Patterns

- `backend/app/models.py` — PLAN-007 `created_at`/`sold_at` column pattern (lines 56–60)
- `backend/app/db.py` — idempotent `ADD COLUMN IF NOT EXISTS` + backfill pattern (lines 206–218)
- `backend/app/scraper/orchestrator.py` — `_phase3_cleanup` (lines 559–600)
- `backend/app/api/routes.py` — `list_listings` filter params (lines 121–270); `is_sold` filter currently absent — this plan adds it
- `backend/app/api/schemas.py` — `ListingSummary`, `ListingDetail`, `ScrapeSummary` (lines 11–115)
- `frontend/src/hooks/useListings.ts` — `ListingsFilter`, `readFiltersFromParams`, `writeFiltersToParams`
- `frontend/src/api/client.ts` — `getListings`, `ListingsQueryParams`
- `frontend/src/types/api.ts` — `ListingSummary`, `ListingDetail`, `ScrapeSummary`, `ListingsQueryParams`
- `frontend/src/components/FilterPanel.tsx` — mobile-only: bottom sheet (lines 83–355); `hasSecondaryFilters` (line 62)
- `frontend/src/components/PlzBar.tsx` — desktop filter dropdown (`hidden sm:block sticky top-14`); existing filter sections at lines 349–450; `hasActiveFilterBadge` (line 173)
- `frontend/src/components/ListingCard.tsx` — badge pattern (lines 41–90)
- `frontend/src/components/ScrapeLog.tsx` — `deleted_stale` reference (line 19)

## Test Files

- `backend/tests/test_orchestrator_phases.py` — Phase 3 tests; existing `test_phase3_deletes_stale_listings` must be removed (see Step 2)
- `backend/tests/test_scrape_runner.py` — two fixtures with `deleted_stale` key (see Step 2)
- `backend/tests/test_api.py` — API filter tests
- `frontend/src/components/__tests__/ScrapeLog.test.tsx` — `deleted_stale` fixture rename
- Frontend test fixtures across `frontend/src/**/__tests__/` — must add `is_outdated` field (see Step 4c)

---

## Step 1 — ORM model + DB migration [x]

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`

### 1a. Add column to ORM

In `backend/app/models.py`, add after `sold_at` (line 60):

```python
is_outdated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

### 1b. Add migration to `init_db()`

In `backend/app/db.py`, append after the `sold_at` ADD COLUMN block:

```python
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_outdated BOOLEAN NOT NULL DEFAULT FALSE"
))
# Backfill: mark existing rows whose posted_at is older than 8 weeks and are not sold.
# Guard AND is_outdated = FALSE makes this idempotent — rows already marked are skipped.
# All statements run inside engine.begin() (single transaction), so now() is constant.
await conn.execute(text(
    """
    UPDATE listings
    SET is_outdated = TRUE
    WHERE is_sold = FALSE
      AND posted_at IS NOT NULL
      AND posted_at < NOW() - INTERVAL '8 weeks'
      AND is_outdated = FALSE
    """
))
```

### 1c. Verify column

```bash
docker compose up --build -d
docker compose exec db psql -U rcscout rcscout -c "\d listings" | grep is_outdated
```

Expected: `is_outdated | boolean | not null | false`

---

## Step 2 — Phase 3 orchestrator: mark instead of delete [x]

**Depends on:** Step 1

**Files:**
- Modify: `backend/app/scraper/orchestrator.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/test_orchestrator_phases.py`
- Modify: `backend/tests/test_scrape_runner.py`

### 2a. Replace DELETE with UPDATE in `_phase3_cleanup`

Replace the `stale_result` DELETE block (lines 583–592) with:

```python
# Mark non-sold listings older than 8 weeks as outdated (no deletion — kept for history)
outdated_result = await session.execute(
    text("""
        UPDATE listings
        SET is_outdated = TRUE
        WHERE is_sold = FALSE
          AND posted_at < :cutoff
          AND posted_at IS NOT NULL
          AND is_outdated = FALSE
        RETURNING id
    """),
    {"cutoff": eight_weeks_ago},
)
marked_outdated = len(outdated_result.fetchall())
```

Update the return dict and log:

```python
logger.info(
    "Phase 3: cleaned images from %d sold + marked %d outdated listings", cleaned_sold, marked_outdated
)
return {"cleaned_sold": cleaned_sold, "marked_outdated": marked_outdated}
```

### 2b. Rename `deleted_stale` in `ScrapeSummary`

In `backend/app/api/schemas.py`, in `ScrapeSummary`:

```python
# Before:
deleted_stale: int = 0
# After:
marked_outdated: int = 0
```

### 2c. Fix `deleted_stale` call sites in tests — explicit list

**`backend/tests/test_scrape_runner.py` line 88:** Change `"deleted_stale": 0` → `"marked_outdated": 0` in the `p3` fixture dict.

**`backend/tests/test_scrape_runner.py` line 131:** Same rename.

**`backend/tests/test_orchestrator_phases.py`:** Delete the entire existing `test_phase3_deletes_stale_listings` test — its assertion that the row is gone is the inverse of the new behavior. Step 9 adds replacement tests.

### 2d. Phase 2 recheck queue note

`_RECHECK_SQL` queries `is_sold = FALSE` listings — outdated non-sold listings will continue to appear in the recheck pool. This is acceptable (they may still flip to sold), and the pool growth is bounded by the 8-week threshold.

---

## Step 3 — Backend API: new filter params + schemas [x]

**Depends on:** Step 1

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/api/schemas.py`

### 3a. Add `is_outdated` to both `ListingSummary` and `ListingDetail`

In `backend/app/api/schemas.py`:

```python
# In ListingSummary (after is_sold):
is_outdated: bool = False

# In ListingDetail (after is_sold):
is_outdated: bool = False
```

Both schemas use `ConfigDict(from_attributes=True)`, so Pydantic will read the ORM attribute automatically.

### 3b. New filter params in `list_listings`

Add after `price_indicator` parameter (line ~139):

```python
show_outdated: bool = Query(default=False),
only_sold: bool = Query(default=False),
```

### 3c. Apply default + new filters

After the existing filter clauses (before the sort/distance block):

```python
# Default: hide sold and outdated. Toggles opt into each group.
if only_sold:
    stmt = stmt.where(Listing.is_sold == True)
else:
    stmt = stmt.where(Listing.is_sold == False)
    if not show_outdated:
        stmt = stmt.where(Listing.is_outdated == False)
```

When `only_sold=True`, `show_outdated` is ignored — all sold listings (outdated or not) are shown.

### 3d. `GET /api/favorites` — no change

The favorites endpoint is intentionally not filtered by `is_sold` or `is_outdated`. Users explicitly pinned these listings and should always see them regardless of status.

---

## Step 4 — Frontend types + filter wiring [x]

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/hooks/useListings.ts`
- Modify: `frontend/src/api/client.ts`

### 4a. `api.ts` — types

Add `is_outdated: boolean` to **both** `ListingSummary` and `ListingDetail`:

```typescript
is_outdated: boolean;
```

Add to `ListingsQueryParams`:

```typescript
show_outdated?: boolean;
only_sold?: boolean;
```

Rename in `ScrapeSummary`:
```typescript
// Before:
deleted_stale: number;
// After:
marked_outdated: number;
```

### 4b. `useListings.ts`

Add to `ListingsFilter`:

```typescript
show_outdated?: boolean;
only_sold?: boolean;
```

In `readFiltersFromParams`, add:

```typescript
const show_outdated = params.get('show_outdated') === 'true' ? true : undefined;
const only_sold = params.get('only_sold') === 'true' ? true : undefined;
```

Include in the return object. In `writeFiltersToParams`:

```typescript
if (filter.show_outdated) p.set('show_outdated', 'true');
if (filter.only_sold) p.set('only_sold', 'true');
```

In the `getListings(...)` call and dependency array, add `show_outdated` and `only_sold`.

### 4c. `client.ts`

In `getListings`, add:

```typescript
if (params.show_outdated) qs.set('show_outdated', 'true');
if (params.only_sold) qs.set('only_sold', 'true');
```

### 4d. Update frontend test fixtures

`is_outdated: boolean` is a required (non-optional) field on `ListingSummary` and `ListingDetail`. Every test fixture that constructs these types inline will fail `tsc --noEmit` until updated.

Grep for `is_sold: false` across `frontend/src/**/__tests__/` to find all fixture objects (same pattern as the `source` field fix in commit `ade4350`). Add `is_outdated: false` to every `ListingSummary` and `ListingDetail` fixture literal. Affected files include at minimum:
- `frontend/src/components/__tests__/FavoriteCard.test.tsx`
- `frontend/src/components/__tests__/ListingCard.test.tsx`
- `frontend/src/components/__tests__/ListingDetailModal.test.tsx`
- `frontend/src/components/__tests__/FavoritesModal.test.tsx`
- `frontend/src/pages/__tests__/DetailPage.test.tsx`
- `frontend/src/components/__tests__/ScrapeLog.test.tsx` (rename `deleted_stale` → `marked_outdated`)

Run `npx tsc --noEmit` after to confirm no fixture gaps remain.

---

## Step 5 — Mobile filter: "Ansicht" section in FilterPanel [x]

**Depends on:** Step 4

**Files:**
- Modify: `frontend/src/components/FilterPanel.tsx`

**Reuse check:** Pill-button toggle pattern reused from `shipping_available` and `price_indicator` sections in the same file.

### 5a. Update `hasSecondaryFilters`

```typescript
const hasSecondaryFilters =
  filter.category !== 'all' || !!filter.max_distance || filter.sort !== 'date' ||
  filter.sort_dir !== 'desc' || !!filter.price_min || !!filter.price_max ||
  filter.shipping_available === true || !!filter.price_indicator ||
  !!filter.drive_type || !!filter.completeness ||
  !!filter.model_type || !!filter.model_subtype ||
  filter.show_outdated === true || filter.only_sold === true;
```

### 5b. Add "Ansicht" section at the bottom of the mobile filter sheet content div (after Subtyp, before closing `</div></div>`)

```tsx
{/* Ansicht */}
<div>
  <div className={sectionLabel} style={sectionLabelColor}>Ansicht</div>
  <div className="flex flex-wrap gap-2">
    <button
      type="button"
      className={`px-3 py-1.5 rounded-full text-sm transition ${
        filter.only_sold === true
          ? 'bg-aurora-indigo text-white'
          : 'bg-white/10 text-white/70 hover:bg-white/20'
      }`}
      onClick={() => onChange({
        ...filter,
        only_sold: filter.only_sold === true ? undefined : true,
        show_outdated: undefined,
        page: 1,
      })}
    >
      Nur Verkaufte
    </button>
    <button
      type="button"
      className={`px-3 py-1.5 rounded-full text-sm transition ${
        filter.show_outdated === true
          ? 'bg-aurora-indigo text-white'
          : 'bg-white/10 text-white/70 hover:bg-white/20'
      }`}
      disabled={filter.only_sold === true}
      onClick={() => onChange({
        ...filter,
        show_outdated: filter.show_outdated === true ? undefined : true,
        page: 1,
      })}
    >
      Ältere anzeigen
    </button>
  </div>
</div>
```

"Ältere anzeigen" is disabled when "Nur Verkaufte" is active (irrelevant in sold mode). Toggling "Nur Verkaufte" ON resets `show_outdated` to avoid stale URL state.

---

## Step 6 — Desktop filter: "Ansicht" section in PlzBar [x]

**Depends on:** Step 4

**Files:**
- Modify: `frontend/src/components/PlzBar.tsx`

**Context:** The desktop filter lives in `PlzBar` (`hidden sm:block sticky top-14`), NOT in FilterPanel. PlzBar already has its own filter dropdown with Kategorie, Entfernung, and Preis sections. FilterPanel is mobile-only.

**Reuse check:** Pill-button pattern reused from the Versand section in PlzBar (added in the double-searchbar fix prior to this plan).

### 6a. Update `hasActiveFilterBadge`

```typescript
const hasActiveFilterBadge = filter.category !== 'all' || !!filter.max_distance ||
  !!filter.price_min || !!filter.price_max ||
  filter.shipping_available === true || !!filter.price_indicator ||
  !!filter.model_type || !!filter.model_subtype ||
  filter.show_outdated === true || filter.only_sold === true;
```

### 6b. Add "Ansicht" section to PlzBar filter dropdown

Insert after the last section (Subtyp) and before the closing `</div>` of the filter dropdown panel (approximately after line 530 in the current file, inside the `{filterOpen && (<div ...>)}` block):

```tsx
{divider}

{/* Ansicht */}
<div className="px-4 pt-3 pb-4">
  <p className={sectionLabel} style={sectionLabelColor}>Ansicht</p>
  <div className="flex flex-wrap gap-2">
    <button
      type="button"
      className={`px-3 py-1.5 rounded-full text-sm transition ${
        filter.only_sold === true
          ? 'bg-aurora-indigo text-white'
          : 'bg-white/10 text-white/70 hover:bg-white/20'
      }`}
      onClick={() => writeFiltersToParams({
        ...filter,
        only_sold: filter.only_sold === true ? undefined : true,
        show_outdated: undefined,
        page: 1,
      }, setSearchParams)}
    >
      Nur Verkaufte
    </button>
    <button
      type="button"
      className={`px-3 py-1.5 rounded-full text-sm transition ${
        filter.show_outdated === true
          ? 'bg-aurora-indigo text-white'
          : 'bg-white/10 text-white/70 hover:bg-white/20'
      }`}
      disabled={filter.only_sold === true}
      onClick={() => writeFiltersToParams({
        ...filter,
        show_outdated: filter.show_outdated === true ? undefined : true,
        page: 1,
      }, setSearchParams)}
    >
      Ältere anzeigen
    </button>
  </div>
</div>
```

---

## Step 7 — ListingCard: "ALT" badge [x]

**Files:**
- Modify: `frontend/src/components/ListingCard.tsx`

**Reuse check:** No existing pattern for a static non-clickable badge. Follows the same `text-xs font-semibold px-2 py-0.5 rounded-full` visual class pattern as `PriceIndicatorBadge`, but as a `<span>` (not a `<button>`) since it has no click action.

Find where the `is_sold` / "VERKAUFT" badge is rendered. Add the "ALT" badge alongside it:

```tsx
{listing.is_outdated && !listing.is_sold && (
  <span
    className="text-xs font-semibold px-2 py-0.5 rounded-full"
    style={{ background: 'rgba(148,163,184,0.15)', color: '#94A3B8', border: '1px solid rgba(148,163,184,0.25)' }}
  >
    ALT
  </span>
)}
```

The image placeholder: `ListingCard` already handles `images.length === 0` with a grey fallback. No separate asset needed.

---

## Step 8 — ScrapeLog frontend update [x]

**Depends on:** Step 4d

**Files:**
- Modify: `frontend/src/components/ScrapeLog.tsx`
- Modify: `frontend/src/components/__tests__/ScrapeLog.test.tsx`

In `ScrapeLog.tsx` line 19:

```typescript
// Before:
const deleted = (s.cleaned_sold ?? 0) + (s.deleted_stale ?? 0);
// After:
const outdated = (s.cleaned_sold ?? 0) + (s.marked_outdated ?? 0);
```

Update any display label ("gelöscht" / "stale") to "veraltet markiert" or similar.

In `ScrapeLog.test.tsx`, rename `deleted_stale: 0` → `marked_outdated: 0` in all fixtures (covered by Step 4d, but list it here for completeness).

---

## Step 9 — Tests [x]

**Depends on:** Steps 1–3

**Files:**
- Modify: `backend/tests/test_orchestrator_phases.py`
- Modify: `backend/tests/test_api.py`

### Phase 3 tests (in `test_orchestrator_phases.py`)

**Remove** the existing `test_phase3_deletes_stale_listings` test first (its assertion that the row is gone is now wrong).

Add:

1. **Phase 3 marks outdated instead of deleting:**
   - Pre-insert non-sold listing with `posted_at = 9 weeks ago`
   - Run `_phase3_cleanup`
   - Assert listing still exists in DB AND `is_outdated = TRUE`

2. **Phase 3 does not mark sold listings as outdated:**
   - Pre-insert sold listing with `posted_at = 9 weeks ago`
   - Run `_phase3_cleanup`
   - Assert `is_outdated = FALSE`

3. **Phase 3 idempotent — does not re-mark already-outdated listings:**
   - Pre-insert listing with `is_outdated = TRUE, posted_at = 9 weeks ago`
   - Run `_phase3_cleanup`
   - Assert `result["marked_outdated"] == 0` AND `is_outdated` still `TRUE` (second SELECT to confirm no regression)

4. **Phase 3 does not mark recent listings:**
   - Pre-insert listing with `posted_at = 2 weeks ago`
   - Run `_phase3_cleanup`
   - Assert `is_outdated = FALSE`

### API filter tests (in `test_api.py`)

5. **Default hides sold and outdated:**
   - Pre-insert: one active (`is_sold=F, is_outdated=F`), one sold, one outdated non-sold
   - `GET /api/listings` — assert only active listing in results

6. **Default also hides both-flags-set listing:**
   - Pre-insert: one listing with `is_sold=TRUE AND is_outdated=TRUE`
   - `GET /api/listings` (default) — assert 0 results

7. **`show_outdated=true` includes outdated non-sold:**
   - Pre-insert: one active, one outdated non-sold
   - `GET /api/listings?show_outdated=true` — assert both in results

8. **`only_sold=true` shows only sold listings:**
   - Pre-insert: one active, one sold, one outdated non-sold
   - `GET /api/listings?only_sold=true` — assert only sold in results

9. **`only_sold=true` includes sold outdated listings:**
   - Pre-insert: one sold+outdated listing
   - `GET /api/listings?only_sold=true` — assert it appears

---

## Verification

```bash
# Apply migration
docker compose up --build -d

# Verify column exists
docker compose exec db psql -U rcscout rcscout -c "\d listings" | grep is_outdated

# Verify backfill
docker compose exec db psql -U rcscout rcscout -c \
  "SELECT is_outdated, COUNT(*) FROM listings GROUP BY is_outdated"

# Verify default API hides sold+outdated
docker compose exec db psql -U rcscout rcscout -c \
  "SELECT COUNT(*) FROM listings WHERE is_sold = FALSE AND is_outdated = FALSE"
# Should match count returned by GET /api/listings (no params)

# Run backend tests
docker compose exec backend pytest tests/test_orchestrator_phases.py tests/test_api.py -v

# Run frontend type-check (must be zero errors)
cd frontend && npx tsc --noEmit

# Run frontend tests
cd frontend && npx vitest run
```

---

## Plan Review
<!-- dglabs.agent.review-plan — 2026-04-19 -->

### Structural Checklist
- [x] Required sections present (Context/Goal, Breaking Changes, Approval table, Steps, Verification, Reference Patterns, Test Files)
- [x] Step status markers present (`[ ]` on every step header; will flip to `[x]` during implementation)
- [x] Step granularity suitable for a fresh AI instance (each step fits well within a single agent context; Step 4 is the largest but bounded)
- [x] Test files named per step (Step 9 lists target files; Step 4d instructs grep-based fixture update)
- [x] Breaking changes marked Yes with concrete list (3 items)
- [x] No BREAK markers needed — plan is fully additive from the Human's perspective once approved; no irreversible forks inside the implementation path
- [x] Dependencies between steps are explicit (`Depends on: Step N` on Steps 2, 3, 5, 6, 8, 9)

### Codebase Verification (first-hand reads)
- `backend/app/models.py` — `sold_at` is line 60, new column placement ✅
- `backend/app/db.py` — migration block ends at line 221 (not 218 as cited); pattern is identical, harmless drift ✅
- `backend/app/scraper/orchestrator.py` — `_phase3_cleanup` is lines 559–600 ✅; DELETE block is lines 583–593 (plan says 583–592, off by one for the closing line of `RETURNING`) — acceptable
- `backend/app/api/routes.py` — `list_listings` params 121–142; `price_indicator` is line 139 ✅; favorites endpoint verified as not going through `list_listings` (lines 434–461) — Step 3d claim is correct
- `backend/app/api/schemas.py` — `ListingSummary` 11–44, `ListingDetail` 47–84, `ScrapeSummary` 96–103 ✅
- `frontend/src/components/FilterPanel.tsx` — **`hasSecondaryFilters` is at line 49, not line 62** (plan Reference Patterns line 33 says line 62; line 62 is `inputStyle`) — non-blocking mislabel
- `frontend/src/components/PlzBar.tsx` — `hasActiveFilterBadge` is line 175 (plan says line 173); existing filter dropdown block is lines 352–552 (plan cites 349–450 as "existing filter sections", actually covers IconButton + Entfernung block only) — non-blocking mislabel
- `frontend/src/components/ListingCard.tsx` — VERKAUFT badge at lines 140–148; `PriceIndicatorBadge` at lines 41–82 (plan says 41–90) — close enough
- `frontend/src/components/ScrapeLog.tsx` — `deleted_stale` reference at line 19 ✅
- `frontend/src/hooks/useListings.ts` — `ListingsFilter`, `readFiltersFromParams`, `writeFiltersToParams` all present and match the plan's proposed wiring ✅
- `frontend/src/api/client.ts` — `getListings` + `ListingsQueryParams` match ✅
- `frontend/src/types/api.ts` — `ListingSummary`, `ListingDetail`, `ScrapeSummary`, `ListingsQueryParams` match ✅

### Codex Cross-Review
**Codex CLI unavailable** — repeated `401 Unauthorized` on `api.openai.com/v1/responses` at 2026-04-19T11:27Z. Review is based solely on agent-side analysis + direct code reads. No findings lost — every file mentioned in the plan was read first-hand during this review.

### 🔴 Blocking
None. The plan is technically sound and implementable as written.

### 🟡 Non-Blocking

1. **[Agent] — Step 4d frontend fixture list is incomplete.**
   `rg "is_sold: (true|false)" frontend/` returns hits in 5 files:
   - `frontend/src/pages/__tests__/DetailPage.test.tsx`
   - `frontend/src/__tests__/ModalRouting.test.tsx` ← **NOT listed in the plan**
   - `frontend/src/components/__tests__/FavoriteCard.test.tsx`
   - `frontend/src/components/__tests__/ListingCard.test.tsx`
   - `frontend/src/components/__tests__/FavoritesModal.test.tsx`

   The plan additionally lists `ListingDetailModal.test.tsx`, which contains **zero** `is_sold` literals — it mocks `getListing` differently and constructs no inline `ListingSummary`/`ListingDetail` fixtures. The grep instruction in Step 4d (`Grep for is_sold: false across frontend/src/**/__tests__/`) is correct and will catch `ModalRouting.test.tsx`, so the executing agent will find the right files regardless. The explicit list is just stale — recommend adding `ModalRouting.test.tsx` and removing `ListingDetailModal.test.tsx` so the list matches reality, otherwise the implementer may trust the list over the grep.

2. **[Agent] — Minor line-number drift in Reference Patterns & Step 6b.**
   `FilterPanel.hasSecondaryFilters` is line **49**, not 62. `PlzBar.hasActiveFilterBadge` is line **175**, not 173. PlzBar's filter dropdown ends at line **552** (plan says "approximately after line 530"). None of these affect correctness — the plan still names the identifier to modify — but any fresh agent opening line 62 of FilterPanel will hit `inputStyle` and have to search for `hasSecondaryFilters` themselves.

3. **[Agent] — Step 2a line range is 583–593, not 583–592.** The `RETURNING id` closing parenthesis sits on line 593. Trivial.

4. **[Agent] — Step 8 label update is vague.** Plan says "Update any display label ('gelöscht' / 'stale') to 'veraltet markiert' or similar." The current label in `ScrapeLog.tsx` line 20 is `${deleted} gelöscht`. Since listings are no longer deleted, "gelöscht" is actively misleading for admin observability. Recommend the plan prescribe the exact new label (e.g. `${outdated} veraltet`) instead of "or similar" to prevent inconsistent implementations if the step is re-run.

5. **[Agent] — Step 2d Phase 2 recheck claim verified but worth strengthening.** `_RECHECK_SQL` at `backend/app/scraper/orchestrator.py:449–455` filters only on `is_sold = FALSE`, so outdated non-sold listings continue cycling through the recheck pool indefinitely (Phase 2 bumps `scraped_at = now()` on every recheck, so they never "age out" of the queue). This is exactly what the plan claims, and the "bounded by 8-week threshold" phrasing is slightly misleading — the pool size is bounded by the crawl cadence, not by the outdated threshold. Consider tightening the note: _"outdated non-sold rows are still rechecked; if this becomes noisy, a future plan can add `AND is_outdated = FALSE` to `_RECHECK_SQL` — out of scope here."_

6. **[Agent] — Docs update for lifecycle change is not mentioned in the plan.** `docs/definition.md` and `docs/architektur.md` do not currently describe the Phase 3 retention policy (neither "delete after 8 weeks" nor the new "soft-flag"), so the lifecycle change is not documented anywhere. Not a blocker because neither doc currently contradicts the new behavior, but this is exactly the kind of hidden policy that belongs in `architektur.md` under "Scraping Strategy" (right next to the existing "Sold recheck" bullet at line 88). Recommend adding a Step 10 (or extending Step 8) to add one sentence to `architektur.md`: _"Phase 3: listings with `posted_at > 8 weeks` are marked `is_outdated=TRUE`; the API hides them by default but keeps them in the DB for history."_ Also consider whether a `limitations.md` entry is needed for "outdated listings never fully aged out of Phase 2 recheck".

7. **[Agent] — Step 3c wording clarity.** The plan says `"When only_sold=True, show_outdated is ignored"`, which matches the code: `only_sold=True` branches unconditionally into `Listing.is_sold == True` without applying the outdated filter. This is consistent with the UI disabled-state in Steps 5/6 (Ältere-Button is disabled when only_sold active). Edge case worth an explicit test (not currently in Step 9): `only_sold=TRUE, show_outdated=TRUE` — should behave identically to `only_sold=TRUE` (outdated flag ignored server-side even if the client somehow sends both). Test 9 almost covers this, but making it explicit would prevent accidental regressions if the ignore-logic is refactored.

8. **[Agent] — `_UPSERT_SQL` interaction with `is_outdated`.** `_UPSERT_SQL` in `orchestrator.py:72–109` does not touch `is_outdated` (correct — no clobber on re-insert of old rows, new rows default to FALSE via server_default). However, **if a previously outdated listing is re-listed by the seller, Phase 1 upserts `scraped_at = now()` but does not reset `is_outdated` to FALSE**. This means: a listing marked outdated 9 weeks ago but still actively refreshed by the seller will stay hidden from the default feed forever. Probably negligible in practice (Phase 1 finds it "fully known" and skips), but worth a line in Assumptions & Risks. Not a blocker — current DELETE behavior has the same issue (row is gone, seller re-posts under a new external_id) — but the soft-flag inverts the tradeoff.

9. **[Agent] — Verification section does not prove the UI toggles work.** The `cd frontend && npx vitest run` line checks tests pass, but no instruction asks the implementer to load the app in a browser and confirm the two new toggles in both FilterPanel and PlzBar actually toggle listing visibility end-to-end. Not strictly required (unit tests + type-check cover the wiring), but a manual smoke-test one-liner would catch regressions the tests miss (e.g. URL round-trip through `readFiltersFromParams`/`writeFiltersToParams`).

10. **[Agent] — `is_outdated: false` as a REQUIRED TS field.** Step 4a declares `is_outdated: boolean` (non-optional). Plan correctly flags this in Step 4d as the reason fixtures must be updated. Alternative: make it optional (`is_outdated?: boolean`) on the TS side — backend always sends it, so the client-side optionality costs nothing and removes the need to patch ~6 test files. Non-blocking style choice; the plan's stricter approach is arguably better for catching bugs, so keep as-is unless the Human prefers less churn.

### Verdict
✅ **APPROVED** — no blocking issues. All file paths and identifiers referenced are present in the codebase; the idempotent SQL in Step 1b is correct (`AND is_outdated = FALSE` guard makes re-runs no-op); Phase 2 recheck interaction (Step 2d) matches the actual `_RECHECK_SQL`; favorites endpoint (Step 3d) is confirmed not to go through `list_listings`; `only_sold`/`show_outdated` interaction in Step 3c is consistent with the UI disabled-state in Steps 5/6. The non-blocking notes (primarily the `ModalRouting.test.tsx` fixture gap and the missing `architektur.md` update for the lifecycle change) should be addressed by the implementing agent during execution but do not warrant a re-review loop.

_Codex cross-review was attempted but `codex exec` returned 401 Unauthorized from OpenAI. Review completeness relies on first-hand reads of every file mentioned in the plan._

---

_Code review closed 2026-04-19 (backend, cycle 1): 0 critical, 2 important (W1 upsert comment → applied, W2 NULL posted_at test → added), 4 recommended (deferred as tech-debt notes — thresholds-as-constants, test_scrape_runner extra assert, posted_at helper comment)._

_Code review closed 2026-04-19 (frontend, cycle 1): 0 critical/high, 2 medium (M1 NEU-badge guard with !is_outdated → applied, M2 pre-existing failures confirmed → no action), 3 low + 1 suggestion (deferred)._
