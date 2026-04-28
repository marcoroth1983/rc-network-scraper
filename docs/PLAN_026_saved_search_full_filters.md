# Saved Searches: vollständige Filter-Persistenz Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Beim Speichern und Laden einer Suche werden alle aktiven Filter (Modelltyp, Subtyp, Preisspanne, Antrieb, Vollständigkeit, Versand, Ansicht-Toggles) persistiert und wiederhergestellt — nicht nur PLZ/Distanz/Sort/Kategorie/Suchbegriff.

**Architecture:** Erweiterung des bestehenden Schemas mit Einzelspalten (konsistent zum aktuellen `SavedSearch`-Modell). Frontend serialisiert vollständigen Filter-State in den Save/Update-Payload; bei Aktivierung schreibt App alle Felder als URL-Parameter zurück. `criteriaChanged` (Drift-Detection) erweitert sich entsprechend.

**Tech Stack:** Python 3.12 / SQLAlchemy 2 (async), FastAPI / Pydantic v2, React 18 / TypeScript, PostgreSQL 16.

**Breaking Changes:** Ja (DB-Schema). `saved_searches` bekommt 9 neue Spalten. Dev: `Base.metadata.create_all` legt nur **neue Tabellen** an, ändert keine bestehenden — Dev-DB muss einmalig neu erstellt werden (`docker compose down -v && docker compose up -d`). Prod (VPS staging): einmaliges manuelles `ALTER TABLE` per SSH (siehe Verification). Bestehende gespeicherte Suchen behalten ihre Werte; neue Spalten sind NULL/false-default → kein Datenverlust.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-28 |
| Human | approved | 2026-04-28 |

---

## Context

### Bug
- Setze Filter `model_type=flugzeug`, `model_subtype=jet`, sort `distance asc`, PLZ + Distanz; speichere Suche.
- Persistiert wird nur PLZ + max_distance + sort + sort_dir + (search/category falls gesetzt).
- `model_type`/`model_subtype` und sechs weitere Filterfelder gehen verloren.

### Root Cause (verifiziert)
- **Frontend** (`frontend/src/pages/ListingsPage.tsx:155-179`): `handleSave()` und `handleUpdate()` bauen einen minimalen Payload (`search, plz, max_distance, sort, sort_dir, category`). Alle anderen Felder fehlen, obwohl sie im Filter-State leben (`useListings.ts:6-23`) und beim normalen Listings-Fetch mitgeschickt werden (`useInfiniteListings.ts:113-121`).
- **Backend-Schema** (`backend/app/api/schemas.py:143-184`): `SavedSearchCreate`/`SavedSearchUpdate` kennen nur die genannten 6 Felder.
- **Backend-Modell** (`backend/app/models.py:97-115`): `SavedSearch`-ORM hat keine Spalten für die fehlenden Felder.
- **Backend-Routen** (`backend/app/api/routes.py:579-588, 633-639`): `create_search`/`update_search` lesen nur die 6 Felder.
- **Frontend-Aktivierung** (`frontend/src/App.tsx:79-96`): `handleActivateSearch` schreibt nur 5 URL-Parameter (`search, plz, sort, sort_dir, max_distance`) — selbst wenn das Backend die Felder lieferte, würden sie beim Klick auf eine gespeicherte Suche nicht in die URL/State zurückgeschrieben.
- **Drift-Detection** (`frontend/src/pages/ListingsPage.tsx:62-77`): `criteriaChanged` vergleicht nur die alten 5 Felder → "Update verfügbar"-Hinweis (`showUpdate`) reagiert nicht auf Änderungen der neuen Felder.

### Felder im Scope (alle aus `ListingsFilter` in `useListings.ts:6-23`)
| Feld | TS-Typ | Pydantic-Typ | DB-Typ |
|---|---|---|---|
| `price_min` | `string` (URL) → `number\|null` (API) | `float \| None` | `Float` nullable |
| `price_max` | `string` → `number\|null` | `float \| None` | `Float` nullable |
| `drive_type` | `string \| undefined` | `str \| None` | `String(50)` nullable |
| `completeness` | `string \| undefined` | `str \| None` | `String(50)` nullable |
| `shipping_available` | `boolean \| undefined` | `bool \| None` | `Boolean` nullable |
| `model_type` | `string \| undefined` | `str \| None` | `String(50)` nullable |
| `model_subtype` | `string \| undefined` | `str \| None` | `String(50)` nullable |
| `show_outdated` | `boolean \| undefined` | `bool \| None` | `Boolean` nullable |
| `only_sold` | `boolean \| undefined` | `bool \| None` | `Boolean` nullable |

`Float` gewählt (statt `Numeric`), da Pydantic `float | None` direkt mappt und keine Rechenoperationen auf den Preisen laufen — vermeidet `Decimal`/`float`-Coercion am Read-Path.

### Out of Scope
- **Notification-Matcher** (`backend/app/services/search_matcher.py`): nutzt aktuell nur `search`, `category`, `plz`, `max_distance`. Erweiterung auf neue Felder ist eine separate Entscheidung — Backlog-Hinweis am Plan-Ende, KEINE Implementierung in diesem Plan. Begründung: Matcher-Erweiterung würde Tests in `test_search_matcher.py` zwingend mitziehen und ist konzeptionell eine andere Frage (was triggert eine Benachrichtigung).
- **Sortierung**: `sort` und `sort_dir` werden bereits korrekt persistiert.
- **Datenmigration alter Suchen**: bestehende Reihen behalten NULL — gewünschtes Verhalten (kein Filter).
- **Format-Validierung** der neuen Felder über die DB-Spalte hinaus (z. B. `drive_type` ∈ Enum-Liste): gehört in eine separate Validierungs-Initiative, nicht hier.

