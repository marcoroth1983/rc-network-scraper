# Saved-Searches Schema-Drift Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Restore saving and listing of saved searches on prod by adding the 9 filter columns (added to the `SavedSearch` model in commit `983c2e8` but never mirrored into `init_db()`) as idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations, plus harden the frontend so a future API failure surfaces instead of silently emptying the list.

**Architecture:** Prod runs `init_db()` (`backend/app/db.py`) on every startup: `Base.metadata.create_all` (no-op for existing tables) + explicit idempotent ALTERs. The `saved_searches` table predates the 9 filter columns, so `create_all` never adds them and `init_db` has no ALTER for them → every `SELECT`/`INSERT` on the full model raises `UndefinedColumnError` (500). Tests pass because `conftest.py` rebuilds the schema fresh from `Base.metadata`. Fix = add the 9 ALTERs to `init_db()`; the columns appear on the next deploy (startup). Frontend `useSavedSearches.load()` currently has no error handling, so a 500 leaves `searches` at `[]` ("all gone"), and `handleSave` awaits without a catch so a failed POST shows no feedback ("button does nothing").

**Tech Stack:** Python 3.12, SQLAlchemy async, asyncpg, PostgreSQL 16, pytest/pytest-asyncio; React 18 + TypeScript + Vite, Vitest.

**Breaking Changes:** No. All 9 columns are nullable with no default — additive only. No data loss; existing rows (prod row-count verified = 1) are preserved and become readable again once the columns exist.

**Out of scope (explicit):**
- Other tables: a full model-vs-`init_db` drift audit (2026-06-07) confirmed drift is **isolated to `saved_searches`**; `listings`, `users`, `plz_geodata`, `intl_geodata`, `user_favorites`, `push_subscriptions`, `user_notification_prefs`, `search_notifications` are all fully covered.
- A visible error toast/banner for failed saves — single-user hobby app; `console.error` + non-silent failure is sufficient (YAGNI). Note in `docs/backlog.md` if desired.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-06-07 |
| Human | approved | 2026-06-07 |

---

## Context

**Root cause (verified on prod 2026-06-07):**
- Prod `saved_searches` has 13 columns; the 9 model columns `price_min, price_max, drive_type, completeness, shipping_available, model_type, model_subtype, show_outdated, only_sold` are **absent** (`\d saved_searches` on `rcn-scout-db-1`).
- Prod backend log: `asyncpg.exceptions.UndefinedColumnError: column saved_searches.price_min does not exist` on `SELECT ... FROM saved_searches WHERE is_active IS true`.
- Prod row-count = 1 → data not lost; the empty UI is the 500-on-GET rendering `[]`.

**Model definition (verified):** `backend/app/models.py:110-118` — all 9 columns, all nullable, no `server_default`:
- `price_min` Float · `price_max` Float · `drive_type` String(50) · `completeness` String(50) · `shipping_available` Boolean · `model_type` String(50) · `model_subtype` String(50) · `show_outdated` Boolean · `only_sold` Boolean

**Type mapping (SQLAlchemy → PostgreSQL):** Float → `DOUBLE PRECISION`, String(50) → `VARCHAR(50)`, Boolean → `BOOLEAN`. All nullable → no `DEFAULT` clause (mirrors the existing nullable `category` ALTER at `db.py:44`).

**`init_db()` structure (verified `backend/app/db.py:18-258`):** uses the **module-level** `engine` (`db.py:9`, bound to `settings.DATABASE_URL`) via `async with engine.begin() as conn`. The existing `saved_searches` ALTER is at `db.py:43-45`:
```python
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS category VARCHAR(50)"
        ))
```
New ALTERs are inserted immediately after this block. **Migration-test implication:** because `init_db` binds the module-global `engine`, a test must monkeypatch `app.db.engine` to the test engine before calling `init_db()`.

**Schema-Sweep note:** `conftest.py` (`backend/tests/conftest.py:48-91`) builds the test schema via `Base.metadata.create_all` — which already includes the 9 columns (they are on the model) — plus manual ALTERs for non-model tables. **No conftest change is needed**: `create_all` covers the 9 columns for tests. Only `init_db()` (the prod path on a pre-existing table) is missing them.

**Frontend save flow (verified):**
- `frontend/src/hooks/useSavedSearches.ts:26-29` `load()` — `await getSavedSearches(); setSearches(result)`, no try/catch.
- `useSavedSearches.ts:35-38` `save()` — `await createSavedSearch(criteria); await load()`.
- `frontend/src/pages/ListingsPage.tsx:170-179` `handleSave`/`handleUpdate` — `await onSaveSearch(...); showFeedback('saved')`, no try/catch; `showFeedback` only supports `'saved' | 'updated'` (`ListingsPage.tsx:164`).

