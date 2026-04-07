# Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Build a Kleinanzeigen-style React/TypeScript SPA for browsing RC airplane listings from the backend API, with search, distance filtering, sorting, and pagination.

**Architecture:** Single-page React 18 app with React Router 6 — two routes: `/` (listing grid with filters, pagination) and `/listings/:id` (detail view). Filter state lives exclusively in URL search params so browser back/forward works. User's reference PLZ is persisted to `localStorage` under key `rcn_ref_plz` and synced to URL. No external state management — useState + URL params only.

**Tech Stack:** React 18, TypeScript, Vite 5, Tailwind CSS 3 (postcss), React Router 6, Vitest + @testing-library/react.

**Breaking Changes:** No — adds `frontend/` directory and a `frontend` service to `docker-compose.yml`; no backend changes.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-06 |
| Human | approved | 2026-04-07 |

---

## API Surface (backend at http://localhost:8002)

### GET /api/listings
Query params: `page`(int,1), `per_page`(int,20), `search`(str|null), `sort`("date"|"price"|"distance"), `plz`(str|null), `max_distance`(int|null)

**Validation rules (enforced by backend, must guard on frontend too):**
- `sort=distance` requires `plz` → backend returns HTTP 400 if missing
- `max_distance` requires `plz` → backend returns HTTP 400 if missing

Response shape:
```json
{
  "total": 62,
  "page": 1,
  "per_page": 20,
  "items": [{
    "id": 130,
    "external_id": "12113834",
    "url": "https://www.rc-network.de/threads/...",
    "title": "F-18 LX Modells",
    "price": "280",
    "condition": "Gut",
    "plz": null,
    "city": "Würzburg",
    "latitude": null,
    "longitude": null,
    "author": "MI77",
    "posted_at": "2026-04-06T19:22:16Z",
    "scraped_at": "2026-04-06T20:54:50.935574Z",
    "distance_km": null
  }]
}
```

### GET /api/listings/{id}
Adds fields: `shipping` (str|null), `description` (str), `images` (string[]), `posted_at_raw` (str|null).

### GET /api/geo/plz/{plz}
Response: `{ plz, city, lat, lon }` — HTTP 404 if PLZ not found.

### POST /api/scrape?max_pages=10
Response: `{ pages_crawled, listings_found, new, updated, skipped }`
**IMPORTANT:** Synchronous and blocking — can take 40+ seconds. UI must show a loading/disabled state.

---

## File Structure

```
frontend/
├── index.html
├── package.json
├── vite.config.ts          # API proxy /api → backend (env var or localhost:8002)
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx             # React Router setup + header with ScrapeButton
│   ├── index.css           # Tailwind directives
│   ├── test-setup.ts       # jest-dom import
│   ├── types/
│   │   └── api.ts          # TypeScript interfaces
│   ├── api/
│   │   └── client.ts       # Typed fetch wrappers
│   ├── hooks/
│   │   └── useListings.ts  # Data fetching + URL param sync
│   ├── components/
│   │   ├── ListingCard.tsx
│   │   ├── FilterPanel.tsx
│   │   ├── Pagination.tsx
│   │   ├── ScrapeButton.tsx
│   │   └── __tests__/
│   │       ├── ListingCard.test.tsx
│   │       └── FilterPanel.test.tsx
│   └── pages/
│       ├── ListingsPage.tsx
│       └── DetailPage.tsx
```

---

## Design Rules

- Tailwind gray-based color scheme, cards with `shadow-sm` + hover `shadow-md`
- Responsive card grid: 1 col mobile, 2 col `md:`, 3 col `lg:`
- Null fields render as `–`, never "null" or "undefined"
- Price displayed as-is from backend (raw string like "480,00 EUR VB") — no parsing
- Distance displayed as e.g. "42.7 km" (1 decimal), `–` when null
- Language: German UI labels (`Suche`, `Zurück`, `Seite X von Y`, etc.)

---

### Task 1: Scaffold Vite + React + TS project [ ]

**Status:** open

**Files:**
- Create: `frontend/` (via npm create vite)
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/index.css`
- Create: `frontend/src/test-setup.ts`

**Step 1: Scaffold the Vite project**

From the repo root (`D:\DEVELOPMENT\_workplace_AI\rcn-scraper`):

```bash
npm create vite@latest frontend -- --template react-ts
```

Expected output:
```
Scaffolding project in .../rcn-scraper/frontend...
Done.
```

**Step 2: Install dependencies**

```bash
cd frontend && npm install react-router-dom
npm install -D tailwindcss@3 postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event @vitejs/plugin-react jsdom
```

Expected: all packages install without errors.

**Step 3: Initialize Tailwind**

```bash
npx tailwindcss init -p
```

Expected: creates `tailwind.config.js` and `postcss.config.js`.

**Step 4: Write `frontend/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