### Verifizierte Vorhandene Stellen
- `Base.metadata.create_all` Setup: `backend/app/db.py:24` (kein Alembic).
- Tests: `backend/tests/test_saved_searches.py` existiert, deckt Create/Update CRUD bereits ab.
- Frontend-Typen: `frontend/src/types/api.ts:152-176` (`SearchCriteria`, `SavedSearch`).
- `writeFiltersToParams` (`useListings.ts:78-99`) schreibt bereits alle Felder als URL-Params — `handleActivateSearch` muss dieselbe Logik nutzen statt eigene Liste.

---

## Tasks

### Task 1: ORM-Modell erweitern [ ]

**Files:**
- Modify: `backend/app/models.py:97-115`

**Step 1: Spalten ergänzen**

In `class SavedSearch` nach `category`-Spalte (Zeile 109) einfügen:

```python
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    drive_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completeness: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shipping_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    show_outdated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    only_sold: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

`Float` aus SQLAlchemy ergänzen (aktuell nicht importiert; verifiziert per Read am Datei-Kopf):

```python
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
```

**Step 2: Commit**

```bash
git add backend/app/models.py
git commit -m "feat(saved-searches): add filter columns to SavedSearch model"
```

---

### Task 2: Pydantic-Schemata erweitern [ ]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/api/schemas.py:143-203`

**Step 1: `SavedSearchCreate` erweitern**

Nach `category` (Zeile 149) ergänzen, vor den Validators:

```python
    price_min: float | None = None
    price_max: float | None = None
    drive_type: str | None = None
    completeness: str | None = None
    shipping_available: bool | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    show_outdated: bool | None = None
    only_sold: bool | None = None
```

**Step 2: `SavedSearchUpdate` identisch erweitern** (`schemas.py:165-184`).

**Step 3: `SavedSearchResponse` erweitern** (`schemas.py:187-203`) — alle 9 Felder hinzufügen, jeweils mit `= None` Default damit ältere DB-Reihen ohne Werte serialisierbar bleiben:

```python
    price_min: float | None = None
    price_max: float | None = None
    drive_type: str | None = None
    completeness: str | None = None
    shipping_available: bool | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    show_outdated: bool | None = None
    only_sold: bool | None = None
```

**Step 4: Commit**

```bash
git add backend/app/api/schemas.py
git commit -m "feat(saved-searches): add filter fields to Create/Update/Response schemas"
```

---

### Task 3: Routen-Persistenz [ ]

**Depends on:** Task 2

**Files:**
- Modify: `backend/app/api/routes.py:579-588` (`create_search`)
- Modify: `backend/app/api/routes.py:633-639` (`update_search`)

**Step 1: `create_search` — `SavedSearch(...)`-Konstruktor um neue Felder erweitern**

Nach `category=body.category,` einfügen:

```python
        price_min=body.price_min,
        price_max=body.price_max,
        drive_type=body.drive_type,
        completeness=body.completeness,
        shipping_available=body.shipping_available,
        model_type=body.model_type,
        model_subtype=body.model_subtype,
        show_outdated=body.show_outdated,
        only_sold=body.only_sold,
```

**Step 2: `update_search` — Zuweisungen ergänzen**

Nach `saved.category = body.category` einfügen:

```python
    saved.price_min = body.price_min
    saved.price_max = body.price_max
    saved.drive_type = body.drive_type
    saved.completeness = body.completeness
    saved.shipping_available = body.shipping_available
    saved.model_type = body.model_type
    saved.model_subtype = body.model_subtype
    saved.show_outdated = body.show_outdated
    saved.only_sold = body.only_sold
```

**Step 3: Commit**

```bash
git add backend/app/api/routes.py
git commit -m "feat(saved-searches): persist all filter fields in create/update routes"
```

---

### Task 4: Backend-Tests [ ]

**Depends on:** Task 3

**Files:**
- Modify: `backend/tests/test_saved_searches.py`

**Step 1: Drei Tests am Ende der Datei ergänzen**

