# PLAN 017 — Preisvergleich-Modal (Comparables)

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-13 |
| Human | pending | — |

## Context & Goal

Price-indicator badges (`deal` / `fair` / `expensive`) show on listing cards and the detail page. They currently have a native `title` tooltip with median + count on hover. Goal: clicking the badge opens a modal that shows the actual comparable listings used to compute the indicator, with the current listing highlighted and a median price marker in the sorted list.

## Breaking Changes

**No.** Additive only — badge gets `cursor-pointer` and an `onClick`, native `title` tooltip removed. No DB schema changes. No existing API routes modified.

## Assumptions & Risks

- The comparables query mirrors the two-level grouping from the SQL job (`manufacturer+model_name` ≥5, fallback `model_type+model_subtype+completeness` ≥5) but runs live — may occasionally differ from stored `price_indicator_count` if listings sold since the last job run. Acceptable.
- The backend does **not** include the current listing itself in results (`id != listing.id`).
- `ListingCard` uses a stretched `<Link>` overlay (`after:absolute after:inset-0`). Badge `<span>` elements need `relative z-10` to sit above the overlay and receive click events. `stopPropagation`/`preventDefault` are also kept as safety.
- Desktop popover is positioned via `getBoundingClientRect()` in a `useLayoutEffect`.
- Auth: new endpoint uses the same `Depends(get_current_user)` pattern.

## Reviewer Findings (2026-04-13)

**Blocking — all incorporated below:**

1. **Badge z-index missing** (Step 6 & 7): The `after:absolute after:inset-0` stretched link overlay intercepts clicks. Badge `<span>` elements must have `relative z-10` to receive click events. Fixed in Steps 6 (`PriceIndicatorBadge` spans) and 7.3.
2. **TypeScript ref variance** (Step 6): `RefObject<HTMLSpanElement | null>` is not assignable to `RefObject<HTMLElement | null>` with @types/react 19.2 (invariant). Fixed: `anchorRef` prop narrowed to `React.RefObject<HTMLSpanElement | null>`.
3. **Backend grouping diverges from SQL job** (Step 2): Route used `if listing.manufacturer and listing.model_name` without checking the ≥5 threshold. If L1 group has <5 members the stored indicator came from L2, but the modal would show L1. Fixed: route now counts L1 members first; uses L1 only when ≥5, otherwise falls back to L2.

---

## Steps

### Step 1 — Backend: Schemas `[open]`

**File: `backend/app/api/schemas.py`**

Add after `PaginatedResponse`:

```python
class ComparableListing(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    price: str | None
    price_numeric: float | None
    condition: str | None
    city: str | None
    posted_at: datetime | None
    is_favorite: bool = False


class ComparablesResponse(BaseModel):
    group_label: str
    group_level: Literal["model", "type"]
    median: float
    count: int
    listings: list[ComparableListing]
```

`Literal`, `datetime`, `ConfigDict` are already imported.

---

### Step 2 — Backend: New Route `[open]`

**File: `backend/app/api/routes.py`**

Add `import statistics` to stdlib imports at the top.

Add `ComparableListing, ComparablesResponse` to the `from app.api.schemas import (...)` block.

Add the route **before** `@router.get("/listings/{listing_id}", ...)` (FastAPI first-match — the sub-path must come first):

```python
@router.get("/listings/{listing_id}/comparables", response_model=ComparablesResponse)
async def get_comparables(
    listing_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ComparablesResponse:
    """Return the comparable listings used to compute the price indicator for a given listing."""
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    fav_ids = await _get_favorite_listing_ids(current_user.id, session)

    base_q = (
        select(Listing)
        .where(Listing.is_sold == False)          # noqa: E712
        .where(Listing.price_numeric.is_not(None))
        .where(Listing.id != listing_id)
    )

    rows: list[Listing]
    group_label: str
    group_level: str

    # Mirror the SQL job's two-level grouping: L1 requires ≥5 members, L2 is fallback.
    used_level: str | None = None

    if listing.manufacturer and listing.model_name:
        l1_q = base_q.where(
            Listing.manufacturer == listing.manufacturer,
            Listing.model_name == listing.model_name,
        ).order_by(Listing.price_numeric.asc())
        res = await session.execute(l1_q)
        l1_rows = list(res.scalars().all())
        if len(l1_rows) >= 4:  # ≥4 others = ≥5 total including current listing
            rows = l1_rows
            group_label = f"{listing.manufacturer} {listing.model_name}"
            group_level = "model"
            used_level = "l1"

    if used_level is None and listing.model_type and listing.model_subtype and listing.completeness:
        l2_q = base_q.where(
            Listing.model_type == listing.model_type,
            Listing.model_subtype == listing.model_subtype,
            Listing.completeness == listing.completeness,
        ).order_by(Listing.price_numeric.asc())
        res = await session.execute(l2_q)
        l2_rows = list(res.scalars().all())
        if len(l2_rows) >= 4:  # ≥4 others = ≥5 total including current listing
            rows = l2_rows
            group_label = f"{listing.model_type} {listing.model_subtype} {listing.completeness}"
            group_level = "type"
            used_level = "l2"

    if used_level is None:
        return ComparablesResponse(
            group_label="",
            group_level="model",
            median=listing.price_indicator_median or 0.0,
            count=0,
            listings=[],
        )

    prices = [float(r.price_numeric) for r in rows if r.price_numeric is not None]
    median_val = statistics.median(prices) if prices else (listing.price_indicator_median or 0.0)

    items: list[ComparableListing] = []
    for row in rows:
        comp = ComparableListing.model_validate(row)
        if row.id in fav_ids:
            comp = comp.model_copy(update={"is_favorite": True})
        items.append(comp)

    return ComparablesResponse(
        group_label=group_label,
        group_level=group_level,  # type: ignore[arg-type]
        median=median_val,
        count=len(items),
        listings=items,
    )
```