**Frontend test convention (mirror reference):** `frontend/src/hooks/__tests__/useInfiniteListings.test.tsx:11-30` — explicit vitest imports (`import { describe, it, expect, vi, beforeEach } from 'vitest'`), `vi.mock('../../api/client', () => ({ ... }))` declared BEFORE importing the hook, `renderHook` + `waitFor` from `@testing-library/react`. Mirror this; new mock surface: `getSavedSearches`, `createSavedSearch`, `markSearchesViewed` (and any other `../api/client` exports the hook imports — see `useSavedSearches.ts:2-9`).

---

### Task 1: Add the 9 saved_searches filter columns to init_db() [IMPLEMENTED]

**Files:**
- Modify: `backend/app/db.py:43-45` (insert immediately after the existing `category` ALTER block)

**Step 1: Implement**

Insert the following block directly after the existing `ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS category VARCHAR(50)` statement (after `db.py:45`):

```python
        # PLAN-031: saved-searches filter columns (added to the SavedSearch model in
        # commit 983c2e8 but never mirrored here — prod table predates them, so create_all
        # never added them and every SELECT/INSERT 500'd with UndefinedColumnError).
        # All nullable, no default — mirrors the model (models.py:110-118).
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS price_min DOUBLE PRECISION"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS price_max DOUBLE PRECISION"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS drive_type VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS completeness VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS shipping_available BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS model_type VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS model_subtype VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS show_outdated BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS only_sold BOOLEAN"
        ))
```

**Step 2: Commit**

```bash
git add backend/app/db.py
git commit -m "fix: add missing saved_searches filter columns to init_db migration (PLAN-031)"
```

---

### Task 2: Regression test — init_db re-adds filter columns to a legacy table [IMPLEMENTED]

**Depends on:** Task 1

**Files:**
- Create: `backend/tests/test_db_migrations.py`

**Reuse check:** No existing test exercises `init_db()`. This is a new convention (migration-idempotency test). The test mirrors the async/`text(...)` style of `test_orchestrator_phases.py:20-60` but operates on the schema, not on listings data.

**Why this test catches the bug:** normal tests can't — `conftest.py` rebuilds the full schema from the model. This test simulates the legacy prod table (drops the 9 columns), runs the real `init_db()` against the test engine (monkeypatched), and asserts the columns are restored. It would have failed before Task 1.

**Step 1: Write test**

```python
"""Regression test for init_db() schema migrations.

Guards against the saved_searches drift (PLAN-031): columns added to a model
after its table already exists must be mirrored as explicit ALTERs in init_db(),
or prod (where the table pre-exists) is missing them. conftest rebuilds the
schema from Base.metadata, so only a legacy-shaped table reproduces the bug.
"""
import pytest
from sqlalchemy import text

import app.db as db_module
from app.db import init_db

_FILTER_COLUMNS = [
    "price_min", "price_max", "drive_type", "completeness", "shipping_available",
    "model_type", "model_subtype", "show_outdated", "only_sold",
]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_init_db_readds_saved_search_filter_columns(test_engine, monkeypatch):
    # Bind init_db() to the test engine (it uses the module-global `engine`).
    monkeypatch.setattr(db_module, "engine", test_engine)

    # Simulate the legacy prod table: drop the 9 filter columns.
    async with test_engine.begin() as conn:
        for col in _FILTER_COLUMNS:
            await conn.execute(text(f"ALTER TABLE saved_searches DROP COLUMN IF EXISTS {col}"))

    # Run the real migration.
    await init_db()

    # All 9 columns must exist again.
    async with test_engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'saved_searches'"
        ))
        present = {row[0] for row in result.fetchall()}
    missing = [c for c in _FILTER_COLUMNS if c not in present]
    assert not missing, f"init_db did not add columns: {missing}"
```

Note: this test uses the session-scoped `test_engine` fixture (not `db_session`) and restores the schema by re-running `init_db()`, so it leaves the table whole for subsequent tests. Ordering-risk (accepted): the DROP loop and `init_db()` run back-to-back with no assertion between them, so the window where the schema could be left broken for later tests (e.g. `test_saved_searches.py`) is near-zero; if `init_db()` itself regresses, expect cascading failures pointing here first.

**Step 2: Commit**

```bash
git add backend/tests/test_db_migrations.py
git commit -m "test: regression test for init_db saved_searches column migration (PLAN-031)"
```

---

### Task 3: Harden frontend saved-search load/save against silent failure [ ]

**Depends on:** none (independent of Tasks 1–2)

**Files:**
- Modify: `frontend/src/hooks/useSavedSearches.ts:26-29` (`load`)
- Modify: `frontend/src/pages/ListingsPage.tsx:170-179` (`handleSave`, `handleUpdate`)
- Create: `frontend/src/hooks/__tests__/useSavedSearches.test.tsx`

**Reuse check:** No existing `useSavedSearches` test. Mirrors `useInfiniteListings.test.tsx:11-30` (explicit vitest imports + `vi.mock('../../api/client', ...)` before hook import + `renderHook`/`waitFor`).

**Step 1: Harden `load()` in `useSavedSearches.ts`**