```python
@pytest.mark.asyncio
async def test_create_search_persists_all_filter_fields(api_client: AsyncClient):
    """POST /api/searches mit allen Feldern → alle in Response zurückgegeben."""
    payload = {
        "search": "Multiplex",
        "model_type": "flugzeug",
        "model_subtype": "Jet",
        "price_min": 100.0,
        "price_max": 500.0,
        "drive_type": "elektro",
        "completeness": "rtf",
        "shipping_available": True,
        "show_outdated": False,
        "only_sold": True,
        "sort": "distance",
        "sort_dir": "asc",
    }
    resp = await api_client.post("/api/searches", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["model_type"] == "flugzeug"
    assert data["model_subtype"] == "Jet"
    assert data["price_min"] == 100.0
    assert data["price_max"] == 500.0
    assert data["drive_type"] == "elektro"
    assert data["completeness"] == "rtf"
    assert data["shipping_available"] is True
    assert data["show_outdated"] is False
    assert data["only_sold"] is True


@pytest.mark.asyncio
async def test_update_search_overwrites_filter_fields(api_client: AsyncClient):
    """PUT /api/searches/{id} ersetzt alle Filter-Felder (auch zurück auf None)."""
    create = await api_client.post(
        "/api/searches",
        json={"search": "x", "model_type": "flugzeug", "model_subtype": "Jet", "price_min": 50.0},
    )
    sid = create.json()["id"]

    update = await api_client.put(
        f"/api/searches/{sid}",
        json={"search": "x", "model_type": "auto", "model_subtype": None, "price_min": None},
    )
    assert update.status_code == 200
    data = update.json()
    assert data["model_type"] == "auto"
    assert data["model_subtype"] is None
    assert data["price_min"] is None


@pytest.mark.asyncio
async def test_create_search_omitted_filter_fields_default_to_null(api_client: AsyncClient):
    """POST /api/searches ohne Filter-Felder → alle neuen Felder NULL/None."""
    resp = await api_client.post("/api/searches", json={"search": "y"})
    assert resp.status_code == 201
    data = resp.json()
    for field in (
        "price_min", "price_max", "drive_type", "completeness",
        "shipping_available", "model_type", "model_subtype",
        "show_outdated", "only_sold",
    ):
        assert data[field] is None, f"{field} should default to None"
```

**Step 2: Commit**

```bash
git add backend/tests/test_saved_searches.py
git commit -m "test(saved-searches): cover full filter-field persistence"
```

---

### Task 5: Frontend-Typen erweitern [ ]

**Depends on:** Task 2

**Files:**
- Modify: `frontend/src/types/api.ts:152-176`

**Step 1: `SearchCriteria` erweitern**

Nach `category?: string;` (Zeile 158) einfügen:

```typescript
  price_min?: number | null;
  price_max?: number | null;
  drive_type?: string | null;
  completeness?: string | null;
  shipping_available?: boolean | null;
  model_type?: string | null;
  model_subtype?: string | null;
  show_outdated?: boolean | null;
  only_sold?: boolean | null;
```

**Step 2: `SavedSearch` erweitern**

Nach `category?: string | null;` (Zeile 175) dieselben 9 Felder einfügen (Typ identisch, da Response = Create-Felder).

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat(saved-searches): extend SearchCriteria and SavedSearch types"
```

---

### Task 6: Helper-Modul `savedSearchCriteria.ts` anlegen [ ]

**Depends on:** Task 5

**Files:**
- Create: `frontend/src/lib/savedSearchCriteria.ts`

**Reuse check:** Neuer Helper, kein bestehender Pattern dafür. Wird in Tasks 7, 8, 9 importiert (single source of truth). Verzeichnis `frontend/src/lib/` existiert prüfen — falls nicht, erstellen.

**Step 1: Datei anlegen**

```typescript
import type { ListingsFilter } from '../hooks/useListings';
import type { SavedSearch, SearchCriteria } from '../types/api';

/** Serialise the in-app filter state into the API payload for save/update. */
export function criteriaFromFilter(filter: ListingsFilter): SearchCriteria {
  return {
    search: filter.search || null,
    plz: filter.plz || null,
    max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
    sort: filter.sort,
    sort_dir: filter.sort_dir,
    // undefined (not "all") so the backend stores NULL for "all categories"
    category: filter.category !== 'all' ? filter.category : undefined,
    price_min: filter.price_min ? parseFloat(filter.price_min) : null,
    price_max: filter.price_max ? parseFloat(filter.price_max) : null,
    drive_type: filter.drive_type ?? null,
    completeness: filter.completeness ?? null,
    shipping_available: filter.shipping_available ?? null,
    model_type: filter.model_type ?? null,
    model_subtype: filter.model_subtype ?? null,
    show_outdated: filter.show_outdated ?? null,
    only_sold: filter.only_sold ?? null,
  };
}

/** Hydrate a ListingsFilter from a SavedSearch row.
 *
 * `currentCategory` is intentionally passed in (rather than read from the saved
 * row) because saved searches do not override the user's currently selected
 * category — that lives in localStorage and is global to the listings UI. */
export function filterFromSavedSearch(saved: SavedSearch, currentCategory: string): ListingsFilter {
  const sort: ListingsFilter['sort'] =
    saved.sort === 'price' || saved.sort === 'distance' ? saved.sort : 'date';
  const sort_dir: 'asc' | 'desc' = saved.sort_dir === 'asc' ? 'asc' : 'desc';
  return {
    search: saved.search ?? '',
    plz: saved.plz ?? '',
    sort,
    sort_dir,
    max_distance: saved.max_distance != null ? String(saved.max_distance) : '',
    page: 1,
    category: currentCategory,
    price_min: saved.price_min != null ? String(saved.price_min) : '',
    price_max: saved.price_max != null ? String(saved.price_max) : '',
    drive_type: saved.drive_type ?? undefined,
    completeness: saved.completeness ?? undefined,
    shipping_available: saved.shipping_available ?? undefined,
    model_type: saved.model_type ?? undefined,
    model_subtype: saved.model_subtype ?? undefined,
    show_outdated: saved.show_outdated ?? undefined,
    only_sold: saved.only_sold ?? undefined,
  };
}