---

### Step 3 — Frontend: Types `[open]`

**File: `frontend/src/types/api.ts`** — append at the end:

```typescript
export interface ComparableListing {
  id: number;
  title: string;
  url: string;
  price: string | null;
  price_numeric: number | null;
  condition: string | null;
  city: string | null;
  posted_at: string | null;
  is_favorite: boolean;
}

export interface ComparablesResponse {
  group_label: string;
  group_level: 'model' | 'type';
  median: number;
  count: number;
  listings: ComparableListing[];
}
```

---

### Step 4 — Frontend: API Client `[open]`

**File: `frontend/src/api/client.ts`**

Add `ComparablesResponse` to the type imports. Add at the end:

```typescript
export async function getComparables(id: number): Promise<ComparablesResponse> {
  const res = await fetch(`/api/listings/${id}/comparables`, { credentials: 'include' });
  return handleResponse<ComparablesResponse>(res);
}
```

---

### Step 5 — Frontend: `useComparables` Hook `[open]`

**File: `frontend/src/hooks/useComparables.ts`** (new file)

```typescript
import { useState, useEffect } from 'react';
import { getComparables } from '../api/client';
import type { ComparablesResponse } from '../types/api';

interface UseComparablesResult {
  data: ComparablesResponse | null;
  loading: boolean;
  error: string | null;
}

export function useComparables(listingId: number | null): UseComparablesResult {
  const [data, setData] = useState<ComparablesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (listingId === null) { setData(null); setLoading(false); setError(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getComparables(listingId)
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err: Error) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [listingId]);

  return { data, loading, error };
}
```

---

### Step 6 — Frontend: `ComparablesModal` Component `[open]`

**File: `frontend/src/components/ComparablesModal.tsx`** (new file)

Props:
```typescript
interface Props {
  listingId: number | null;          // null = closed
  currentListingId: number;          // to highlight in the list
  anchorRef: React.RefObject<HTMLSpanElement | null>;  // badge DOM node for desktop positioning
  onClose: () => void;
}
```

Full implementation:

```typescript
import { useRef, useLayoutEffect, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useComparables } from '../hooks/useComparables';

interface Props {
  listingId: number | null;
  currentListingId: number;
  anchorRef: React.RefObject<HTMLSpanElement | null>;
  onClose: () => void;
}

export default function ComparablesModal({ listingId, currentListingId, anchorRef, onClose }: Props) {
  const isOpen = listingId !== null;
  const { data, loading, error } = useComparables(listingId);
  const popoverRef = useRef<HTMLDivElement>(null);
  const swipeStartY = useRef<number | null>(null);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const POPOVER_WIDTH = 400;
    const POPOVER_MAX_H = window.innerHeight * 0.6;
    const spaceBelow = window.innerHeight - rect.bottom - 8;
    const top = spaceBelow >= POPOVER_MAX_H
      ? rect.bottom + window.scrollY + 6
      : rect.top + window.scrollY - POPOVER_MAX_H - 6;
    const left = Math.min(
      rect.left + window.scrollX,
      window.innerWidth + window.scrollX - POPOVER_WIDTH - 16,
    );
    setPopoverStyle({ top, left, width: POPOVER_WIDTH });
  }, [isOpen, anchorRef, data]);

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose(); }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) { document.body.style.overflow = 'hidden'; }
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  if (!isOpen) return null;

  const medianValue = data?.median ?? 0;
  let medianInsertIdx = -1;
  if (data) {
    for (let i = data.listings.length - 1; i >= 0; i--) {
      const p = data.listings[i].price_numeric;
      if (p !== null && p <= medianValue) { medianInsertIdx = i; break; }
    }
  }

  const panelStyle: React.CSSProperties = {
    background: 'rgba(12, 12, 28, 0.98)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid rgba(255,255,255,0.1)',
    boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
  };

  const header = data ? (
    <div className="px-4 py-3 flex items-center justify-between shrink-0"
      style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
      <div>
        <p className="text-xs font-semibold" style={{ color: '#F8FAFC' }}>{data.group_label}</p>
        <p className="text-[10px]" style={{ color: 'rgba(248,250,252,0.4)' }}>
          {data.count} {data.count === 1 ? 'Inserat' : 'Inserate'}{' · '}Median{' '}
          {data.median.toLocaleString('de-DE', { maximumFractionDigits: 0 })} €
        </p>
      </div>
      <button onClick={onClose} aria-label="Schließen"
        className="p-1 rounded-full" style={{ color: 'rgba(248,250,252,0.4)' }}>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  ) : null;

  const listBody = (
    <>
      {loading && (
        <div className="flex justify-center py-10">
          <div className="animate-spin h-6 w-6 border-4 rounded-full"
            style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }} />
        </div>
      )}
      {error && (
        <p className="px-4 py-6 text-sm text-center" style={{ color: '#EC4899' }}>
          Fehler: {error}
        </p>
      )}
      {data && data.listings.length === 0 && !loading && (
        <p className="px-4 py-6 text-sm text-center" style={{ color: 'rgba(248,250,252,0.4)' }}>
          Keine Vergleichsinserate gefunden.
        </p>
      )}
      {data?.listings.map((item, idx) => (
        <div key={item.id}>
          {idx === medianInsertIdx && (
            <div className="flex items-center gap-2 px-4 py-1">
              <div className="flex-1 h-px" style={{ background: 'rgba(167,139,250,0.35)' }} />
              <span className="text-[10px] font-semibold" style={{ color: '#A78BFA' }}>
                Ø {data.median.toLocaleString('de-DE', { maximumFractionDigits: 0 })} €
              </span>
              <div className="flex-1 h-px" style={{ background: 'rgba(167,139,250,0.35)' }} />
            </div>
          )}
          <Link
            to={`/listings/${item.id}`}
            onClick={onClose}
            className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-white/5"
            style={{
              background: item.id === currentListingId ? 'rgba(99,102,241,0.12)' : 'transparent',
              borderLeft: item.id === currentListingId ? '2px solid #6366F1' : '2px solid transparent',
            }}
          >
            <span className="text-sm line-clamp-1 flex-1"
              style={{ color: item.id === currentListingId ? '#F8FAFC' : 'rgba(248,250,252,0.75)' }}>
              {item.title}
            </span>
            <div className="flex items-center gap-2 shrink-0">
              {item.condition && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                  style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(248,250,252,0.5)' }}>
                  {item.condition}
                </span>
              )}
              {item.city && (
                <span className="text-[10px]" style={{ color: 'rgba(248,250,252,0.4)' }}>{item.city}</span>
              )}
              <span className="text-sm font-bold" style={{ color: '#FDE68A' }}>
                {item.price_numeric != null
                  ? item.price_numeric.toLocaleString('de-DE', { maximumFractionDigits: 0 }) + ' €'
                  : (item.price ?? '–')}
              </span>
            </div>
          </Link>
        </div>
      ))}
    </>
  );

  return createPortal(
    <>
      {/* Mobile bottom sheet (< sm) */}
      <div className="fixed inset-0 z-40 sm:hidden"
        style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(3px)' }}
        onClick={onClose} aria-hidden="true" />
      <div
        role="dialog" aria-modal="true" aria-label="Preisvergleich"
        className="fixed bottom-0 left-0 right-0 z-50 sm:hidden rounded-t-2xl flex flex-col"
        style={{
          ...panelStyle,
          borderBottom: 'none',
          maxHeight: '75vh',
          paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.5rem)',
        }}
        onTouchStart={(e) => { swipeStartY.current = e.touches[0].clientY; }}
        onTouchEnd={(e) => {
          if (swipeStartY.current === null) return;
          const delta = e.changedTouches[0].clientY - swipeStartY.current;
          swipeStartY.current = null;
          if (delta > 60) onClose();
        }}
      >
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full" style={{ background: 'rgba(255,255,255,0.18)' }} aria-hidden="true" />
        </div>
        {header}
        <div className="flex-1 overflow-y-auto">{listBody}</div>
      </div>

      {/* Desktop popover (>= sm) */}
      <div className="fixed inset-0 z-40 hidden sm:block"
        onClick={onClose} aria-hidden="true" />
      <div
        ref={popoverRef}
        role="dialog" aria-modal="true" aria-label="Preisvergleich"
        className="fixed z-50 hidden sm:flex flex-col rounded-xl overflow-hidden"
        style={{ ...popoverStyle, maxHeight: '60vh', ...panelStyle }}
        onClick={(e) => e.stopPropagation()}
      >
        {header}
        <div className="flex-1 overflow-y-auto">{listBody}</div>
      </div>
    </>,
    document.body,
  );
}
```

