# Model Type / Subtype Filter UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Expose `model_type` and `model_subtype` as filter controls in the FilterPanel mobile bottom sheet, with full URL persistence and backend wiring.

**Architecture:** The vocabulary is hardcoded in a frontend constants file that mirrors `backend/app/analysis/vocabulary.py`. The FilterPanel renders a static Typ dropdown and a dynamic Subtyp dropdown (options depend on selected Typ). Changing Typ resets Subtyp. The filter flows through the existing `ListingsFilter → useInfiniteListings → getListings → API` chain. `useListings` shares `ListingsFilter` and its read/write helpers — both hooks must be updated consistently.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Vite, FastAPI (backend `model_type` filter param missing — added here)

**Breaking Changes:** No

**Out of scope:** Saved search persistence for `model_type`/`model_subtype` (SavedSearch backend schema and SearchCriteria type are not extended in this plan — add to backlog if needed).

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-18 |
| Human | approved | 2026-04-18 |

---

## Overview of Changes

| Layer | File | Change |
|---|---|---|
| Backend | `backend/app/api/routes.py` | Add `model_type` query param and WHERE clause |
| Frontend | `frontend/src/constants/vocabulary.ts` | New: hardcoded vocabulary |
| Frontend | `frontend/src/types/api.ts` | Add `model_type` to `ListingsQueryParams` |
| Frontend | `frontend/src/hooks/useListings.ts` | Add `model_type`/`model_subtype` to `ListingsFilter`, read/write helpers |
| Frontend | `frontend/src/api/client.ts` | Pass `model_type`/`model_subtype` to query string |
| Frontend | `frontend/src/hooks/useInfiniteListings.ts` | Add `model_type`/`model_subtype` to filterRef, filterChanged, destructure, getListings call, deps, returned filter |
| Frontend | `frontend/src/components/FilterPanel.tsx` | Add Typ + Subtyp sections, update `hasSecondaryFilters` |
| Frontend | `frontend/src/components/__tests__/FilterPanel.test.tsx` | Extend `defaultFilter`, add 5 new tests |

---

## Task 1: Backend — add `model_type` filter param [ ]

**Files:**
- Modify: `backend/app/api/routes.py` around lines 134 and 172

**Step 1: Add query param after `completeness`**

In the function signature of `list_listings`, add `model_type` immediately before `model_subtype` (currently line 134):

```python
model_type: str | None = Query(default=None),
model_subtype: str | None = Query(default=None),
```

**Step 2: Add WHERE clause after `completeness` filter block**

After `if completeness: stmt = stmt.where(Listing.completeness == completeness)` (around line 171), replace the existing `model_subtype` block with:

```python
if model_type:
    stmt = stmt.where(Listing.model_type == model_type)
if model_subtype:
    stmt = stmt.where(Listing.model_subtype == model_subtype)
```

**Step 3: Verify backend starts without errors**

```bash
docker compose restart backend
docker compose logs backend --tail=20
```

Expected: no tracebacks, `Application startup complete.`

**Step 4: Commit**

```bash
git add backend/app/api/routes.py
git commit -m "feat(api): add model_type filter param to GET /listings"
```

---

## Task 2: Frontend vocabulary constants [ ]

**Files:**
- Create: `frontend/src/constants/vocabulary.ts`

**Step 1: Create vocabulary file**

```typescript
// Must mirror backend/app/analysis/vocabulary.py — update both when vocabulary changes.

export const MODEL_TYPES = [
  "airplane", "helicopter", "multicopter", "glider", "boat", "car",
] as const;

export type ModelType = typeof MODEL_TYPES[number];

export const MODEL_SUBTYPES: Record<ModelType, string[]> = {
  airplane: ["jet", "warbird", "trainer", "scale", "3d", "nurflügler",
    "hochdecker", "tiefdecker", "mitteldecker", "delta", "biplane",
    "aerobatic", "kit", "hotliner", "funflyer", "speed", "pylon"],
  helicopter: ["700", "580", "600", "550", "500", "450", "420", "380", "scale"],
  glider: ["thermik", "hotliner", "f3b", "f3k", "f3j", "f5j", "f5b", "f5k",
    "f3f", "f3l", "hangflug", "dlg", "scale", "motorglider"],
  multicopter: ["quadcopter", "hexacopter", "fpv"],
  boat: ["rennboot", "segelboot", "schlepper", "submarine", "yacht"],
  car: ["buggy", "monstertruck", "crawler", "tourenwagen", "truggy", "drift"],
};

export const MODEL_TYPE_LABELS: Record<ModelType, string> = {
  airplane: "Flugzeug",
  helicopter: "Hubschrauber",
  multicopter: "Multicopter",
  glider: "Segler",
  boat: "Boot",
  car: "Auto",
};
```