/** Returns true if the live filter differs from the saved search criteria. */
export function criteriaDiffers(filter: ListingsFilter, saved: SavedSearch): boolean {
  const a = criteriaFromFilter(filter);
  // Compare against the same shape the backend would receive on update.
  const b = criteriaFromFilter(filterFromSavedSearch(saved, filter.category));
  const keys = Object.keys(a) as (keyof SearchCriteria)[];
  return keys.some((k) => (a[k] ?? null) !== (b[k] ?? null));
}
```

`SearchCriteria` und `SavedSearch` müssen nach Task 5 die neuen Felder enthalten — sonst tsc-Fehler.

**Step 2: Commit**

```bash
git add frontend/src/lib/savedSearchCriteria.ts
git commit -m "feat(saved-searches): add criteriaFromFilter / filterFromSavedSearch helpers"
```

---

### Task 7: `writeFiltersToParams` refactoren — pure Funktion [ ]

**Depends on:** Task 5

**Files:**
- Modify: `frontend/src/hooks/useListings.ts:78-99`
- Modify: `frontend/src/hooks/useListings.ts:117-119` (Aufrufer in `useListings`)
- Modify: `frontend/src/hooks/useInfiniteListings.ts:155-161` (Aufrufer in `useInfiniteListings`)

**Reuse check:** Eine einzige bestehende Implementierung in `useListings.ts`. Refactor zu reiner Funktion eliminiert die Setter-Indirection und macht den Helper auch in `App.tsx` ohne Tricks nutzbar.

**Step 1: Signatur ändern — `URLSearchParams` zurückgeben**

`useListings.ts:78-99` durch:

```typescript
export function writeFiltersToParams(filter: ListingsFilter): URLSearchParams {
  const p = new URLSearchParams();
  if (filter.search) p.set('search', filter.search);
  if (filter.plz) p.set('plz', filter.plz);
  if (filter.sort !== 'date') p.set('sort', filter.sort);
  if (filter.sort_dir !== 'desc') p.set('sort_dir', filter.sort_dir);
  if (filter.max_distance) p.set('max_distance', filter.max_distance);
  if (filter.price_min) p.set('price_min', filter.price_min);
  if (filter.price_max) p.set('price_max', filter.price_max);
  if (filter.drive_type) p.set('drive_type', filter.drive_type);
  if (filter.completeness) p.set('completeness', filter.completeness);
  if (filter.shipping_available != null) p.set('shipping_available', String(filter.shipping_available));
  if (filter.model_type) p.set('model_type', filter.model_type);
  if (filter.model_subtype) p.set('model_subtype', filter.model_subtype);
  if (filter.show_outdated) p.set('show_outdated', 'true');
  if (filter.only_sold) p.set('only_sold', 'true');
  if (filter.page > 1) p.set('page', String(filter.page));
  return p;
}
```

**Step 2: Aufrufer in `useListings.ts:117-119` anpassen**

```typescript
const setFilter = useCallback((next: ListingsFilter) => {
  setSearchParams(writeFiltersToParams(next));
}, [setSearchParams]);
```

**Step 3: Aufrufer in `useInfiniteListings.ts:155-161` anpassen**

```typescript
const setFilter = useCallback(
  (next: Omit<ListingsFilter, 'page'>) => {
    setSearchParams(writeFiltersToParams({ ...next, page: 1 }));
  },
  [setSearchParams],
);
```

**Step 4: Commit**

```bash
git add frontend/src/hooks/useListings.ts frontend/src/hooks/useInfiniteListings.ts
git commit -m "refactor(filters): writeFiltersToParams returns URLSearchParams"
```

---

### Task 8: Save/Update + Aktivierung + Drift nutzen Helper-Modul [ ]

**Depends on:** Task 6, Task 7

**Files:**
- Modify: `frontend/src/pages/ListingsPage.tsx:62-77` (entferne lokales `criteriaChanged`)
- Modify: `frontend/src/pages/ListingsPage.tsx:140-179` (`handleSave`, `handleUpdate`, `hasCriteriaChanged`)
- Modify: `frontend/src/App.tsx:79-96` (`handleActivateSearch`)

**Step 1: ListingsPage.tsx — lokales `criteriaChanged` ersetzen**

Funktion `criteriaChanged` (Zeile 62-77) löschen. Imports am Datei-Kopf erweitern:

```typescript
import { criteriaFromFilter, criteriaDiffers } from '../lib/savedSearchCriteria';
```

`hasCriteriaChanged`-Berechnung (Zeile 139-142) ersetzen durch:

```typescript
const hasCriteriaChanged =
  isExistingSearch && activeSavedSearchCriteria != null
    ? criteriaDiffers(filter, activeSavedSearchCriteria)
    : false;
```

**Step 2: ListingsPage.tsx — `handleSave`/`handleUpdate`**

```typescript
async function handleSave() {
  await onSaveSearch(criteriaFromFilter(filter));
  showFeedback('saved');
}

