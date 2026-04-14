# PLAN 016 — Detail as Modal Route + Shareable Deep Link + Desktop Layout Redesign

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-14 |
| Human | approved | 2026-04-14 |

## Reviewer Remarks

Open remarks (this round, if any) land here. All prior-round findings have been incorporated into the plan body:

- **Round 1:** caching-approach abandoned in favour of Modal-Routing; desktop layout redesign merged into this plan.
- **Round 2 blockers (all fixed in body):** FavoriteCard missed → Step 2 now covers both cards; PlzBar unmount under modal → Step 1.2 uses `effectiveLocation` for gate; direct-hit close → Step 1.5 flag + Step 3 close-handler switch; iOS scroll-lock → three-layer mitigation in Step 3; hard-coded `key: 'default'` → `key: ''` with type-satisfying comment.
- **Round 3 blockers:** iOS `onTouchMove` predicate replaced with `overscroll-behavior: contain`-only policy (Safari 16+ scope documented); Step 4a share-button placement made deterministic (stub markup inserted here, behaviour wired in Step 5); test case 4 tightened to assert modal actually unmounts after direct-hit close; test case 6 wording fixed to capture pre-mount value; test case 17 added for nested-modal scroll reset; `useLocation` import drop made explicit in Step 4a.
- **Round 4 blockers (this revision):** import paths corrected (`./lib/modalLocation` / `./components/ListingDetailModal` from `App.tsx`); Step 4a stub-button JSX pinned verbatim with static un-copied styling and `[Step 5 → …]` annotations on the three sites Step 5 replaces; Step 4a now also covers the error-branch `<Link to={backTo}>` and drops the now-unused `Link` import; Step 6 pins the concrete harness for test case 4 (`createMemoryRouter` + `RouterProvider` + `waitFor` against the same router instance).

## Context & Goal

Three user-visible problems in one plan, because they all touch the same files:

1. **Lost place on back navigation.** Tapping a listing card navigates to `/listings/:id`, which unmounts `ListingsPage`. On back, infinite-scroll state is gone and scroll resets to 0. Painful on mobile.
2. **No share link.** A backlog item asks for a "Teilen" button that produces a direct URL to the listing.
3. **Detail view wastes space on wide screens.** On viewports ≥ 1000px the content sits in a narrow `max-w-2xl` (672px) column with the hero image stacked above a vertical metadata list. Lots of empty side gutters, lots of scrolling.

**Unified solution:** render the detail view as a **modal route** over the listings page (React Router "background location" pattern), widen the content, and restructure the desktop layout into a 3-column row (metadata left / hero image centre / metadata right) with the secondary sections (additional images, description, author's active listings, author's sold listings) stacked below at full width.

- Listings page stays mounted while the modal is open → scroll restore comes for free, no cache / hydration / fetch-skip logic.
- Share link stays `/listings/:id` — direct hits render the modal over a freshly-mounted background `/`.
- Desktop layout widens to ~80% of a FullHD viewport (hard cap 1536px via `max-w-screen-2xl`).
- Mobile layout stays stacked and single-column; no regression.

This plan subsumes the backlog entries *"Detail Page — Desktop Layout Redesign"* and *"Share-Link on Detail Page"*. Both are removed from `docs/backlog.md` as part of Step 7.

## Breaking Changes

**No.** URL schema, API contract, and route paths are unchanged. The in-page "Zurück zur Liste" link (`backTo`) on `DetailPage` is removed — the modal X button replaces it. That is a UI change, not a breaking change for data or routing.

## Assumptions & Risks

