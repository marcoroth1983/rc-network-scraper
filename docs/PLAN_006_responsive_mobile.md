# PLAN_006: Responsive / Mobile Layout

| Approval | Status  | Date |
|----------|---------|------|
| Reviewer | approved | 2026-04-10 |
| Human    | approved | 2026-04-10 |

## Context & Goal

The frontend is desktop-optimized. On mobile (<640px), the FilterPanel's horizontal flex row (search + distance + sort) gets cramped, the filter area scrolls out of view, and touch targets are undersized. Goal: make the entire UI mobile-first responsive with a sticky search/filter bar.

## Breaking Changes

No. Pure CSS/layout changes with no API or data model impact.

## Steps

### Step 1: FilterPanel — stack layout + sticky `[done]`

**File:** `frontend/src/components/FilterPanel.tsx`

Current: single `flex gap-3 items-center` row with search, distance (`w-40` = 160px), sort (`w-52` = 208px).

Changes:
- Make the outer container sticky: `sticky top-[6.25rem] z-20` (below Header 3.5rem + PlzBar 2.75rem).
- Remove rounded corners when sticky to avoid gap with PlzBar: `rounded-none sm:rounded-card`.
- Search input on its own row (full width).
- Distance + Sort in a second row below search: replace fixed widths with `flex-1` on mobile. Use `flex-1 sm:w-40 sm:flex-none` for distance and `flex-1 sm:w-52 sm:flex-none` for sort.
- On `sm:` and up, revert to single-row horizontal layout (search flex-1, distance + sort beside it).
- Reduce bottom margin: `mb-6` → `mb-4 sm:mb-6`.

Tailwind approach:
```
Outer wrapper: sticky top-[6.25rem] z-20 rounded-none sm:rounded-card
Inner layout:  flex flex-col sm:flex-row sm:items-center gap-3
Distance:      flex-1 sm:w-40 sm:flex-none (removes w-40 shrink-0 on mobile)
Sort:          flex-1 sm:w-52 sm:flex-none (removes w-52 shrink-0 on mobile)
Row 2 wrapper: flex gap-3 (groups distance+sort on mobile)
```

### Step 2: PlzBar — mobile touch targets `[done]`

**File:** `frontend/src/components/PlzBar.tsx`

Changes:
- PLZ input: `py-1` → `py-1.5` for better touch target height (~40px).
- Merkliste button: hide text on mobile, show only star icon. Use `hidden sm:inline` on the text label.
- City label: `text-sm` → `text-xs sm:text-sm` to save space on narrow screens.

### Step 3: FavoritesModal — mobile fullscreen `[done]`

**File:** `frontend/src/components/FavoritesModal.tsx`

Changes:
- Modal container: on mobile, fill viewport. `w-full max-w-2xl` → `w-full sm:max-w-2xl`.
- Rounded corners: `rounded-2xl` → `rounded-none sm:rounded-2xl` (fullscreen = no rounding on mobile).
- Outer wrapper vertical padding: `py-8` → `py-0 sm:py-8`.
- Body max-height: `max-h-[70vh]` → `max-h-[80vh] sm:max-h-[70vh]`.

### Step 4: FavoriteCard — responsive thumbnail `[done]`

**File:** `frontend/src/components/FavoriteCard.tsx`

Changes:
- Thumbnail: `w-24 h-20` → `w-20 h-16 sm:w-24 sm:h-20` to fit better on narrow screens.

### Step 5: DetailPage — mobile field grid + images `[done]`

**File:** `frontend/src/pages/DetailPage.tsx`

Changes:
- Fields grid: keep `grid-cols-2` on mobile (field labels are short enough), change to `grid-cols-2 md:grid-cols-3` (drop `sm:` breakpoint).
- Title + actions: `flex items-start justify-between` → stack on mobile with `flex-col sm:flex-row`.
- Images gallery: add `overflow-x-auto` and `flex-nowrap sm:flex-wrap` for horizontal scroll on mobile.
- Back link + title padding: `p-6` → `p-4 sm:p-6`.

### Step 6: Pagination — touch-friendly buttons `[done]`

**File:** `frontend/src/components/Pagination.tsx`

Changes:
- Buttons: `px-4 py-2` → `px-3 py-2.5 sm:px-4 sm:py-2` for taller touch targets on mobile.
- Font size: keep `text-sm`.

### Step 7: ListingCard — minor mobile tweaks `[done]`

**File:** `frontend/src/components/ListingCard.tsx`

Changes:
- Footer text: `text-xs` is fine, but add `flex-wrap` fallback if location text is very long.
- Price: `text-xl` → `text-lg sm:text-xl` to prevent overflow on narrow cards.

### Step 8: App.tsx — main content padding `[done]`

**File:** `frontend/src/App.tsx`

Changes:
- Main content: `px-4 py-6` → `px-3 py-4 sm:px-4 sm:py-6` for tighter mobile margins.

### Step 9: ScrapeLog dropdown — mobile clipping `[done]`

**File:** `frontend/src/components/ScrapeLog.tsx`

Changes:
- Dropdown width: `w-72` → `w-64 sm:w-72` to fit 375px screens with header padding.
- Add `right-0` (already present) — verify it does not clip left edge on mobile.

## Reviewer Remarks

- Blocking #1 (fixed): FilterPanel distance+sort fixed widths replaced with `flex-1` on mobile.
- Blocking #2 (fixed): Step status fields added.
- Blocking #3 (fixed): Reviewer Section added.
- Note #2 (incorporated): DetailPage keeps `grid-cols-2` on mobile.
- Note #1 (FavoriteCard button text): deferred — not critical for first pass.

## Verification

```bash
cd frontend && npx tsc --noEmit
cd frontend && npx vitest run
```

Manual: open browser DevTools, test at 375px, 414px, 768px, 1024px widths. Verify:
- FilterPanel is sticky and does not overlap PlzBar
- Search is on its own line on mobile, inline on tablet+
- All touch targets >= 44px height
- FavoritesModal fills screen on mobile
- DetailPage fields stack on mobile
- No horizontal scroll on any viewport