async function handleUpdate() {
  if (activeSavedSearchId == null) return;
  await onUpdateSearch(activeSavedSearchId, criteriaFromFilter(filter));
  showFeedback('updated');
}
```

**Step 3: App.tsx — `handleActivateSearch` neu**

Imports erweitern:

```typescript
import { writeFiltersToParams } from './hooks/useListings';
import { filterFromSavedSearch } from './lib/savedSearchCriteria';
```

Funktion ersetzen:

```typescript
const handleActivateSearch = useCallback(
  (id: number, criteria: SearchCriteria) => {
    setActiveSavedSearchId(id);
    setFavoritesOpen(false);
    // Saved searches do not override the currently chosen category — preserve it.
    const currentCategory = localStorage.getItem('rcn_category') ?? 'all';
    // criteria is already a SavedSearch-shaped subset (Task 5 widened SearchCriteria).
    const f = filterFromSavedSearch(criteria as SavedSearch, currentCategory);
    const qs = writeFiltersToParams(f).toString();
    navigate(qs ? `/?${qs}` : '/');
  },
  [navigate],
);
```

`SavedSearch` aus `./types/api` importieren falls nicht schon vorhanden. Der Cast bleibt nötig, weil `handleActivateSearch` typisiert `SearchCriteria` annimmt; der Aufrufer (FavoritesModal/Page) übergibt aber tatsächlich ein `SavedSearch`. Alternative: Signatur auf `SavedSearch` umstellen — sauberer, prüfen welche Stelle aufruft.

**Hinweis Coder:** Falls die Aufruferseite (FavoritesModal) tatsächlich ein `SavedSearch`-Objekt übergibt, lieber die Signatur direkt auf `(id: number, saved: SavedSearch)` ändern und den Cast entfernen. `grep -n "handleActivateSearch\|onActivate" frontend/src/components/FavoritesModal.tsx frontend/src/pages/FavoritesPage.tsx` prüfen.

**Step 4: Commit**

```bash
git add frontend/src/pages/ListingsPage.tsx frontend/src/App.tsx
git commit -m "fix(saved-searches): persist and restore all filter fields end-to-end"
```

---

### Task 9: FavoritesModal/Page Anzeige (optional anzeigen) [ ]

**Depends on:** Task 5

**Files:**
- Modify: `frontend/src/components/FavoritesModal.tsx:55-59`
- Modify: `frontend/src/pages/FavoritesPage.tsx:53-57`

**Step 1: Filter-Summary in beiden Karten ergänzen**

In beiden Files baut `filterParts` bisher nur PLZ/Distanz/Sort. Ergänzen, jeweils nach `if (search.sort) ...`:

```typescript
if (search.model_type) filterParts.push(search.model_type);
if (search.model_subtype) filterParts.push(search.model_subtype);
if (search.price_min != null || search.price_max != null) {
  const lo = search.price_min ?? '';
  const hi = search.price_max ?? '';
  filterParts.push(`${lo}–${hi} €`);
}
if (search.drive_type) filterParts.push(search.drive_type);
if (search.completeness) filterParts.push(search.completeness);
if (search.shipping_available) filterParts.push('Versand');
if (search.only_sold) filterParts.push('Verkauft');
if (search.show_outdated) filterParts.push('inkl. veraltet');
```

`SavedSearch`-Felder sind nach Task 5 verfügbar.

**Step 2: Commit**

```bash
git add frontend/src/components/FavoritesModal.tsx frontend/src/pages/FavoritesPage.tsx
git commit -m "feat(saved-searches): show extended filter summary on saved-search cards"
```

---

### Task 10: Frontend-Tests für Helper-Modul [ ]

**Depends on:** Task 8

**Files:**
- Create: `frontend/src/lib/savedSearchCriteria.test.ts`

**Step 1: Tests anlegen**

```typescript
import { describe, it, expect } from 'vitest';
import {
  criteriaFromFilter,
  filterFromSavedSearch,
  criteriaDiffers,
} from './savedSearchCriteria';
import type { ListingsFilter } from '../hooks/useListings';
import type { SavedSearch } from '../types/api';

const baseFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  sort_dir: 'desc',
  max_distance: '',
  page: 1,
  category: 'all',
  price_min: '',
  price_max: '',
};

const baseSaved: SavedSearch = {
  id: 1,
  user_id: 1,
  name: null,
  search: null,
  plz: null,
  max_distance: null,
  sort: 'date',
  sort_dir: 'desc',
  is_active: true,
  last_checked_at: null,
  last_viewed_at: null,
  created_at: '2026-04-28T00:00:00Z',
  match_count: 0,
  category: null,
};

describe('criteriaFromFilter', () => {
  it('serialises all filter fields including model_type/subtype', () => {
    const out = criteriaFromFilter({
      ...baseFilter,
      plz: '49356',
      sort: 'distance',
      sort_dir: 'asc',
      max_distance: '50',
      model_type: 'flugzeug',
      model_subtype: 'Jet',
    });
    expect(out.model_type).toBe('flugzeug');
    expect(out.model_subtype).toBe('Jet');
    expect(out.plz).toBe('49356');
    expect(out.sort).toBe('distance');
    expect(out.sort_dir).toBe('asc');
    expect(out.max_distance).toBe(50);
  });

  it('passes undefined for category="all"', () => {
    expect(criteriaFromFilter(baseFilter).category).toBeUndefined();
  });

  it('parses price strings into numbers', () => {
    const out = criteriaFromFilter({ ...baseFilter, price_min: '100', price_max: '500' });
    expect(out.price_min).toBe(100);
    expect(out.price_max).toBe(500);
  });
});