- **React Router v6 background-location pattern.** Navigating from `ListingsPage` attaches `{ background: currentLocation }` to `location.state`. The main `<Routes>` renders `location={background ?? location}`; a second `<Routes>` overlays the modal route when `background` is set. Direct hits on `/listings/:id` have no `background` → handled via `DirectHitDetailRedirect` (Step 1.5).
- **Scroll restoration is free.** `ListingsPage` never unmounts while the modal is open, so `document.scrollingElement.scrollTop` is preserved by the browser.
- **Risk: `isListingsPage` must follow the background location, not the raw URL.** `App.tsx:68` currently renders `PlzBar` only when `location.pathname === '/'`. When the modal opens, the URL becomes `/listings/:id`, `isListingsPage` flips to `false`, `PlzBar` unmounts, and on close it re-mounts — shifting the listings page's scroll position under the modal and defeating the whole plan. **Fix is part of Step 1:** compute `isListingsPage` from `(background ?? location).pathname`.
- **Risk: direct-hit close has no history to go back to.** A user opening a shared `/listings/:id` link in a **new tab** has exactly one history entry. `navigate(-1)` on the modal close does nothing visible (or tries to leave the page). **Fix is part of Step 1 + Step 3:** `DirectHitDetailRedirect` tags the synthesized state with `isDirectHit: true`; `ListingDetailModal` reads that flag and uses `navigate('/', { replace: true })` instead of `navigate(-1)` for close. Same-tab paste into an existing `/` session still gets clean back behaviour because the pre-existing `/` history entry remains.
- **Risk: direct-hit + first-visit collision.** On a fresh device (no `localStorage.rcn_category`), the background `ListingsPage` triggers its `CategoryModal`. Mitigated by the detail modal using an opaque aurora-deep background colour at `z-[60]` — one level above all existing modals (`FavoritesModal`, `CategoryModal`, first-visit `CategoryModal` in `ListingsPage`), which all sit at `z-50`. After the user closes the detail modal, the category modal is presented — correct onboarding flow.
- **Risk: iOS Safari scroll bleed.** `document.body.style.overflow = 'hidden'` alone is not enough on iOS Safari when the modal is itself a scroll container (`overflow-y-auto`). The user can rubber-band the body through the modal. Mitigation applied in Step 3:
  1. Lock body: `document.body.style.overflow = 'hidden'` (save and restore previous value on unmount).
  2. `overscroll-behavior: contain` on the modal wrapper via inline style — Safari 16+ honours this and alone is sufficient to stop scroll chaining into the body.
  Do **not** use `position: fixed` — it resets scrollY on iOS.
  **Scope note:** Safari ≤ 15 does not honour `overscroll-behavior` and will still rubber-band. Acceptable for this single-user hobby app on current hardware; if older iOS ever matters, add a `touchmove` listener that opts-out inner scrollers via a `data-modal-scroll` attribute. A naive `onTouchMove` with an `e.target === e.currentTarget` predicate would fail because the inner padding wrapper (`max-w-screen-2xl ... pb-20`) is neither the current target nor scrollable — touches starting there would be allowed through. Do not add such a handler; rely on `overscroll-behavior: contain`.
- **Risk: history when user chains details (A → card inside A → B).** Each nested card click pushes a new history entry with the **original** listings background (see Step 2). Back goes A → listings (not A → A again). Mitigation: card inside detail uses `background = state.background ?? location`, so nested modals never use another modal as their background.
- **Risk: `navigator.share` availability.** Feature-detect; fall back to `navigator.clipboard.writeText`. `navigator.share` can reject with `AbortError` when the user cancels the share sheet — swallow silently; do not fall through to clipboard in that specific case.
- **Risk: share URL uses `window.location.origin`.** On the VPN/VPS single-user deployment this reflects the URL the user typed. Acceptable for hobby scope; flagged for a future backlog item if a canonical public origin is ever introduced.
- **Risk: synthesized `Location` shape for `DirectHitDetailRedirect`.** Do not hard-code `key: 'default'` — it collides with React Router's own initial-entry key and can confuse RR when consumers compare location keys. Use `key: ''` to satisfy the `Location` type; React Router never reads the key off this synthesized object (it is only consumed as a `state.background` value for route matching and pathname comparison, never pushed into the history stack). Step 1.5 spells out the exact shape.
- **Risk: `getListingsByAuthor` SQL limit.** The backend query in `routes.py` returns up to **10** listings total (mixed aktuell + vergangen), not 10 per bucket. With many sold items, the split may show (e.g.) 8 aktuell + 2 vergangen rather than "all vergangen". This is acceptable — a plan extension to raise/split the limit is not in scope. Documented in Step 4c.
- **Fullscreen on all breakpoints** is the explicit UX decision. No desktop-centered modal variant.
- **Desktop layout breakpoint is `lg` (≥ 1024px).** The user's trigger was "ab 1000px"; Tailwind's `lg` is the nearest standard breakpoint and already used elsewhere in the codebase. Below `lg` the layout stays stacked as today.
- **Desktop width is capped at 1536px** (`max-w-screen-2xl`). At FullHD this is ≈ 80% viewport width as requested. At 1440px it fills the viewport with a small gutter. At 1280px it is effectively full-width.
- **Hero image on desktop keeps its existing visual size** by staying in a 6/12 centre column. At container width 1536px the image column is 768px wide — slightly wider than today's 672px, but bounded by `maxHeight: 360px` with `object-cover` so vertical size is unchanged.
- **"Aktuelle" vs "vergangene" listings of the author are distinguished by `is_sold`.** `is_sold === false` → aktuell; `is_sold === true` → vergangen. Filtering is client-side from the existing mixed response.
- **Risk: breaking the `backTo` flow on existing users.** The current `backTo` computed from `location.state.from` (see `DetailPage.tsx:142-145`) is no longer used. Step 4a deletes it. Any existing test that asserts the back link's `href` must be updated or removed.