**Step 2: Commit**

```bash
git add frontend/src/constants/vocabulary.ts
git commit -m "feat(frontend): add vocabulary constants mirroring backend"
```

---

## Task 3: Type definitions [ ]

**Depends on:** Task 2

**Files:**
- Modify: `frontend/src/types/api.ts` (interface `ListingsQueryParams`)

**Step 1: Add `model_type` and `model_subtype` to `ListingsQueryParams`**

Replace the existing `ListingsQueryParams` interface (lines 122–137) with:

```typescript
export interface ListingsQueryParams {
  page?: number;
  per_page?: number;
  search?: string | null;
  sort?: 'date' | 'price' | 'distance';
  sort_dir?: 'asc' | 'desc';
  plz?: string | null;
  max_distance?: number | null;
  category?: string | null;
  price_min?: number | null;
  price_max?: number | null;
  drive_type?: string;
  completeness?: string;
  shipping_available?: boolean;
  price_indicator?: string;
  model_type?: string;
  model_subtype?: string;
}
```

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat(types): add model_type/model_subtype to ListingsQueryParams"
```

---

## Task 4: API client [ ]

**Depends on:** Task 3

**Files:**
- Modify: `frontend/src/api/client.ts` (function `getListings`, after line 54)

**Step 1: Pass `model_type` and `model_subtype` in query string**

After `if (params.price_indicator) qs.set('price_indicator', params.price_indicator);`, add:

```typescript
if (params.model_type) qs.set('model_type', params.model_type);
if (params.model_subtype) qs.set('model_subtype', params.model_subtype);
```

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(api-client): forward model_type/model_subtype to GET /listings"
```

---

## Task 5: useListings — filter type and URL helpers [ ]

**Depends on:** Task 4

**Files:**
- Modify: `frontend/src/hooks/useListings.ts`

**Step 1: Update `ListingsFilter` interface**

Add two optional fields after `price_indicator`:

```typescript
export interface ListingsFilter {
  search: string;
  plz: string;
  sort: 'date' | 'price' | 'distance';
  sort_dir: 'asc' | 'desc';
  max_distance: string;
  page: number;
  category: string;
  price_min: string;
  price_max: string;
  drive_type?: string;
  completeness?: string;
  shipping_available?: boolean;
  price_indicator?: string;
  model_type?: string;
  model_subtype?: string;
}
```

**Step 2: Update `readFiltersFromParams`**

After `price_indicator: params.get('price_indicator') ?? undefined,`, add:

```typescript
model_type: params.get('model_type') ?? undefined,
model_subtype: params.get('model_subtype') ?? undefined,
```

**Step 3: Update `writeFiltersToParams`**

After `if (filter.price_indicator) p.set('price_indicator', filter.price_indicator);`, add:

```typescript
if (filter.model_type) p.set('model_type', filter.model_type);
if (filter.model_subtype) p.set('model_subtype', filter.model_subtype);
```

**Step 4: Update `getListings` call inside `useEffect` (in `useListings`)**

After `price_indicator: filter.price_indicator,`, add:

```typescript
model_type: filter.model_type,
model_subtype: filter.model_subtype,
```

**Step 5: Update useEffect dependency array in `useListings`**

After `filter.price_indicator,`, add:

```typescript
filter.model_type,
filter.model_subtype,
```

**Step 6: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 7: Commit**