**Step 5: Write `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**Step 6: Write `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://localhost:8002',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
});
```

**Step 7: Write `frontend/src/test-setup.ts`**

```ts
import '@testing-library/jest-dom';
```

**Step 8: Add test scripts to `frontend/package.json`**

In the `"scripts"` section, add:
```json
"test": "vitest",
"test:ui": "vitest --ui"
```

**Step 9: Replace `frontend/src/main.tsx`**

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

**Step 10: Verify dev server starts**

```bash
cd frontend && npm run dev
```

Expected:
```
  VITE v5.x.x  ready in XXX ms
  ➜  Local:   http://localhost:5173/
```

**Step 11: Commit**

```bash
cd frontend && git add -A && git commit -m "feat(frontend): scaffold Vite+React+TS project with Tailwind and API proxy"
```

---

### Task 2: TypeScript types + API client [ ]

**Status:** open

**Depends on:** Task 1

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/api/client.ts`

**Step 1: Write `frontend/src/types/api.ts`**

```ts
export interface ListingSummary {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
  condition: string | null;
  plz: string | null;
  city: string | null;
  latitude: number | null;
  longitude: number | null;
  author: string;
  posted_at: string | null;   // ISO 8601 string
  scraped_at: string;          // ISO 8601 string
  distance_km: number | null;
}

export interface ListingDetail {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
  condition: string | null;
  shipping: string | null;
  description: string;
  images: string[];
  author: string;
  posted_at: string | null;
  posted_at_raw: string | null;
  plz: string | null;
  city: string | null;
  latitude: number | null;
  longitude: number | null;
  scraped_at: string;
}

export interface PaginatedResponse {
  total: number;
  page: number;
  per_page: number;
  items: ListingSummary[];
}

export interface PlzResponse {
  plz: string;
  city: string;
  lat: number;
  lon: number;
}

export interface ScrapeSummary {
  pages_crawled: number;
  listings_found: number;
  new: number;
  updated: number;
  skipped: number;
}

export interface ListingsQueryParams {
  page?: number;
  per_page?: number;
  search?: string | null;
  sort?: 'date' | 'price' | 'distance';
  plz?: string | null;
  max_distance?: number | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}
```

**Step 2: Write `frontend/src/api/client.ts`**

```ts
import type {
  ListingsQueryParams,
  ListingDetail,
  PaginatedResponse,
  PlzResponse,
  ScrapeSummary,
} from '../types/api';
import { ApiError } from '../types/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export async function getListings(params: ListingsQueryParams): Promise<PaginatedResponse> {
  const qs = new URLSearchParams();
  if (params.page != null) qs.set('page', String(params.page));
  if (params.per_page != null) qs.set('per_page', String(params.per_page));
  if (params.search) qs.set('search', params.search);
  if (params.sort) qs.set('sort', params.sort);
  if (params.plz) qs.set('plz', params.plz);
  if (params.max_distance != null) qs.set('max_distance', String(params.max_distance));

  const res = await fetch(`/api/listings?${qs.toString()}`);
  return handleResponse<PaginatedResponse>(res);
}

export async function getListing(id: number): Promise<ListingDetail> {
  const res = await fetch(`/api/listings/${id}`);
  return handleResponse<ListingDetail>(res);
}

export async function resolvePlz(plz: string): Promise<PlzResponse> {
  const res = await fetch(`/api/geo/plz/${encodeURIComponent(plz)}`);
  return handleResponse<PlzResponse>(res);
}

export async function triggerScrape(maxPages = 10): Promise<ScrapeSummary> {
  const res = await fetch(`/api/scrape?max_pages=${maxPages}`, { method: 'POST' });
  return handleResponse<ScrapeSummary>(res);
}
```

**Step 3: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors, no output.

**Step 4: Commit**

```bash
git add frontend/src/types/ frontend/src/api/
git commit -m "feat(frontend): add TypeScript types and typed API client"
```

---

### Task 3: App shell + routing [ ]

**Status:** open

**Depends on:** Task 2

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/ListingsPage.tsx` (stub)
- Create: `frontend/src/pages/DetailPage.tsx` (stub)

**Step 1: Write stub `frontend/src/pages/ListingsPage.tsx`**

```tsx
export default function ListingsPage() {
  return <div className="p-4 text-gray-500">Listings — coming soon</div>;
}
```

**Step 2: Write stub `frontend/src/pages/DetailPage.tsx`**

```tsx
export default function DetailPage() {
  return <div className="p-4 text-gray-500">Detail — coming soon</div>;
}
```

**Step 3: Write `frontend/src/App.tsx`**

```tsx
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';