Replace `load` (`useSavedSearches.ts:26-29`):

```typescript
  const load = async () => {
    try {
      const result = await getSavedSearches();
      setSearches(result);
    } catch (err) {
      // Keep the previous list rather than blanking it on a transient failure
      // (a 500 here previously made all saved searches look "gone").
      console.error('Failed to load saved searches:', err);
    }
  };
```

**Step 2: Harden `handleSave`/`handleUpdate` in `ListingsPage.tsx`**

Replace `handleSave` and `handleUpdate` (`ListingsPage.tsx:170-179`) so a failed mutation logs instead of throwing an unhandled rejection, and success feedback only fires on success:

```typescript
  async function handleSave() {
    try {
      await onSaveSearch(criteriaFromFilter(filter));
      showFeedback('saved');
    } catch (err) {
      console.error('Failed to save search:', err);
    }
  }

  async function handleUpdate() {
    if (activeSavedSearchId == null) return;
    try {
      await onUpdateSearch(activeSavedSearchId, criteriaFromFilter(filter));
      showFeedback('updated');
    } catch (err) {
      console.error('Failed to update search:', err);
    }
  }
```

**Step 3: Write test**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

vi.mock('../../api/client', () => ({
  getSavedSearches: vi.fn(),
  createSavedSearch: vi.fn(),
  updateSavedSearch: vi.fn(),
  deleteSavedSearch: vi.fn(),
  toggleSavedSearch: vi.fn(),
  markSearchesViewed: vi.fn(),
}));

import { useSavedSearches } from '../useSavedSearches';
import * as client from '../../api/client';

describe('useSavedSearches.load resilience', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps an empty list and does not throw when the API rejects on mount', async () => {
    vi.mocked(client.getSavedSearches).mockRejectedValue(new Error('500'));
    const { result } = renderHook(() => useSavedSearches());
    // Allow the mount effect to run and reject internally.
    await waitFor(() => expect(client.getSavedSearches).toHaveBeenCalled());
    expect(result.current.searches).toEqual([]);
  });

  it('does not blank a previously loaded list when a later load fails', async () => {
    vi.mocked(client.getSavedSearches).mockResolvedValueOnce([
      { id: 1, name: 'A', is_active: true, match_count: 0 } as never,
    ]);
    const { result } = renderHook(() => useSavedSearches());
    await waitFor(() => expect(result.current.searches).toHaveLength(1));

    vi.mocked(client.getSavedSearches).mockRejectedValueOnce(new Error('500'));
    await act(async () => { await result.current.load(); });
    expect(result.current.searches).toHaveLength(1);
  });
});
```

**Step 4: Commit**

```bash
git add frontend/src/hooks/useSavedSearches.ts frontend/src/pages/ListingsPage.tsx frontend/src/hooks/__tests__/useSavedSearches.test.tsx
git commit -m "fix: surface saved-search load/save failures instead of silently emptying list (PLAN-031)"
```

---

## Verification

### A. Automated (run once, after all tasks)

Backend (from the backend container):

```bash
docker compose exec backend pytest tests/test_db_migrations.py tests/test_saved_searches.py -v
docker compose exec backend pytest tests/ -q
```
Expect: the new migration test passes; existing `test_saved_searches.py` still passes; full suite green.

Frontend (from `frontend/`):

```bash
docker compose exec frontend npm run test -- --run src/hooks/__tests__/useSavedSearches.test.tsx
```
(Verify the script name against `frontend/package.json` before running; use the project's standard vitest invocation. Full FE suite has pre-existing unrelated failures tracked as TEST-01/02 in `docs/backlog.md` — do not block on those.)

### B. Operational — deploy both fixes to the VPS (Human-authorized)

Both PLAN-030 (geocode guard, already on `main`) and PLAN-031 ship in one release **v2.7.1**.

0. **Safety net — pull a full DB dump from the live VPS BEFORE deploying** (the migration alters the prod schema). Store locally with a timestamped name; verify the file is non-empty:
   ```bash
   ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
     "docker exec rcn-scout-db-1 pg_dump -U rcscout -d rcscout" > "backup_rcscout_prod_2026-06-07.sql"
   ```
   Confirm the dump contains the `saved_searches` data (the existing row) before proceeding. Do NOT release until the dump is verified.
1. Bump `frontend/package.json` version to `2.7.1`; ensure `CHANGELOG.md` `[2.7.1]` section lists both fixes (geocode guard + saved-searches columns).
2. Cut the release (triggers GH Actions deploy): `gh release create v2.7.1 --title v2.7.1 --notes "..."` (deploy is release-triggered, NOT push-triggered).
3. After deploy, verify on prod that `init_db()` applied the columns:
   ```bash
   ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
     "docker exec rcn-scout-db-1 psql -U rcscout -d rcscout -c '\\d saved_searches'"
   ```
   Expect all 9 columns present.
4. Confirm the saved-search list loads and saving works in the live app, and the existing row (count = 1) reappears.