```bash
git add frontend/src/hooks/useListings.ts
git commit -m "feat(hook): add model_type/model_subtype to ListingsFilter and useListings"
```

---

## Task 6: useInfiniteListings — wire model_type/model_subtype [ ]

**Depends on:** Task 5

**Files:**
- Modify: `frontend/src/hooks/useInfiniteListings.ts`

`useInfiniteListings` is the hook actually used by `ListingsPage`. It re-implements change detection, destructuring, API calls, and filter reconstruction — all must include the two new fields.

**Step 1: Extend `filterRef` initializer (lines 48–61)**

Add two lines before the closing `}`:

```typescript
const filterRef = useRef({
  search: urlFilter.search,
  plz: urlFilter.plz,
  sort: urlFilter.sort,
  sort_dir: urlFilter.sort_dir,
  max_distance: urlFilter.max_distance,
  category: urlFilter.category,
  price_min: urlFilter.price_min,
  price_max: urlFilter.price_max,
  drive_type: urlFilter.drive_type,
  completeness: urlFilter.completeness,
  shipping_available: urlFilter.shipping_available,
  price_indicator: urlFilter.price_indicator,
  model_type: urlFilter.model_type,
  model_subtype: urlFilter.model_subtype,
});
```

**Step 2: Extend `filterChanged` comparison (lines 66–78)**

Add two comparison lines after `prevFilter.price_indicator !== urlFilter.price_indicator`:

```typescript
const filterChanged =
  prevFilter.search !== urlFilter.search ||
  prevFilter.plz !== urlFilter.plz ||
  prevFilter.sort !== urlFilter.sort ||
  prevFilter.sort_dir !== urlFilter.sort_dir ||
  prevFilter.max_distance !== urlFilter.max_distance ||
  prevFilter.category !== urlFilter.category ||
  prevFilter.price_min !== urlFilter.price_min ||
  prevFilter.price_max !== urlFilter.price_max ||
  prevFilter.drive_type !== urlFilter.drive_type ||
  prevFilter.completeness !== urlFilter.completeness ||
  prevFilter.shipping_available !== urlFilter.shipping_available ||
  prevFilter.price_indicator !== urlFilter.price_indicator ||
  prevFilter.model_type !== urlFilter.model_type ||
  prevFilter.model_subtype !== urlFilter.model_subtype;
```

**Step 3: Extend `filterRef.current` reassignment (lines 81–94)**

Add two lines before closing `}`:

```typescript
filterRef.current = {
  search: urlFilter.search,
  plz: urlFilter.plz,
  sort: urlFilter.sort,
  sort_dir: urlFilter.sort_dir,
  max_distance: urlFilter.max_distance,
  category: urlFilter.category,
  price_min: urlFilter.price_min,
  price_max: urlFilter.price_max,
  drive_type: urlFilter.drive_type,
  completeness: urlFilter.completeness,
  shipping_available: urlFilter.shipping_available,
  price_indicator: urlFilter.price_indicator,
  model_type: urlFilter.model_type,
  model_subtype: urlFilter.model_subtype,
};
```

**Step 4: Extend destructuring (line 106)**

Replace the existing destructure line with:

```typescript
const { search, plz, sort, sort_dir, max_distance, category, price_min, price_max, drive_type, completeness, shipping_available, price_indicator, model_type, model_subtype } = filterRef.current;
```

**Step 5: Extend `getListings` call (lines 131–146)**

After `price_indicator,`, add:

```typescript
model_type,
model_subtype,
```

**Step 6: Extend `useEffect` dependency array (line 169)**

After `price_indicator` in the deps array, add:

```
, model_type, model_subtype
```

The full updated comment line:

```typescript
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [page, search, plz, sort, sort_dir, max_distance, category, price_min, price_max, drive_type, completeness, shipping_available, price_indicator, model_type, model_subtype]);
```

**Step 7: Extend returned `filter` object (lines 218–232)**

After `price_indicator: urlFilter.price_indicator,`, add:

```typescript
model_type: urlFilter.model_type,
model_subtype: urlFilter.model_subtype,
```

**Step 8: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 9: Commit**