function Header() {
  return (
    <header className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link to="/" className="text-xl font-bold text-gray-800 hover:text-gray-600">
          RC-Markt Scout
        </Link>
        {/* ScrapeButton added in Task 9 */}
        <div id="scrape-button-slot" />
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="max-w-6xl mx-auto px-4 py-6">
          <Routes>
            <Route path="/" element={<ListingsPage />} />
            <Route path="/listings/:id" element={<DetailPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

**Step 4: Verify dev server compiles**

```bash
cd frontend && npm run dev
```

Expected: no TypeScript errors in terminal.

**Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/
git commit -m "feat(frontend): add App shell with React Router and header"
```

---

### Task 4: ListingCard component + tests [ ]

**Status:** open

**Depends on:** Task 3

**Files:**
- Create: `frontend/src/components/ListingCard.tsx`
- Create: `frontend/src/components/__tests__/ListingCard.test.tsx`

**Reuse check:** No existing pattern found.

**Step 1: Write the failing tests — `frontend/src/components/__tests__/ListingCard.test.tsx`**

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ListingCard from '../ListingCard';
import type { ListingSummary } from '../../types/api';

const base: ListingSummary = {
  id: 130,
  external_id: '12113834',
  url: 'https://www.rc-network.de/threads/test',
  title: 'F-18 LX Modells',
  price: '280',
  condition: 'Gut',
  plz: null,
  city: 'Würzburg',
  latitude: null,
  longitude: null,
  author: 'MI77',
  posted_at: '2026-04-06T19:22:16Z',
  scraped_at: '2026-04-06T20:54:50.935574Z',
  distance_km: null,
};

function renderCard(props: Partial<ListingSummary> = {}) {
  return render(
    <MemoryRouter>
      <ListingCard listing={{ ...base, ...props }} />
    </MemoryRouter>,
  );
}

describe('ListingCard', () => {
  it('renders without crashing with all fields present', () => {
    renderCard();
    expect(screen.getByText('F-18 LX Modells')).toBeInTheDocument();
  });

  it('renders title as a link to /listings/:id', () => {
    renderCard();
    const link = screen.getByRole('link', { name: /F-18 LX Modells/i });
    expect(link).toHaveAttribute('href', '/listings/130');
  });

  it('shows "–" when price is null', () => {
    renderCard({ price: null });
    expect(screen.getByTestId('price')).toHaveTextContent('–');
  });

  it('shows raw price string as-is', () => {
    renderCard({ price: '480,00 EUR VB' });
    expect(screen.getByTestId('price')).toHaveTextContent('480,00 EUR VB');
  });

  it('shows "–" when condition is null', () => {
    renderCard({ condition: null });
    expect(screen.getByTestId('condition')).toHaveTextContent('–');
  });

  it('shows "–" when distance_km is null', () => {
    renderCard({ distance_km: null });
    expect(screen.getByTestId('distance')).toHaveTextContent('–');
  });

  it('shows distance formatted to 1 decimal', () => {
    renderCard({ distance_km: 42.7 });
    expect(screen.getByTestId('distance')).toHaveTextContent('42.7 km');
  });

  it('shows city when present', () => {
    renderCard({ city: 'München' });
    expect(screen.getByTestId('location')).toHaveTextContent('München');
  });

  it('shows "–" when both city and plz are null', () => {
    renderCard({ city: null, plz: null });
    expect(screen.getByTestId('location')).toHaveTextContent('–');
  });

  it('shows author', () => {
    renderCard();
    expect(screen.getByTestId('author')).toHaveTextContent('MI77');
  });
});
```

**Step 2: Run tests — confirm they fail**

```bash
cd frontend && npm test -- --run
```

Expected: FAIL — "Cannot find module '../ListingCard'".

**Step 3: Write `frontend/src/components/ListingCard.tsx`**

```tsx
import { Link } from 'react-router-dom';
import type { ListingSummary } from '../types/api';

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

interface Props {
  listing: ListingSummary;
}

export default function ListingCard({ listing }: Props) {
  const location = listing.city ?? listing.plz ?? null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 flex flex-col gap-2 hover:shadow-md transition-shadow">
      <Link
        to={`/listings/${listing.id}`}
        className="text-base font-semibold text-gray-900 hover:text-blue-700 leading-snug line-clamp-2"
      >
        {listing.title}
      </Link>

      <div className="flex items-center justify-between">
        <span data-testid="price" className="text-lg font-bold text-gray-800">
          {listing.price ?? '–'}
        </span>
        <span
          data-testid="condition"
          className="text-sm text-gray-500 bg-gray-100 px-2 py-0.5 rounded"
        >
          {listing.condition ?? '–'}
        </span>
      </div>

      <div className="text-sm text-gray-600 flex flex-wrap gap-x-3 gap-y-1">
        <span data-testid="location">{location ?? '–'}</span>
        <span data-testid="distance">
          {listing.distance_km != null
            ? `${listing.distance_km.toFixed(1)} km`
            : '–'}
        </span>
      </div>

      <div className="text-xs text-gray-400 flex justify-between mt-auto pt-1 border-t border-gray-100">
        <span data-testid="author">{listing.author}</span>
        <span>{formatDate(listing.posted_at)}</span>
      </div>
    </div>
  );
}
```

**Step 4: Run tests — confirm they pass**

```bash
cd frontend && npm test -- --run
```

Expected:
```
 ✓ src/components/__tests__/ListingCard.test.tsx (10 tests)
Tests  10 passed (10)
```

**Step 5: Commit**

```bash
git add frontend/src/components/ListingCard.tsx frontend/src/components/__tests__/ListingCard.test.tsx
git commit -m "feat(frontend): add ListingCard component with null-safe rendering and tests"
```

---

### Task 5: useListings hook + ListingsPage [ ]

**Status:** open

**Depends on:** Task 4

**Files:**
- Create: `frontend/src/hooks/useListings.ts`
- Modify: `frontend/src/pages/ListingsPage.tsx`

**Step 1: Write `frontend/src/hooks/useListings.ts`**

```ts
import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getListings } from '../api/client';
import type { PaginatedResponse } from '../types/api';

export interface ListingsFilter {
  search: string;
  plz: string;
  sort: 'date' | 'price' | 'distance';
  max_distance: string; // stored as string in URL; convert to int before API call
  page: number;
}

export function readFiltersFromParams(params: URLSearchParams): ListingsFilter {
  const sortRaw = params.get('sort') ?? 'date';
  const sort: ListingsFilter['sort'] =
    sortRaw === 'price' || sortRaw === 'distance' ? sortRaw : 'date';
  return {
    search: params.get('search') ?? '',
    plz: params.get('plz') ?? '',
    sort,
    max_distance: params.get('max_distance') ?? '',
    page: parseInt(params.get('page') ?? '1', 10) || 1,
  };
}

export function writeFiltersToParams(
  filter: ListingsFilter,
  setParams: (p: URLSearchParams) => void,
) {
  const p = new URLSearchParams();
  if (filter.search) p.set('search', filter.search);
  if (filter.plz) p.set('plz', filter.plz);
  if (filter.sort !== 'date') p.set('sort', filter.sort);
  if (filter.max_distance) p.set('max_distance', filter.max_distance);
  if (filter.page > 1) p.set('page', String(filter.page));
  setParams(p);
}

interface UseListingsResult {
  data: PaginatedResponse | null;
  loading: boolean;
  error: string | null;
  filter: ListingsFilter;
  setFilter: (next: ListingsFilter) => void;
}

export function useListings(): UseListingsResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = readFiltersFromParams(searchParams);

  const [data, setData] = useState<PaginatedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setFilter = (next: ListingsFilter) => {
    writeFiltersToParams(next, setSearchParams);
  };

  useEffect(() => {
    // Guard: don't send distance params without PLZ (backend returns 400)
    if ((filter.sort === 'distance' || filter.max_distance) && !filter.plz) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getListings({
      page: filter.page,
      per_page: 20,
      search: filter.search || null,
      sort: filter.sort,
      plz: filter.plz || null,
      max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
    })
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    filter.page,
    filter.search,
    filter.plz,
    filter.sort,
    filter.max_distance,
  ]);

  return { data, loading, error, filter, setFilter };
}
```

**Step 2: Write full `frontend/src/pages/ListingsPage.tsx`**

```tsx
import ListingCard from '../components/ListingCard';
import { useListings } from '../hooks/useListings';

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function ListingsPage() {
  const { data, loading, error } = useListings();

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div className="rounded-md bg-red-50 border border-red-200 p-4 text-red-700">
        Fehler beim Laden: {error}
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">Keine Anzeigen gefunden.</div>
    );
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">{data.total} Anzeigen gefunden</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.items.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
      </div>
    </div>
  );
}
```

**Step 3: Verify in browser**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173/ — listings from the backend should appear as cards.

**Step 4: Commit**

```bash
git add frontend/src/hooks/useListings.ts frontend/src/pages/ListingsPage.tsx
git commit -m "feat(frontend): add useListings hook with URL param sync and ListingsPage grid"
```

---

### Task 6: FilterPanel component + tests [ ]

**Status:** open

**Depends on:** Task 5

**Files:**
- Create: `frontend/src/components/FilterPanel.tsx`
- Create: `frontend/src/components/__tests__/FilterPanel.test.tsx`
- Modify: `frontend/src/pages/ListingsPage.tsx`

**Step 1: Write failing tests — `frontend/src/components/__tests__/FilterPanel.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import FilterPanel from '../FilterPanel';
import type { ListingsFilter } from '../../hooks/useListings';
import * as client from '../../api/client';

const defaultFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  max_distance: '',
  page: 1,
};

function renderPanel(filter = defaultFilter, onChange = vi.fn()) {
  return render(
    <MemoryRouter>
      <FilterPanel filter={filter} onChange={onChange} />
    </MemoryRouter>,
  );
}

describe('FilterPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('renders search input', () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/Suche/i)).toBeInTheDocument();
  });

  it('renders PLZ input', () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/PLZ/i)).toBeInTheDocument();
  });

  it('calls onChange with updated search value', () => {
    const onChange = vi.fn();
    renderPanel(defaultFilter, onChange);
    fireEvent.change(screen.getByPlaceholderText(/Suche/i), {
      target: { value: 'F-18' },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'F-18', page: 1 }),
    );
  });

  it('max_distance input is disabled when PLZ is empty', () => {
    renderPanel();
    expect(screen.getByLabelText(/Max.*km/i)).toBeDisabled();
  });

  it('max_distance input is enabled when filter.plz is set', () => {
    renderPanel({ ...defaultFilter, plz: '97070' });
    expect(screen.getByLabelText(/Max.*km/i)).not.toBeDisabled();
  });

  it('shows city name after successful PLZ validation', async () => {
    vi.spyOn(client, 'resolvePlz').mockResolvedValue({
      plz: '97070',
      city: 'Würzburg',
      lat: 49.7,
      lon: 9.9,
    });
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText(/PLZ/i), {
      target: { value: '97070' },
    });
    fireEvent.blur(screen.getByPlaceholderText(/PLZ/i));
    await waitFor(() =>
      expect(screen.getByText('Würzburg')).toBeInTheDocument(),
    );
  });

  it('shows error message when PLZ not found (404)', async () => {
    const { ApiError } = await import('../../types/api');
    vi.spyOn(client, 'resolvePlz').mockRejectedValue(new ApiError(404, 'PLZ not found'));
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText(/PLZ/i), {
      target: { value: '00000' },
    });
    fireEvent.blur(screen.getByPlaceholderText(/PLZ/i));
    await waitFor(() =>
      expect(screen.getByText(/PLZ nicht gefunden/i)).toBeInTheDocument(),
    );
  });
});
```

**Step 2: Run tests — confirm they fail**

```bash
cd frontend && npm test -- --run
```

Expected: FAIL — "Cannot find module '../FilterPanel'".

**Step 3: Write `frontend/src/components/FilterPanel.tsx`**

```tsx
import { useState, useEffect } from 'react';
import { resolvePlz } from '../api/client';
import { ApiError } from '../types/api';
import type { ListingsFilter } from '../hooks/useListings';

const PLZ_STORAGE_KEY = 'rcn_ref_plz';

interface Props {
  filter: ListingsFilter;
  onChange: (next: ListingsFilter) => void;
}

export default function FilterPanel({ filter, onChange }: Props) {
  const [plzInput, setPlzInput] = useState(filter.plz);
  const [plzCity, setPlzCity] = useState<string | null>(null);
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  // On mount: restore PLZ from localStorage if URL has none.
  // Call onChange (not silent) so the PLZ propagates to the URL and API.
  useEffect(() => {
    if (!filter.plz) {
      const saved = localStorage.getItem(PLZ_STORAGE_KEY);
      if (saved) {
        setPlzInput(saved);
        validateAndApplyPlz(saved); // silent=false → calls onChange → updates URL
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateAndApplyPlz(value: string, silent = false) {
    if (!value) {
      setPlzCity(null);
      setPlzError(null);
      return;
    }
    setPlzValidating(true);
    setPlzError(null);
    setPlzCity(null);
    try {
      const result = await resolvePlz(value);
      setPlzCity(result.city);
      localStorage.setItem(PLZ_STORAGE_KEY, value);
      if (!silent) {
        onChange({ ...filter, plz: value, page: 1 });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlzError('PLZ nicht gefunden');
      } else {
        setPlzError('Fehler bei der PLZ-Validierung');
      }
    } finally {
      setPlzValidating(false);
    }
  }

  function handlePlzBlur() {
    validateAndApplyPlz(plzInput);
  }

  function handlePlzClear() {
    setPlzInput('');
    setPlzCity(null);
    setPlzError(null);
    localStorage.removeItem(PLZ_STORAGE_KEY);
    onChange({
      ...filter,
      plz: '',
      sort: filter.sort === 'distance' ? 'date' : filter.sort,
      max_distance: '',
      page: 1,
    });
  }

  const hasValidPlz = !!filter.plz && !plzError;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4 flex flex-col gap-3 mb-6">
      {/* Search */}
      <div>
        <label htmlFor="search" className="block text-sm font-medium text-gray-700 mb-1">
          Suche
        </label>
        <input
          id="search"
          type="text"
          placeholder="Suche nach Titel oder Beschreibung…"
          value={filter.search}
          onChange={(e) => onChange({ ...filter, search: e.target.value, page: 1 })}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        {/* PLZ */}
        <div className="flex-1">
          <label htmlFor="plz" className="block text-sm font-medium text-gray-700 mb-1">
            Meine PLZ
          </label>
          <div className="relative">
            <input
              id="plz"
              type="text"
              placeholder="PLZ (z.B. 49356)"
              value={plzInput}
              onChange={(e) => setPlzInput(e.target.value)}
              onBlur={handlePlzBlur}
              maxLength={5}
              className={`w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                plzError ? 'border-red-400' : 'border-gray-300'
              }`}
            />
            {plzValidating && (
              <span className="absolute right-2 top-2.5 text-xs text-gray-400">…</span>
            )}
            {plzInput && !plzValidating && (
              <button
                type="button"
                onClick={handlePlzClear}
                className="absolute right-2 top-2 text-gray-400 hover:text-gray-600 text-sm"
                aria-label="PLZ löschen"
              >
                ✕
              </button>
            )}
          </div>
          {plzCity && <p className="mt-1 text-xs text-green-600">{plzCity}</p>}
          {plzError && <p className="mt-1 text-xs text-red-500">{plzError}</p>}
        </div>

        {/* Max distance */}
        <div className="w-32">
          <label
            htmlFor="max_distance"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Max. km
          </label>
          <input
            id="max_distance"
            type="number"
            min={1}
            placeholder="km"
            disabled={!hasValidPlz}
            value={filter.max_distance}
            onChange={(e) => onChange({ ...filter, max_distance: e.target.value, page: 1 })}
            aria-label="Max Entfernung in km"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
          />
        </div>

        {/* Sort */}
        <div className="w-44">
          <label htmlFor="sort" className="block text-sm font-medium text-gray-700 mb-1">
            Sortierung
          </label>
          <select
            id="sort"
            value={filter.sort}
            onChange={(e) => {
              const val = e.target.value as ListingsFilter['sort'];
              if (val === 'distance' && !hasValidPlz) return;
              onChange({ ...filter, sort: val, page: 1 });
            }}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="date">Datum</option>
            <option value="price">Preis</option>
            <option value="distance" disabled={!hasValidPlz}>
              Entfernung{!hasValidPlz ? ' (PLZ erforderlich)' : ''}
            </option>
          </select>
        </div>
      </div>
    </div>
  );
}
```

**Step 4: Wire FilterPanel into ListingsPage**

Replace `frontend/src/pages/ListingsPage.tsx` with the full version:

```tsx
import ListingCard from '../components/ListingCard';
import FilterPanel from '../components/FilterPanel';
import { useListings } from '../hooks/useListings';

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function ListingsPage() {
  const { data, loading, error, filter, setFilter } = useListings();

  return (
    <div>
      <FilterPanel filter={filter} onChange={setFilter} />

      {loading && <Spinner />}

      {!loading && error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-red-700">
          Fehler beim Laden: {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          <p className="text-sm text-gray-500 mb-4">{data.total} Anzeigen gefunden</p>
          {data.items.length === 0 ? (
            <div className="text-center py-12 text-gray-500">Keine Anzeigen gefunden.</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {data.items.map((listing) => (
                <ListingCard key={listing.id} listing={listing} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

**Step 5: Run all tests**

```bash
cd frontend && npm test -- --run
```

Expected:
```
 ✓ src/components/__tests__/ListingCard.test.tsx (10 tests)
 ✓ src/components/__tests__/FilterPanel.test.tsx (7 tests)
Tests  17 passed (17)
```

**Step 6: Commit**

```bash
git add frontend/src/components/FilterPanel.tsx frontend/src/components/__tests__/FilterPanel.test.tsx frontend/src/pages/ListingsPage.tsx
git commit -m "feat(frontend): add FilterPanel with PLZ validation, localStorage, and distance guards"
```

---

### Task 7: Pagination component [ ]

**Status:** open

**Depends on:** Task 6

**Files:**
- Create: `frontend/src/components/Pagination.tsx`
- Modify: `frontend/src/pages/ListingsPage.tsx`

**Step 1: Write `frontend/src/components/Pagination.tsx`**

```tsx
interface Props {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({ page, totalPages, onPageChange }: Props) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-3 mt-8">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="px-4 py-2 rounded-md border border-gray-300 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        ← Zurück
      </button>

      <span className="text-sm text-gray-600">
        Seite <span className="font-semibold">{page}</span> von{' '}
        <span className="font-semibold">{totalPages}</span>
      </span>

      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="px-4 py-2 rounded-md border border-gray-300 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Weiter →
      </button>
    </div>
  );
}
```

**Step 2: Add Pagination to ListingsPage**

In `frontend/src/pages/ListingsPage.tsx`, add at the top:

```tsx
import Pagination from '../components/Pagination';
```

Inside the `data.items.length > 0` branch, after the card grid closing `</div>`, add:

```tsx
<Pagination
  page={data.page}
  totalPages={Math.ceil(data.total / data.per_page)}
  onPageChange={(p) => setFilter({ ...filter, page: p })}
/>
```

**Step 3: Verify in browser**

Open http://localhost:5173/ — if total > 20, Prev/Next buttons appear. Clicking Next updates `?page=2` in URL and loads the next page.

**Step 4: Commit**

```bash
git add frontend/src/components/Pagination.tsx frontend/src/pages/ListingsPage.tsx
git commit -m "feat(frontend): add Pagination component with URL param sync"
```

---

### Task 8: DetailPage [ ]

**Status:** open

**Depends on:** Task 7

**Files:**
- Modify: `frontend/src/pages/DetailPage.tsx`

**Step 1: Write full `frontend/src/pages/DetailPage.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getListing } from '../api/client';
import type { ListingDetail } from '../types/api';

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900">{value ?? '–'}</dd>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center py-16">
      <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function DetailPage() {
  const { id } = useParams<{ id: string }>();
  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    getListing(Number(id))
      .then((data) => {
        setListing(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, [id]);

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div>
        <Link to="/" className="text-blue-600 hover:underline text-sm mb-4 inline-block">
          ← Zurück zur Liste
        </Link>
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-red-700">
          Fehler: {error}
        </div>
      </div>
    );
  }

  if (!listing) return null;

  const location = [listing.plz, listing.city].filter(Boolean).join(' ') || '–';

  return (
    <div className="max-w-2xl mx-auto">
      <Link to="/" className="text-blue-600 hover:underline text-sm mb-4 inline-block">
        ← Zurück zur Liste
      </Link>

      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-4 leading-tight">
          {listing.title}
        </h1>

        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6 pb-6 border-b border-gray-100">
          <Field label="Preis" value={listing.price} />
          <Field label="Zustand" value={listing.condition} />
          <Field label="Versand" value={listing.shipping} />
          <Field label="Ort" value={location} />
          <Field label="Inserent" value={listing.author} />
          <Field label="Datum" value={formatDate(listing.posted_at)} />
        </dl>

        {listing.images.length > 0 && (
          <div className="mb-6">
            <div className="flex flex-wrap gap-2">
              {listing.images.map((src, i) => (
                <a key={i} href={src} target="_blank" rel="noopener noreferrer">
                  <img
                    src={src}
                    alt={`Bild ${i + 1}`}
                    className="h-32 w-auto rounded border border-gray-200 object-cover hover:opacity-90 transition-opacity"
                    loading="lazy"
                  />
                </a>
              ))}
            </div>
          </div>
        )}

        {listing.description && (
          <div className="mb-6">
            <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-2">
              Beschreibung
            </h2>
            <div className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">
              {listing.description}
            </div>
          </div>
        )}

        <div className="pt-4 border-t border-gray-100">
          <a
            href={listing.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
          >
            Original auf rc-network.de ansehen →
          </a>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify in browser**

Open http://localhost:5173/ — click any listing card. Detail page should show all fields, images (if any), description, and link to rc-network.de. Browser back button returns to the listing list with filters preserved.

**Step 3: Commit**

```bash
git add frontend/src/pages/DetailPage.tsx
git commit -m "feat(frontend): add DetailPage with images, description, and link to original"
```

---

### Task 9: ScrapeButton component [ ]

**Status:** open

**Depends on:** Task 8

**Files:**
- Create: `frontend/src/components/ScrapeButton.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Write `frontend/src/components/ScrapeButton.tsx`**

```tsx
import { useState } from 'react';
import { triggerScrape } from '../api/client';
import type { ScrapeSummary } from '../types/api';

export default function ScrapeButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScrapeSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleScrape() {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const summary = await triggerScrape(10);
      setResult(summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleScrape}
        disabled={loading}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading && (
          <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
        )}
        {loading ? 'Scraping…' : 'Scrape starten'}
      </button>

      {result && !loading && (
        <span className="text-xs text-gray-600">
          ✓ {result.new} neu, {result.updated} aktualisiert, {result.skipped} übersprungen
        </span>
      )}

      {error && !loading && (
        <span className="text-xs text-red-500">Fehler: {error}</span>
      )}
    </div>
  );
}
```

**Step 2: Replace slot in App.tsx with real ScrapeButton**

In `frontend/src/App.tsx`, add import:

```tsx
import ScrapeButton from './components/ScrapeButton';
```

Replace `<div id="scrape-button-slot" />` with:

```tsx
<ScrapeButton />
```

**Step 3: Verify in browser**

Header shows "Scrape starten" button. Clicking it shows spinner + disabled state for ~40s (for 10 pages), then shows the result summary.

**Step 4: Commit**

```bash
git add frontend/src/components/ScrapeButton.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add ScrapeButton with loading state and result summary"
```

---

### Task 10: Docker Compose frontend service [ ]

**Status:** open

**Depends on:** Task 9

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add frontend service to docker-compose.yml**

Read the current `docker-compose.yml` first, then add the `frontend` service block inside `services:`. The final `services:` section must include all three services:

```yaml
  frontend:
    image: node:22-alpine
    working_dir: /app
    volumes:
      - ./frontend:/app
      - /app/node_modules
    ports:
      - "5173:5173"
    environment:
      - API_PROXY_TARGET=http://backend:8000
    command: sh -c "npm install && npm run dev -- --host"
    depends_on:
      - backend
```

**Step 2: Verify all 3 services start together**

From the repo root:

```bash
docker compose up --build
```

Expected (after containers start):
```
 ✔ Container rcn-scraper-db-1        Healthy
 ✔ Container rcn-scraper-backend-1   Started
 ✔ Container rcn-scraper-frontend-1  Started
```

After `npm install` completes inside the frontend container:
```
  VITE v5.x.x  ready in XXX ms
  ➜  Network: http://0.0.0.0:5173/
```

Open http://localhost:5173/ — listings should load.

**Step 3: Verify API proxy works through Docker network**

In the browser, open DevTools → Network. Filter by Fetch/XHR. Reload the page. Confirm `/api/listings` requests return HTTP 200 — this proves the proxy from frontend container to `http://backend:8000` (internal Docker network) works.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(frontend): add frontend Docker Compose service with API proxy to backend"
```

---

## Reviewer Notes

_Review by dglabs.agent.review-plan — 2026-04-06_

**Blockers addressed:**
1. localStorage PLZ restore bug fixed — removed `silent=true` from mount effect so PLZ propagates to URL and API on restore.
2. Per-task `**Status:** open` fields added to all 10 tasks.
3. Reviewer Notes section added (this section).

**Fixed bugs:**
4. FilterPanel 404 test now uses `new ApiError(404, ...)` instead of a hand-rolled `Error`, matching the `instanceof ApiError` check in the component.

**Non-blocking notes (acknowledged, no action):**
- TypeScript types verified to match backend schemas exactly.
- API client URLs and parameter names verified against `routes.py`.
- Docker Compose config is correct: `--host` flag, volume mount pattern, `API_PROXY_TARGET` env var.
- When `useListings` guard short-circuits (PLZ missing for distance sort), `data` retains stale state — acceptable for MVP.
- A test for "max_distance clears when PLZ is cleared" would be nice but is not blocking.

---

## Verification

After all tasks are complete, run the following in sequence:

**1. TypeScript check**
```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

**2. Frontend tests**
```bash
cd frontend && npm test -- --run
```
Expected: all tests pass (at minimum 17 tests across ListingCard and FilterPanel).

**3. Docker Compose full stack**
```bash
docker compose up --build -d
```
Expected: all 3 containers healthy.

**4. Smoke test — listings load**
```bash
curl -s http://localhost:5173/ | grep -o "RC-Markt Scout"
```
Expected: `RC-Markt Scout`

**5. Smoke test — API proxy**
```bash
curl -s http://localhost:5173/api/listings | python -m json.tool | head -5
```
Expected: JSON with `total`, `page`, `per_page`, `items` keys.

**6. Manual browser checks**
- Open http://localhost:5173/ → card grid loads
- Enter PLZ in filter → city name appears, distance sort and max km unlock
- Enter search term → filtered results appear
- Click a card → detail page loads with title, price, description, images
- Click "← Zurück" → returns to filtered listing list (URL params preserved)
- Click "Scrape starten" → button disables, spinner shows, result appears after completion