describe('filterFromSavedSearch', () => {
  it('hydrates ListingsFilter from a SavedSearch with full filter set', () => {
    const f = filterFromSavedSearch(
      {
        ...baseSaved,
        search: 'Multiplex',
        plz: '49356',
        max_distance: 50,
        sort: 'distance',
        sort_dir: 'asc',
        price_min: 100,
        price_max: 500,
        drive_type: 'elektro',
        completeness: 'rtf',
        shipping_available: true,
        model_type: 'flugzeug',
        model_subtype: 'Jet',
        show_outdated: false,
        only_sold: false,
      },
      'all',
    );
    expect(f.model_type).toBe('flugzeug');
    expect(f.model_subtype).toBe('Jet');
    expect(f.max_distance).toBe('50');
    expect(f.price_min).toBe('100');
    expect(f.sort).toBe('distance');
    expect(f.sort_dir).toBe('asc');
  });

  it('preserves currentCategory and ignores saved.category', () => {
    const f = filterFromSavedSearch({ ...baseSaved, category: 'flugzeuge' }, 'autos');
    expect(f.category).toBe('autos');
  });
});

describe('criteriaDiffers', () => {
  it('returns false when filter matches saved', () => {
    const saved = { ...baseSaved, model_type: 'flugzeug', model_subtype: 'Jet' };
    const filter = filterFromSavedSearch(saved, 'all');
    expect(criteriaDiffers(filter, saved)).toBe(false);
  });

  it('detects model_type change', () => {
    const saved = { ...baseSaved, model_type: 'flugzeug' };
    const filter = { ...filterFromSavedSearch(saved, 'all'), model_type: 'auto' };
    expect(criteriaDiffers(filter, saved)).toBe(true);
  });
});
```

**Step 2: Commit**

```bash
git add frontend/src/lib/savedSearchCriteria.test.ts
git commit -m "test(saved-searches): cover savedSearchCriteria helpers"
```

---

## Verification

**Vorbedingung Dev-DB Reset (einmalig)** — `Base.metadata.create_all` ergänzt keine Spalten an bestehenden Tabellen:

```bash
docker compose down -v
docker compose up -d
```

**Backend-Tests**

```bash
docker compose exec backend pytest tests/test_saved_searches.py -v
docker compose exec backend pytest tests/ -v
```

Erwartet: alle drei neuen Tests in Task 4 grün; bestehende Tests unverändert grün.

**Frontend-Tests** (`frontend/package.json:scripts.test = "vitest"` verifiziert):

```bash
cd frontend && pnpm test --run
```

**Manuelle UI-Verifikation** (Reproduktion des gemeldeten Bugs):

1. `docker compose up -d` + Frontend dev (`pnpm dev` aus `frontend/` oder dort konfiguriertes Kommando — package.json prüfen).
2. PLZ setzen, Modelltyp = "flugzeug", Subtyp = "Jet", Sort = Entfernung asc.
3. Suche speichern → in Merkliste/FavoritesModal: Karte zeigt "flugzeug, Jet, Entfernung ↑" (Task 9).
4. Filter zurücksetzen, Suche aus Merkliste aktivieren → URL enthält `model_type=flugzeug&model_subtype=Jet&sort=distance&sort_dir=asc&plz=...&max_distance=...`. FilterPanel zeigt die Werte.
5. Filter ändern (z. B. Subtyp leeren) → "Update"-Button erscheint (Drift-Detection, Task 8).
6. Update klicken → DB-Wert ändert sich, Aktivierung danach lädt den neuen Wert.

**Prod-Migration (VPS staging) — manuell durch Human nach Code-Merge**:

DB-User/Name vor Ausführung aus der VPS-Compose-Konfiguration ablesen — typischerweise `/opt/rcn-scout/.env` oder die `docker-compose.prod.yml` `db.environment.POSTGRES_USER` / `POSTGRES_DB`. SSH-Befehl zum Anzeigen:

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "grep -E 'POSTGRES_(USER|DB)' /opt/rcn-scout/.env || \
   docker inspect $(docker ps -qf name=db) --format '{{json .Config.Env}}' | tr ',' '\n' | grep POSTGRES"
```

Dann ALTER TABLE einspielen:

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3
docker compose -f /opt/rcn-scout/docker-compose.prod.yml exec db psql -U <user> -d <db> -c "
ALTER TABLE saved_searches
  ADD COLUMN price_min DOUBLE PRECISION,
  ADD COLUMN price_max DOUBLE PRECISION,
  ADD COLUMN drive_type VARCHAR(50),
  ADD COLUMN completeness VARCHAR(50),
  ADD COLUMN shipping_available BOOLEAN,
  ADD COLUMN model_type VARCHAR(50),
  ADD COLUMN model_subtype VARCHAR(50),
  ADD COLUMN show_outdated BOOLEAN,
  ADD COLUMN only_sold BOOLEAN;