```bash
git add frontend/src/hooks/useInfiniteListings.ts
git commit -m "feat(hook): wire model_type/model_subtype through useInfiniteListings"
```

---

## Task 7: FilterPanel UI [ ]

**Depends on:** Task 6

**Reuse check:** No existing pattern for dependent dropdowns found in this codebase.

**Files:**
- Modify: `frontend/src/components/FilterPanel.tsx`
- Modify: `frontend/src/components/__tests__/FilterPanel.test.tsx`

**Step 1: Update `hasSecondaryFilters`**

Extend the expression (around line 52):

```typescript
const hasSecondaryFilters =
  filter.category !== 'all' || !!filter.max_distance || filter.sort !== 'date' ||
  filter.sort_dir !== 'desc' || !!filter.price_min || !!filter.price_max ||
  filter.shipping_available === true || !!filter.price_indicator ||
  !!filter.drive_type || !!filter.completeness ||
  !!filter.model_type || !!filter.model_subtype;
```

**Step 2: Add imports**

After the existing imports at the top of `FilterPanel.tsx`, add:

```typescript
import { MODEL_SUBTYPES, MODEL_TYPE_LABELS, CATEGORY_MODEL_TYPES } from '../constants/vocabulary';
import type { ModelType } from '../constants/vocabulary';
```