## Reference Patterns

- React Router v6 "Modals" pattern (background location) — implementation reference.
- `frontend/src/App.tsx:67-68, 151-184` — the current `isListingsPage` gate and `<Routes>` block; both change in Step 1.
- `frontend/src/components/ListingCard.tsx:90, 185-192` — `<Link>` that gets `state={{ background }}`.
- `frontend/src/components/FavoriteCard.tsx:55-61` — `<Link>` that **also** gets `state={{ background }}` (Step 2).
- `frontend/src/pages/DetailPage.tsx:140-145` — confirms `location.state` is already consumed in this file (for the `backTo` link we're removing).
- `frontend/src/components/FavoritesModal.tsx`, `CategoryModal.tsx` — existing modal overlays; style/z-index reference (both `z-50` today → detail modal goes to `z-[60]`).
- `frontend/src/types/api.ts:24,61` — `is_sold` is present on both `ListingSummary` and `ListingDetail`; no backend change needed.
- `backend/app/api/routes.py:254-275` — confirms `getListingsByAuthor` returns mixed aktuell/vergangen with `limit=10`.

## Shared helper — `getBackground`

Both `App.tsx` (Step 1) and the two card components (Step 2) need to read `location.state.background`. Introduce one small helper to keep the state-shape in one place:

**File: `frontend/src/lib/modalLocation.ts`** (new)

```ts
import type { Location } from 'react-router-dom';

export interface ModalState {
  background?: Location;
  isDirectHit?: boolean;
}

export function getBackground(loc: Location): Location | undefined {
  return (loc.state as ModalState | null)?.background;
}

export function isDirectHit(loc: Location): boolean {
  return (loc.state as ModalState | null)?.isDirectHit === true;
}
```

All `as { background?: Location } | null` casts below use these helpers.

## Test files

- `frontend/src/components/__tests__/ListingDetailModal.test.tsx` — **new**.
- `frontend/src/__tests__/ModalRouting.test.tsx` — **new**.
- `frontend/src/components/__tests__/ListingCard.test.tsx` — **extend** with a background-state assertion.
- `frontend/src/components/__tests__/FavoriteCard.test.tsx` — **extend** with a background-state assertion.
- `frontend/src/pages/__tests__/DetailPage.test.tsx` — **new or extend** for share-button behaviour and the aktuell/vergangen split.

Concrete test cases:

1. **Modal opens over listings** — route `/` → navigate to `/listings/42` with `state.background = { pathname: '/' }`; assert both `ListingsPage` and `ListingDetailModal` are in the tree.
2. **Direct hit on `/listings/42`** — no `background` in state; `DirectHitDetailRedirect` emits a `<Navigate replace state={{ background: '/', isDirectHit: true }}>`; after that, the modal renders over a mounted background listings page.
3. **Close modal via `navigate(-1)`** — from a non-direct-hit entry: modal unmounts, listings remain.
4. **Direct-hit close — does NOT use `navigate(-1)`** — on a state flagged `isDirectHit: true`, close dispatches `navigate('/', { replace: true })`. After the navigation, re-render the tree with the new location (empty state, no `background`): assert `ListingDetailModal` is no longer present AND the listings page IS present. This proves the unmount chain (background=undefined → modal Routes branch does not render) and prevents a regression where someone later passes state through to `navigate('/')`.
5. **Scroll preserved across modal** — set `document.scrollingElement.scrollTop = 1000`; open modal; close; assert value unchanged.
6. **`body.style.overflow` lock/unlock** — read `document.body.style.overflow` before mount and capture the actual value (jsdom starts with `''`); mount modal → assert it is now `'hidden'`; unmount → assert the captured pre-mount value is restored (string equality, not a hard-coded `'visible'`). Also assert the modal wrapper's inline style attribute contains `overscroll-behavior: contain`.
7. **Scroll-lock cleanup when modal content changes (A → nested B)** — re-render the modal with a different listing id; assert body overflow stays `'hidden'` throughout (effect does not toggle between renders) and is restored to the original value only when the modal unmounts entirely.
8. **`PlzBar` stays mounted when modal is open over `/`** — mount App at `/listings/42` with `state.background = { pathname: '/' }`; assert `PlzBar` is in the tree (i.e. `isListingsPage` gate uses the background location).
9. **ListingCard propagates background** — card on the listings page renders `<Link state={{ background: <current location> }}>`.
10. **FavoriteCard propagates background** — card on `/favorites` renders `<Link state={{ background: <favorites location> }}>`; after closing the modal, the user is back on `/favorites`.
11. **Nested card inside detail propagates the ORIGINAL background** — card rendered inside the detail modal uses `state.background` (the listings location) as its own background, NOT the current detail location.
12. **Share button — `navigator.share` path** — mock as resolved; click; assert `share({ url: origin + '/listings/42', title })` called.
13. **Share button — clipboard fallback** — `navigator.share` undefined; mock `clipboard.writeText`; click; assert call + "kopiert!" feedback for ~2s.
14. **Share button — AbortError swallowed** — `navigator.share` rejects with `AbortError`; no error UI, no clipboard call.
15. **Author listings split** — DetailPage receives a mixed author list (some `is_sold=true`, some `false`); asserts two sections render with the correct items under each heading. If one group is empty, that section's heading is not rendered.
16. **Desktop layout at ≥ lg** — render with `window.innerWidth = 1280`; assert the 3-column grid container has the lg classes (smoke-test — assert class-name string contains `lg:grid-cols-12`; do NOT mock `matchMedia` or attempt to evaluate responsive variants).
17. **Modal scroll resets on nested navigation** — render the modal at `/listings/42`, scroll the wrapper to e.g. `scrollTop = 500`, re-render at `/listings/99` (still inside the modal); assert `wrapperRef.current.scrollTop === 0` after the pathname change.

## Steps

### Step 1 — Routing Wiring in App.tsx

**Status:** open

**File: `frontend/src/App.tsx`**

**1.1** Add imports: `Navigate`, `Location` from `react-router-dom`. `useLocation` is already imported. Import `ListingDetailModal` from `./components/ListingDetailModal` (Step 3) and `getBackground` from `./lib/modalLocation` (relative paths from `frontend/src/App.tsx`). The card files in Step 2 live under `frontend/src/components/` and import the helper as `'../lib/modalLocation'`.

**1.2** Inside `AuthenticatedAppInner`, compute the background and update the listings gate:

```tsx
const location = useLocation();
const background = getBackground(location);
const effectiveLocation = background ?? location;
const isListingsPage = effectiveLocation.pathname === '/';
```

The new `isListingsPage` keeps `PlzBar` mounted whenever the modal is open over `/` (avoids the bar flicker / scroll shift described in the Risks section).

**1.3** Background routes — change the current `<Routes>` (`App.tsx:165-183`) to use `location={effectiveLocation}`:

```tsx
<Routes location={effectiveLocation}>
  <Route path="/" element={<ListingsPage ... />} />
  <Route path="/listings/:id" element={<DirectHitDetailRedirect />} />
  <Route path="/profile" element={<ProfilePage ... />} />
  <Route path="/favorites" element={<FavoritesPage />} />
</Routes>
```

**1.4** Modal routes — immediately after, inside the same `<main>`:

```tsx
{background && (
  <Routes>
    <Route
      path="/listings/:id"
      element={
        <ListingDetailModal>
          <DetailPage />
        </ListingDetailModal>
      }
    />
  </Routes>
)}
```

**1.5** `DirectHitDetailRedirect` — define locally in `App.tsx`:

```tsx
function DirectHitDetailRedirect() {
  const location = useLocation();
  // Synthesize a background of "/" and flag this entry as a direct hit.
  // The modal close handler reads `isDirectHit` to decide between navigate(-1)
  // (normal in-app navigation, has history) and navigate('/', { replace: true })
  // (cold-open share link, no history to go back to).
  // `key: ''` satisfies the Location type; this synthesized object is only
  // consumed by route matching, never pushed into the history stack.
  return (
    <Navigate
      to={location.pathname + location.search}
      replace
      state={{
        background: { pathname: '/', search: '', hash: '', state: null, key: '' },
        isDirectHit: true,
      }}
    />
  );
}
```

### Step 2 — Cards: Pass Background Location

**Status:** open

Two card components link to `/listings/:id` and both need the same background propagation. Without updating FavoriteCard, navigating from `/favorites` into a detail and back lands the user on `/` instead of `/favorites` (regression).

**File: `frontend/src/components/ListingCard.tsx`**

Near the existing `useLocation()` call (line 90 currently assigns to `routerLocation`):

```tsx
import { getBackground } from '../lib/modalLocation';
// ...
const background = getBackground(routerLocation) ?? routerLocation;
```

Change the `<Link>` at line 186 to pass the new state:

```tsx
<Link
  to={`/listings/${listing.id}`}
  state={{ background }}
  className="..."
  style={...}
>
```

Replace the existing `state={{ from: routerLocation.search }}` (line 187) — the `from` pattern is the old `backTo` hook, removed in Step 4a.

**Why `state.background ?? location`:** when the card is rendered inside the detail modal (author's other listings), `useLocation()` returns the detail URL. Using it as the background for a nested navigation would make "back" from the second detail go to the first detail. Preferring `state.background` (the original listings location) keeps the modal stack flat.

**File: `frontend/src/components/FavoriteCard.tsx`**

Add `useLocation` import from `react-router-dom`; add `getBackground` import; at the top of the component body:

```tsx
const routerLocation = useLocation();
const background = getBackground(routerLocation) ?? routerLocation;
```

Change the `<Link>` at line 55 to include `state`:

```tsx
<Link
  to={`/listings/${listing.id}`}
  state={{ background }}
  className="..."
  style={...}
>
```

### Step 3 — Modal Overlay Component

**Status:** open

**File: `frontend/src/components/ListingDetailModal.tsx`** (new)

```tsx
import { useEffect, useCallback, useRef, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { isDirectHit } from '../lib/modalLocation';

interface Props { children: ReactNode }

export default function ListingDetailModal({ children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const directHit = isDirectHit(location);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => {
    if (directHit) {
      // No (or unreliable) history behind us — drop the modal and land on `/`.
      navigate('/', { replace: true });
    } else {
      navigate(-1);
    }
  }, [navigate, directHit]);

  // Scroll-lock on mount, restore previous value on unmount.
  // Empty deps — effect runs once per modal lifetime so that mid-modal
  // pathname changes (nested A → B) do NOT toggle overflow between renders.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  // Close on Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close]);

  // When the modal's pathname changes (nested card navigation), reset the
  // modal's own scroll position to the top so detail B does not open half-scrolled.
  useEffect(() => {
    if (wrapperRef.current) wrapperRef.current.scrollTop = 0;
  }, [location.pathname]);

  return (
    <div
      ref={wrapperRef}
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[60] overflow-y-auto"
      style={{ background: '#0F0F23', overscrollBehavior: 'contain' }}
    >
      <button
        type="button"
        onClick={close}
        aria-label="Detailansicht schließen"
        className="fixed top-3 right-3 z-[61] w-10 h-10 rounded-full flex items-center justify-center"
        style={{
          background: 'rgba(15,15,35,0.85)',
          border: '1px solid rgba(255,255,255,0.15)',
          color: '#F8FAFC',
          backdropFilter: 'blur(8px)',
        }}
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path d="M6 6l12 12M6 18L18 6" strokeLinecap="round" />
        </svg>
      </button>
      <div className="max-w-screen-2xl mx-auto px-3 pt-14 pb-20 sm:px-4 lg:px-6">
        {children}
      </div>
    </div>
  );
}
```

Notes:
- `z-[60]` sits exactly one level above every existing modal (`FavoritesModal`, both `CategoryModal` instances in `App.tsx:196` and `ListingsPage.tsx:184`, all `z-50`). Grep for `z-50` during implementation to confirm; if anything else already uses `z-60`, bump the detail modal to `z-[70]`.
- `overscrollBehavior: 'contain'` on the wrapper prevents scroll chaining to `<body>` in Safari 16+. No additional `onTouchMove` handler — see the iOS risk note in Assumptions for why a naive predicate would fail and why the `contain` policy is sufficient for current iOS.
- Scroll-reset effect on `location.pathname` fixes the nested-navigation UX where detail B would otherwise open at detail A's scroll offset.

### Step 4 — DetailPage Layout Refactor

Split into three smaller agent-sized units.

#### Step 4a — Remove `backTo` + widen container + insert share-button markup

**Status:** open

**File: `frontend/src/pages/DetailPage.tsx`**

1. Delete the `backTo` ref (lines ~142-145).
2. Delete BOTH back-link sites that reference `backTo`:
   - The main-render "← Zurück zur Liste" `<Link>` block (lines ~241-251) — delete entirely.
   - The error-branch `<Link to={backTo}>` block (lines ~178-184 — inside the `if (error || !listing)` return) — replace with a plain `<div>` rendering just the error text, or omit the back navigation from the error state altogether. Either way, no `Link` remains.
3. **Drop the `useLocation` and `Link` imports** from `react-router-dom` (line 2). After step 2 neither symbol has any consumer left in this file; leaving them triggers ESLint unused-import warnings.
4. Change the root container `<div className="max-w-2xl mx-auto pt-3 pb-6 sm:pt-0 sm:pb-10">` → `<div className="w-full pt-3 pb-6 sm:pt-0 sm:pb-10">`. The modal wrapper owns width.
5. **Insert the share-button markup** in the title-row action group (sibling of the favorite star / sold toggle), using the exact JSX below. Static (un-copied) styling is pinned here; Step 5 later replaces the three marked sites (onClick, style, icon) with the `shareCopied`-conditional versions from Step 5's code block. **Do NOT introduce the `shareCopied` state in this step** — it is added in Step 5.

   ```tsx
   <button
     onClick={() => {}}                                          {/* [Step 5 → handleShare] */}
     aria-label="Link zu diesem Inserat teilen"
     className="p-1.5 rounded-full transition-all duration-200"
     style={{                                                    {/* [Step 5 → conditional on shareCopied] */}
       background: 'rgba(255,255,255,0.06)',
       border: '1px solid rgba(255,255,255,0.1)',
     }}
   >
     {/* [Step 5 → conditional: check icon when shareCopied] */}
     <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="rgba(248,250,252,0.6)" strokeWidth={2} aria-hidden="true">
       <circle cx="18" cy="5" r="3" />
       <circle cx="6" cy="12" r="3" />
       <circle cx="18" cy="19" r="3" />
       <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
       <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
     </svg>
   </button>
   ```

   Test ownership split:
   - After 4a: `getByLabelText('Link zu diesem Inserat teilen')` finds the button (structural test passes).
   - After 5: click-behaviour tests (cases 12–14) pass.

#### Step 4b — Desktop 3-column hero row

**Status:** open

**File: `frontend/src/pages/DetailPage.tsx`**

Today's structure:
```
[Hero image — full width]
[Main card]
  [Title + actions]
  [Metadata grid — 2/3 cols]
  [Gallery]
  [Description]
[Author listings]
```

Restructure to:
```
[Main card]
  [Title + actions]                                  (full width)
  [LG 3-column row — stacked below lg]
    [Metadata column left]   [Hero image]   [Metadata column right]
  [Gallery]                                          (full width)
  [Description]                                      (full width)
[Aktuelle Inserate des Inserenten]                   (full width, Step 4c)
[Vergangene Inserate des Inserenten]                 (full width, Step 4c)
```

Implementation — wrap the hero + metadata-grid section in a new grid container:

```tsx
<div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-6 mb-6 pb-6"
     style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
  {/* Column 1: primary metadata */}
  <dl className="lg:col-span-3 flex flex-col gap-3">
    {/* Preis (highlighted) */}
    {/* Zustand */}
    {/* Versand */}
    {/* Ort (with Maps link) */}
    {/* Entfernung — if distanceKm != null */}
  </dl>

  {/* Column 2: hero image */}
  <div className="lg:col-span-6 order-first lg:order-none">
    {/* Existing hero <a><img ...></a> block, unchanged except:
        - remove the outer `mb-4` (gap comes from the grid now)
        - image: className="w-full h-full rounded-2xl object-cover"
          style={{ maxHeight: '360px', minHeight: '220px', border: ... }} */}
  </div>

  {/* Column 3: secondary metadata */}
  <dl className="lg:col-span-3 flex flex-col gap-3">
    {/* Original link */}
    {/* Inserent */}
    {/* Datum */}
    {/* Hersteller, Modell, Typ, Antrieb, Vollständigkeit — conditional as today */}
    {/* Dynamic LLM attributes */}
  </dl>
</div>
```

Below `lg`: `grid-cols-1` stacks everything; the `order-first lg:order-none` on the hero column pushes the image to the top on mobile, where the user expects it first (preserves today's mobile reading order).

Gallery and Description remain where they are today, structurally unchanged, just sitting below the new grid row.

The existing `col-span-2 md:col-span-1` on the old price block is no longer needed — removed as part of this refactor.

#### Step 4c — Author listings: aktuell vs. vergangen split

**Status:** open

**File: `frontend/src/pages/DetailPage.tsx`**

Replace the existing `{authorListings.length > 0 && (...)}` block (lines ~504-528) with:

```tsx
{authorListings.length > 0 && (() => {
  const aktuell = authorListings.filter((l) => !l.is_sold);
  const vergangen = authorListings.filter((l) => l.is_sold);
  return (
    <>
      {aktuell.length > 0 && (
        <AuthorListingsSection
          heading={`Weitere aktuelle Inserate von ${listing.author}`}
          items={aktuell}
        />
      )}
      {vergangen.length > 0 && (
        <AuthorListingsSection
          heading={`Vergangene Inserate von ${listing.author}`}
          items={vergangen}
        />
      )}
    </>
  );
})()}
```

Extract the existing rendering into a small local component `AuthorListingsSection` (same file) that takes `heading: string; items: ListingSummary[]` and renders the header + grid. Grid: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4` — one extra column at `xl` to make use of the wider container. Card styling stays identical to today.

**Important caveat** (also captured in Assumptions & Risks): the backend query limits author listings to **10 total** (`routes.py:254-275`). Both buckets share that budget — a user with 15 sold listings will not see all 15 under "vergangen". Raising the limit or adding per-bucket fetches is out of scope.

### Step 5 — Share Button Behaviour

**Status:** open

**File: `frontend/src/pages/DetailPage.tsx`**

The button markup was already inserted in Step 4a with a stub `onClick={() => {}}`. In this step:

1. Add the `shareCopied` state and the `handleShare` function shown below.
2. Replace the stub `onClick={() => {}}` with `onClick={handleShare}`.
3. Replace the static button styling with the conditional styling (copied-state visuals) shown below.

```tsx
const [shareCopied, setShareCopied] = useState(false);

async function handleShare() {
  if (!listing) return;
  const url = `${window.location.origin}/listings/${listing.id}`;
  const title = listing.title ?? 'RC-Network Inserat';

  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ url, title });
      return;
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      // Other errors fall through to clipboard fallback.
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 2000);
  } catch {
    // Clipboard unavailable — no UI fallback for this hobby scope.
  }
}
```

Button markup (mirrors favorite/sold toggle styling):

```tsx
<button
  onClick={handleShare}
  aria-label="Link zu diesem Inserat teilen"
  className="p-1.5 rounded-full transition-all duration-200"
  style={{
    background: shareCopied ? 'rgba(45,212,191,0.15)' : 'rgba(255,255,255,0.06)',
    border: `1px solid ${shareCopied ? 'rgba(45,212,191,0.35)' : 'rgba(255,255,255,0.1)'}`,
  }}