"
```

`DOUBLE PRECISION` entspricht SQLAlchemy `Float`.

Bestehende Reihen erhalten NULL — `SavedSearchResponse` toleriert das (Defaults `= None`).

**Regressions-Check**: nach erfolgreicher Verification doc-Update prüfen:
- `docs/architektur.md`: enthält `SavedSearch`-Spaltenübersicht? Falls ja → ergänzen.
- `docs/limitations.md`: prüfen, ob ein Eintrag "Saved searches speichern nur 6 Felder" existiert → entfernen.

---

## Risiken / Trade-offs

- **Einzelspalten vs. JSON-Spalte**: Einzelspalten gewählt für Konsistenz mit Bestandsschema und einfachere Pydantic-Validierung. Trade-off: Jeder neue Filter braucht künftig wieder eine DB-Migration. Bei nächster Filter-Erweiterung (≥2 weitere Felder) JSON-Spalte erneut evaluieren.
- **`Float` (DOUBLE PRECISION) statt `Numeric`**: Pydantic mappt `float | None` direkt; `Numeric` würde `Decimal` liefern und zusätzliche Coercion am Read-Path verlangen. Kosten: minimaler Float-Drift bei Eingabe (z. B. 99.99 ≠ 99.99000000000001). Akzeptabel — Preise sind Eingabewerte, keine Rechengrößen.
- **Notification-Matcher unverändert**: Eine gespeicherte Suche mit `model_type=flugzeug` benachrichtigt den Nutzer aktuell auch für Nicht-Flugzeug-Listings. Bewusst out of scope — separater Plan, da Verhalten und Tests zu erweitern wären (`backend/app/services/search_matcher.py`, `backend/tests/test_search_matcher.py`). Backlog-Eintrag empfohlen: "PLAN_xxx: notification matcher honor extended saved-search filters".
- **Manuelle Prod-Migration**: kein Alembic im Projekt. Prod-DB hat Daten — `ALTER TABLE` muss vom Human einmalig ausgeführt werden. Alternative wäre Alembic-Einführung; out of scope für diesen Hobby-Fix.
- **`show_outdated`/`only_sold` werden persistiert**: konzeptionell Ansicht-Toggles, technisch Teil des Filter-States. Eingeschlossen, weil (a) Drift-Detection sie sonst special-casen müsste und (b) eine gespeicherte Suche andernfalls beim Reaktivieren ein anderes Result-Set zeigt als beim Speichern. Symmetrie schlägt konzeptionelle Reinheit.

---

## Backlog-Vermerke (nach Plan-Abschluss)

- Notification-Matcher-Erweiterung auf neue Saved-Search-Felder (eigener Plan).
- Bei nächster Filter-Hinzufügung: JSON-Spalte vs. weitere Einzelspalten neu evaluieren.

---

_Plan review closed 2026-04-28: 2 blocking + applicable non-blocking findings addressed; 1 blocking (status-field format) dismissed — `[ ]` markers are the canonical format defined by `dglabs.writing-plans` skill; reviewer's "required `status:` field" claim conflicts with the active skill spec._

_Code review closed 2026-04-28 (frontend, cycle 1): 2 medium addressed; 3 low deferred._

---

_Code review closed 2026-04-28 (python, cycle 1): 2 wichtig + 2 empfohlen addressed; 1 empfohlen (Numeric import) info-only._

<!-- Original review preserved below for reference until Human approval. -->

## Plan Review (closed)
<!-- dglabs.agent.review-plan — 2026-04-28 -->

> Codex Pass 2 was launched but did not produce a summary within the available wait window (job stalled after initial file inspection at the 16-minute mark). All findings below are from Pass 1 (agent review against the live codebase). Sources cite agent only.

### Structural Checklist
- [x] Required sections present (Goal, Breaking Changes, Tasks, Verification, Risks)
- [✗] Step status fields — tasks use `[ ]` checkboxes, not the required `status: open|implemented|reviewed|approved`
- [x] Step granularity suitable for fresh AI instance (largest task ~20 LOC; well within budget)
- [x] Test files named per step (Task 4: `backend/tests/test_saved_searches.py`; Task 10: `frontend/src/lib/savedSearchCriteria.test.ts`)
- [x] Breaking changes marked Yes with recovery (`docker compose down -v` dev; manual `ALTER TABLE` prod)
- [x] BREAK markers — none, but plan is short enough that a single end-of-plan verification gate is sufficient
- [x] Approval table present
- [✗] Internal contradiction: Tasks 6 & 7 place helpers in `ListingsPage.tsx` / `useListings.ts`, but Task 10 recommends extracting to `frontend/src/lib/savedSearchCriteria.ts`. The coder must decide twice or refactor mid-plan.

### 🔴 Blocking

1. **[Source: Agent]** — `docs/PLAN_026_*.md` Tasks 6, 7, 10 — **Unresolved helper-location contradiction.** Task 6 instructs the coder to add `criteriaFromFilter` inside `ListingsPage.tsx`. Task 7 adds `filterFromSavedSearch` inside `useListings.ts`. Task 10 then says "Empfehlung Coder: Helper nach `frontend/src/lib/savedSearchCriteria.ts` ziehen … bevorzugt" and writes the test against that module. This forces either (a) the coder duplicates helpers across two locations or (b) Task 10 silently rewrites Tasks 6/7's outputs. Decide upfront and fold it into Tasks 6/7: add helpers directly in `frontend/src/lib/savedSearchCriteria.ts` from the start, then import from `ListingsPage.tsx`, `App.tsx`, `useListings.ts`. Update Task 10 to reference the file as a given. Technical justification: a "soft recommendation" in a plan written for an autonomous executor is a coin flip — `dglabs.executing-plans` will not surface the choice for Human review.

2. **[Source: Agent]** — Task 7 `App.tsx:79-96` — **`writeFiltersToParams` setter abuse.** The setter signature is documented as "the new URLSearchParams to commit" (used as `setSearchParams` adapter). Passing a closure that copies keys into a captured local `p` object is functionally equivalent but semantically misleading; the next reader must trace the closure to realize `next` and `p` carry identical content. Two cleaner alternatives, pick one and pin it in the plan:
   - **Refactor (recommended):** change `writeFiltersToParams` to return `URLSearchParams` (no setter); call sites do `setSearchParams(writeFiltersToParams(filter))` and `App.tsx` does `const qs = writeFiltersToParams(filter).toString()`. One-line change in `useListings.ts:117-119`, removes the trick entirely.
   - **Inline:** in `App.tsx`, build `URLSearchParams` directly using the same field list. Slight duplication, but no setter contortion.
   The current Task 7 ships a confusing pattern that future readers will flag — the plan's own "Hinweis" admits the awkwardness. Technical justification: helper-reuse to avoid drift is a real win, but doing it via a misused setter signature trades one consistency hazard for another.

3. **[Source: Agent]** — Task structure — **Missing per-task `status` field** as required by the project's plan template (`open|implemented|reviewed|approved`). All ten tasks use `[ ]` checkboxes. The orchestrator (`dglabs.executing-plans`) and reviewer cannot machine-mark progress without it.

### 🟡 Non-Blocking

1. **[Source: Agent]** — `backend/app/models.py:90` — Verify `Numeric` is not yet imported before adding it. Current import line (`from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func`, file head) confirms `Numeric` is missing. Plan notes "falls nicht vorhanden" — accurate, just confirm during Step 1.

2. **[Source: Agent]** — Task 1 — **Float vs. Numeric typing.** SQLAlchemy `Numeric` without precision returns `Decimal`, but `Mapped[float | None]` will be a runtime mismatch when the row is read back (Pydantic v2 will coerce `Decimal` → `float` on serialization, so the API response is fine). For consistency with the rest of the table (no other Numeric columns there) consider `Float` instead, since the plan explicitly states "keine Rechenoperationen" and price drift is acceptable. Trade-off mentioned in Risks; flag here for Human awareness.

3. **[Source: Agent]** — Task 4 — **Authenticated test client.** `test_saved_searches.py` already exists and uses `api_client`. Plan should explicitly note that `api_client` is the authenticated fixture (per existing test patterns) so the coder doesn't introduce a different fixture by accident. Three new tests inherit auth from the file's existing fixtures — consistent.

4. **[Source: Agent]** — Task 6 — **`category` URL roundtrip.** `criteriaFromFilter` correctly excludes `"all"` for the API payload. Note: `writeFiltersToParams` (`useListings.ts:78-99`) does NOT write `category` to the URL — category lives only in `localStorage` (`useListings.ts:53`). Task 7's `filterFromSavedSearch` correctly preserves the current `localStorage` category, so the saved search's stored category is intentionally **not** restored on activation. Plan's comment ("Saved searches überschreiben die aktuell gewählte Kategorie nicht (Bestandsverhalten)") matches existing behavior. Make this explicit in `definition.md` if it isn't already, or add a backlog note: "Saved searches with category currently ignore the persisted category at activation time — by design (localStorage-driven category)".

5. **[Source: Agent]** — Task 8 — **Caller signature change.** `criteriaChanged(filter, activeSavedSearchCriteria)` at `ListingsPage.tsx:141` already passes the full `filter`; only the parameter type annotation needs widening (line 64). Plan handles this via "Aufrufer-Signatur: ... Auf `filter` (volles `ListingsFilter`) umstellen" — accurate but understated. The change is purely the type annotation; runtime behavior is correct.

6. **[Source: Agent]** — Task 9 — **`null`-safe price formatting.** `${lo}–${hi} €` when only one bound is set will render as e.g. `100– €` or `–500 €`. Acceptable for a summary chip but flag for UX polish (not a bug).

7. **[Source: Agent]** — `show_outdated` / `only_sold` persistence (Risks/Trade-offs) — **Recommend persisting both.** They're part of the React filter state and feed `criteriaChanged` already. Excluding them creates two foot-guns: (a) the user saves a search "show_outdated=true", reactivates next day, sees a different result set; (b) drift-detection has to special-case them. Symmetry over conceptual purity. Confirm with Human, but the engineering case is in favor.

8. **[Source: Agent]** — Verification — **`pnpm test --run` is correct.** `frontend/package.json:11` shows `"test": "vitest"`, and `pnpm test --run` forwards `--run` to vitest (one-shot mode). The plan's "if npm: check package.json" caveat is unnecessary belt-and-suspenders for this repo; remove it or keep, low cost either way.

9. **[Source: Agent]** — Out-of-Scope completeness — `useInfiniteListings.ts:104-122` already passes all 9 filter fields to the API on listings fetch (verified). No code change needed there; current OOS list is correct on this point.

10. **[Source: Agent]** — Task 7 — **`SearchCriteria` type does not yet contain the new fields.** Frontend `SavedSearch` type (Task 5 Step 2) gets the new fields, but `SearchCriteria` (Task 5 Step 1) also does. The `as Parameters<typeof filterFromSavedSearch>[0]` cast in Task 7 Step 2 is therefore unneeded once Task 5 lands — drop the cast, pass `criteria` directly. Simplifies the call site.

11. **[Source: Agent]** — Prod `ALTER TABLE` — DB user/name placeholders (`<user>`, `<db>`) — fine, but record where to look (Compose env or `.env` on VPS) to spare the Human a search at run time.

### Verdict

**REVISE** — Two architectural ambiguities (helper location split across Tasks 6/7/10, and the `writeFiltersToParams` setter abuse) plus a structural-template miss (missing `status:` fields). All three are mechanical to address; once fixed the plan should re-review fast.