Also add `CATEGORY_MODEL_TYPES` to `frontend/src/constants/vocabulary.ts` (extend Task 2's file):

```typescript
// Which model_types are meaningful for each category.
// rc-cars → only car, schiffsmodelle → only boat are fully implied by the category
// and hidden to avoid redundancy. flugmodelle and "all"/other categories show all flying types.
export const CATEGORY_MODEL_TYPES: Partial<Record<string, ModelType[]>> = {
  flugmodelle:    ['airplane', 'helicopter', 'multicopter', 'glider'],
  rc-cars:        [],   // fully implied by category — section hidden
  schiffsmodelle: [],   // fully implied by category — section hidden
};

// Returns the model_types to show for the given category key.
// Returns all 6 types for categories without a mapping (antriebstechnik, rc-elektronik, etc.)
export function availableModelTypes(category: string): ModelType[] {
  if (category in CATEGORY_MODEL_TYPES) {
    return CATEGORY_MODEL_TYPES[category] ?? [];
  }
  return [...MODEL_TYPES];
}
```

**Step 3: Add Typ + Subtyp sections in the mobile bottom sheet modal**

Add the following after the closing `</div>` of the "Preis-Bewertung" section and before the outer content `</div>` (around line 272).

The `availableModelTypes` helper drives which types appear. When the list is empty (rc-cars, schiffsmodelle), the entire section is hidden — model_type is fully implied by the category.

```tsx
{/* Modelltyp — hidden when category already implies the type */}
{(() => {
  const types = availableModelTypes(filter.category);
  if (types.length === 0) return null;
  return (
    <div>
      <p className={sectionLabel} style={sectionLabelColor}>Modelltyp</p>
      <select
        value={filter.model_type ?? ''}
        onChange={(e) => {
          const val = e.target.value as ModelType | '';
          onChange({
            ...filter,
            model_type: val || undefined,
            model_subtype: undefined,
            page: 1,
          });
        }}
        className={`w-full px-4 py-3 rounded-xl ${inputClass} appearance-none cursor-pointer`}
        style={inputStyle}
        aria-label="Modelltyp"
      >
        <option value="" style={{ background: '#0f0f23' }}>Alle Typen</option>
        {types.map((t) => (
          <option key={t} value={t} style={{ background: '#0f0f23' }}>
            {MODEL_TYPE_LABELS[t]}
          </option>
        ))}
      </select>
    </div>
  );
})()}

{/* Subtyp */}
<div>
  <p className={sectionLabel} style={sectionLabelColor}>Subtyp</p>
  <select
    value={filter.model_subtype ?? ''}
    onChange={(e) => {
      onChange({ ...filter, model_subtype: e.target.value || undefined, page: 1 });
    }}
    disabled={!filter.model_type}
    className={`w-full px-4 py-3 rounded-xl ${inputClass} appearance-none cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed`}
    style={inputStyle}
    aria-label="Subtyp"
  >
    <option value="" style={{ background: '#0f0f23' }}>Alle Subtypen</option>
    {filter.model_type &&
      MODEL_SUBTYPES[filter.model_type as ModelType]?.map((s) => (
        <option key={s} value={s} style={{ background: '#0f0f23' }}>
          {s}
        </option>
      ))}
  </select>
</div>
```

**Step 4: Update FilterPanel test — extend `defaultFilter`**

Replace the existing `defaultFilter` object in `FilterPanel.test.tsx`:

```typescript
const defaultFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  sort_dir: 'desc',
  max_distance: '',
  price_min: '',
  price_max: '',
  page: 1,
  category: 'all',
  model_type: undefined,
  model_subtype: undefined,
};
```

**Step 5: Add new tests**

Append to the `describe('FilterPanel')` block:

```typescript
it('renders Modelltyp select with empty default', () => {
  renderPanel();
  const select = screen.getByRole('combobox', { name: /Modelltyp/i });
  expect(select).toBeInTheDocument();
  expect((select as HTMLSelectElement).value).toBe('');
});

it('Subtyp select is disabled when no model_type is selected', () => {
  renderPanel();
  expect(screen.getByRole('combobox', { name: /Subtyp/i })).toBeDisabled();
});

it('selecting a model_type resets model_subtype and emits correct filter', () => {
  const onChange = vi.fn();
  renderPanel({ ...defaultFilter }, onChange);
  fireEvent.change(screen.getByRole('combobox', { name: /Modelltyp/i }), { target: { value: 'airplane' } });
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ model_type: 'airplane', model_subtype: undefined, page: 1 }),
  );
});

it('Subtyp select is enabled when model_type is set', () => {
  renderPanel({ ...defaultFilter, model_type: 'glider' });
  expect(screen.getByRole('combobox', { name: /Subtyp/i })).not.toBeDisabled();
});

it('selecting "Alle Typen" clears model_type', () => {
  const onChange = vi.fn();
  renderPanel({ ...defaultFilter, model_type: 'boat' }, onChange);
  fireEvent.change(screen.getByRole('combobox', { name: /Modelltyp/i }), { target: { value: '' } });
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ model_type: undefined, model_subtype: undefined }),
  );
});
```

**Step 6: Run tests**

```bash
cd frontend && npx vitest run src/components/__tests__/FilterPanel.test.tsx
```

Expected: all tests pass.

**Step 7: Commit**

```bash
git add frontend/src/components/FilterPanel.tsx
git add frontend/src/components/__tests__/FilterPanel.test.tsx
git commit -m "feat(ui): add model_type/subtype filter dropdowns to FilterPanel"
```

---

## Verification

**Run all frontend tests:**

```bash
cd frontend && npx vitest run
```

Expected: all tests pass.

**Check TypeScript:**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Rebuild Docker:**

```bash
docker compose up --build -d
```

**Smoke-test the backend filter via curl (requires listings with model_type data in DB):**

```bash
# All listings (no filter)
curl -s "http://localhost:8000/api/listings" | python -m json.tool | grep '"total"'

# Filtered by model_type=airplane
curl -s "http://localhost:8000/api/listings?model_type=airplane" | python -m json.tool | grep '"total"'
```

Expected: the second total is ≤ the first. If the DB has airplane listings, total > 0.

**Manual UI smoke test (DevTools → mobile emulation, or mobile device):**

Open `http://localhost:4200`:

1. Tap the filter icon → bottom sheet opens.
2. "Modelltyp" dropdown shows 6 types with German labels.
3. "Subtyp" dropdown is disabled before a type is selected.
4. Select "Flugzeug" → Subtyp enables and shows airplane-specific options.
5. Select a subtype (e.g. "jet") → URL updates to `?model_type=airplane&model_subtype=jet`.
6. Listing count changes to reflect the filter.
7. Refresh the page → both dropdowns restore from URL.
8. Select "Alle Typen" in Modelltyp → Subtyp resets to empty and both params disappear from URL.