>
  {shareCopied ? (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="#2DD4BF" strokeWidth={2} aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ) : (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="rgba(248,250,252,0.6)" strokeWidth={2} aria-hidden="true">
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  )}
</button>
```

Optional transient "Link kopiert!" text adjacent to the icon when `shareCopied === true` — implementer choice.

### Step 6 — Tests

**Status:** open

Implement the 17 test cases listed under **Test files**. Notes:

- Use `MemoryRouter` with `initialEntries`/`initialIndex` to set up background-location states deterministically.
- **Test case 4 harness (direct-hit close → unmount):** a fresh `<MemoryRouter initialEntries={['/']}>` proves nothing — it would just set up a different starting state. Use one of these patterns instead:
  1. **Preferred:** `createMemoryRouter([...routes], { initialEntries: ['/listings/42'], initialIndex: 0 })` with the initial entry's `state` set to `{ background: {...}, isDirectHit: true }`, wrap in `<RouterProvider router={router}/>`. After firing the close click, use `await waitFor(() => { ... })` and assert both `router.state.location.pathname === '/'` AND `screen.queryByRole('dialog')` returns `null`. This proves the navigate call AND the unmount, against the same router instance.
  2. **Alternative:** mount a sentinel `<Route path="*" element={<Probe/>} />` that writes `useLocation().pathname` into a ref or test-global; after the click, `waitFor` the probe to report `'/'`, then assert `queryByRole('dialog')` is null.
  The synchronous `queryByRole` immediately after `fireEvent.click` may see a stale tree — always `waitFor` first so React flushes the navigation.
- For `navigator.share` / `navigator.clipboard` mocking, follow the pattern in `FavoritesModal.test.tsx` (`vi.stubGlobal` or `Object.defineProperty`).
- For scroll preservation (case 5), set `document.scrollingElement.scrollTop` before modal mount and assert it after unmount. If jsdom clamps the value, spy on `window.scrollTo` and assert it is never called during the modal lifecycle.
- For the overscroll-behavior assertion (case 6), read the inline style attribute — jsdom does not compute CSS but does reflect inline styles.
- For scroll-lock across re-renders (case 7), render the modal twice with different children props and assert the body overflow stays `'hidden'` between renders.
- For the `PlzBar` gate (case 8), mount the full `AuthenticatedAppInner` subtree at a `/listings/:id` URL with a synthesized background — assert PlzBar's recognisable text ("Filter" or a specific control) is present.
- For the desktop layout smoke test (case 16), set `window.innerWidth` and fire a `resize` event if needed; assert only on class-name presence, not on computed pixel widths.
- For the author-listings split (case 15), use a fixture with at least one sold and one not-sold listing.
- Existing `ListingCard.test.tsx` and `FavoriteCard.test.tsx` must be updated if they assert the `<Link>` has no `state` prop.

### Step 7 — Backlog Cleanup

**Status:** open

**File: `docs/backlog.md`**

Remove both entries now delivered:
- *"Share-Link on Detail Page"*
- *"Detail Page — Desktop Layout Redesign"*

If `Done` is the established location for delivered items in this file, move them there instead of deleting — check the current structure at apply time.

## Verification

Run from the repo root:

```bash
cd frontend
npm run test -- --run
npm run build
npm run lint
```

Manual check on a dev build:

1. **Mobile (viewport ≤ sm):** open `/`, scroll down 2–3 infinite-scroll trigger points, tap a card → modal opens, scroll is locked. Close (X, Escape, back) → listings page at exact previous scroll. Layout inside modal is stacked, hero image above metadata list — no regression.
2. **Desktop (viewport ≥ 1024px):** open any listing → 3-column row visible (primary metadata left, hero centre, secondary metadata right). Container fills ~80% at FullHD, less on 1280/1440. Gallery + description full width below. Author's active listings below in their own section, then sold listings in a second section.
3. **Nested navigation:** open detail A → scroll to "Weitere aktuelle Inserate" → tap one → detail B replaces the modal. Browser back → detail A. Back again → listings page, same scroll position.
4. **Favorites entry:** open `/favorites`, tap a card → modal opens; close → back on `/favorites` (not `/`).
5. **Share button:**
   - Mobile (HTTPS build): share sheet opens with the correct URL + title.
   - Desktop: "kopiert!" feedback for ~2s; pasted URL opens the same listing.
6. **Direct link, new tab:** copy URL; paste into a **new browser tab** → detail modal opens over a loading/loaded listings page. Close → listings page is interactive, scrollY = 0. No stranded modal.
7. **Direct link, same tab paste:** on an existing `/` tab, paste the URL into the address bar and enter → same behaviour; close via back brings the user to the previous `/` state.
8. **Reload with modal open:** F5 on a `/listings/:id` URL → direct-hit flow runs, modal re-opens over fresh listings.
9. **iOS Safari (real device or accurate emulator):** modal open, try scrolling the background through the modal's padding — scroll is blocked, scroll position underneath does not change; modal content column still scrolls normally; close modal, scroll position intact.
10. **PlzBar stability:** open `/`, open a detail → PlzBar remains in place under the modal, does not flicker; close → no visible layout shift.
11. **First-visit + shared link:** on a fresh browser profile, open a shared `/listings/:id` → detail modal visible; category selection modal hidden behind opaque overlay. Close detail → category modal comes forward.