**Key design notes:**
- Both mobile and desktop panels are always in the DOM (controlled by `sm:hidden` / `hidden sm:flex`) — avoids layout shift at breakpoint.
- Transparent desktop backdrop at z-40 closes the popover on outside click.
- `onClick={e.stopPropagation()}` on the popover panel prevents the backdrop click from immediately closing it.
- Median marker appears after the last item whose price ≤ median.

---

### Step 7 — Wire Up `ListingCard.tsx` `[open]`

**File: `frontend/src/components/ListingCard.tsx`**

1. Add `useRef` to the React import. Add `import ComparablesModal from './ComparablesModal';`

2. Update `PriceIndicatorBadgeProps`:
```typescript
interface PriceIndicatorBadgeProps {
  indicator: ListingSummary['price_indicator'];
  median?: number | null;
  count?: number | null;
  onClick?: (e: React.MouseEvent) => void;
  badgeRef?: React.RefObject<HTMLSpanElement | null>;
}
```

3. In each `<span>` inside `PriceIndicatorBadge`:
   - Change `cursor-default` → `cursor-pointer`
   - Add `relative z-10` to the className (positions span above the `after:absolute after:inset-0` stretched link overlay so click events reach it)
   - Remove `title={buildTooltip(...)}` attribute
   - Add `onClick={onClick}` and `ref={badgeRef}`

4. Add inside `ListingCard` function body:
```typescript
const [comparablesOpen, setComparablesOpen] = useState(false);
const badgeRef = useRef<HTMLSpanElement>(null);
```

5. Update the `<PriceIndicatorBadge />` call:
```tsx
<PriceIndicatorBadge
  indicator={listing.price_indicator}
  median={listing.price_indicator_median}
  count={listing.price_indicator_count}
  badgeRef={badgeRef}
  onClick={(e) => {
    e.stopPropagation();
    e.preventDefault();
    setComparablesOpen(true);
  }}
/>
```

6. Add just before closing `</article>`:
```tsx
{comparablesOpen && (
  <ComparablesModal
    listingId={listing.id}
    currentListingId={listing.id}
    anchorRef={badgeRef}
    onClose={() => setComparablesOpen(false)}
  />
)}
```

---

### Step 8 — Wire Up `DetailPage.tsx` `[open]`

**File: `frontend/src/pages/DetailPage.tsx`**

1. Add `useRef` to React imports. Add `import ComparablesModal from '../components/ComparablesModal';`

2. Update the local `PriceIndicatorBadge` — same changes as Step 7.2/7.3 (add `onClick`, `badgeRef` props; `cursor-pointer`; remove `title`).

3. Add inside `DetailPage` component body:
```typescript
const [comparablesOpen, setComparablesOpen] = useState(false);
const badgeRef = useRef<HTMLSpanElement>(null);
```

4. Update `<PriceIndicatorBadge />` call:
```tsx
<PriceIndicatorBadge
  indicator={listing.price_indicator}
  median={listing.price_indicator_median}
  count={listing.price_indicator_count}
  badgeRef={badgeRef}
  onClick={() => setComparablesOpen(true)}
/>
```
No `stopPropagation` needed — no stretched link overlay on detail page.

5. Render the modal at the end of the component return:
```tsx
{comparablesOpen && listing.price_indicator && (
  <ComparablesModal
    listingId={listing.id}
    currentListingId={listing.id}
    anchorRef={badgeRef}
    onClose={() => setComparablesOpen(false)}
  />
)}
```

---

## Verification

```bash
# Backend tests
docker compose exec backend pytest tests/ -v

# Frontend build
cd frontend && npm run build

# Manual: fetch comparables for a listing with a price_indicator
# (requires a valid session cookie from the browser)
curl -s -b "<cookie>" http://localhost:8002/api/listings/<id>/comparables | python -m json.tool
# Expected: { group_label, group_level, median, count, listings: [...] }
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/api/schemas.py` | Add `ComparableListing`, `ComparablesResponse` |
| `backend/app/api/routes.py` | Add `GET /api/listings/{id}/comparables` |
| `frontend/src/types/api.ts` | Add `ComparableListing`, `ComparablesResponse` |
| `frontend/src/api/client.ts` | Add `getComparables()` |
| `frontend/src/hooks/useComparables.ts` | New hook |
| `frontend/src/components/ComparablesModal.tsx` | New modal component |
| `frontend/src/components/ListingCard.tsx` | Badge clickable + modal trigger |
| `frontend/src/pages/DetailPage.tsx` | Badge clickable + modal inline |
