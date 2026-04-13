# Changelog

## [1.0.0] - 2026-04-13

### Added

**Auth & Roles**
- User role enum (`member` / `admin`) on the `users` table — default `member`
- "Als verkauft markieren" button on detail page visible to admins only
- Scrape-Log button in header visible to admins only
- Admin role auto-assigned via `init_db` migration for configured email

**Detail Page**
- Hero image (first image, full-width) above the content card
- Remaining images shown as a scrollable gallery below the description
- "Weitere von {author}" section at the bottom — 3-column grid on desktop, single column on mobile
- `GET /api/listings/by-author` endpoint for fetching listings by the same author

**Mobile UI**
- Sticky full-width search bar with PLZ status indicator (green location icon / red "!" badge)
- Filter bottom sheet modal with slide-up animation via `createPortal`, swipe-down to dismiss
- Backdrop tap to close filter modal
- X button removed from filter modal (replaced by swipe + backdrop tap)
- Mobile footer Merkliste badge replaced with a dot (count shown on Merkliste page instead)
- Unread badge on "Suchen" tab in FavoritesPage (fix: `markViewed` called only on unmount)
- Back button removed from Profile page (footer handles navigation)
- Spacing above "← Zurück zur Liste" button on detail page

**Desktop UI**
- Second sticky bar (PlzBar) with search, sort, filter popover, and person dropdown
- Filter popover: category, distance, price range
- Person dropdown: user avatar with initials, "Mein Standort" PLZ input, logout
- PLZ status indicator in search input (green chip / red "!") — opens person dropdown on click
- Merkliste button moved to main header with unread count badge

**Filters**
- Price range filter (`price_min` / `price_max`) on both desktop popover and mobile modal
- Backend validates `price_min <= price_max`, filters on `price_numeric` column

**Login Page**
- Slim footer with Datenschutzerklärung link
- Privacy policy modal (scrollable, closeable)

**PWA**
- Install prompt
- Homescreen icon

### Fixed
- Mobile search bar now truly sticky (removed `pt-4` top padding that caused pre-sticky scroll)
- Filter panel full-width on mobile via `-mx-3`
- Bottom sheet z-index issue resolved via `createPortal` (sticky parent created stacking context)
- Trash button on FavoriteCard aligned to card padding (`top-3` instead of `top-0`)
- Unread badge visible during Merkliste page visit (deferred `markViewed` to unmount)
- Input text color softened from pure white to `rgba(248,250,252,0.85)`

### Infrastructure
- CI deploys only on GitHub Release (not on every push to `main`)
- HSTS, security headers, health check on deploy
- Deploy splits into separate build and deploy jobs
