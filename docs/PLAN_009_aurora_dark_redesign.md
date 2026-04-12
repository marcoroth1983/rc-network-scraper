# PLAN_009 — Aurora Dark UI Redesign

## Context & Goal

The app currently uses a light theme (white cards, #F5F5F7 surface, blue brand
accents). PLAN_008 introduces a login page in "Aurora Dark" style — dark
background with animated gradient blobs, translucent glassmorphic cards, and
atmospheric lighting. This plan brings the entire app into the same Aurora Dark
design language so the experience is visually coherent from login to listings.

Visual reference: `docs/mockup_login.html` → "Aurora Dark" tab.

Scope:
- Define Aurora Dark design tokens (Tailwind config)
- Redesign all 7 components: PlzBar, FilterPanel, ListingCard, FavoriteCard,
  FavoritesModal, ScrapeLog, Pagination
- Redesign 2 pages: ListingsPage, DetailPage
- Redesign App.tsx header + loading state
- Aurora background with animated gradient blobs (shared layout element)

Out of scope: Login page (handled by PLAN_008), backend changes, new features.

Depends on: PLAN_008 (login page establishes the Aurora baseline).

### Implementation Constraint: ui-ux-pro-max Skill

The coder agent implementing this plan **must** use the `ui-ux-pro-max` skill
(via `search.py --domain`) to look up UX best practices before writing each
component. The design tokens in this plan define *what* the components look like;
the skill provides *how* to build them correctly (interaction patterns, contrast,
animation timing, accessibility).

Required lookups per step:

| Step | Skill query (--domain) | Purpose |
|------|------------------------|---------|
| 3 (Header) | `ux "sticky header dark blur navigation"` | Nav patterns, blur performance |
| 4 (PlzBar) | `ux "input field dark theme focus states"` | Dark input contrast, focus rings |
| 5 (FilterPanel) | `ux "filter controls dark dropdown"` | Form controls on dark backgrounds |
| 6 (ListingCard) | `ux "card hover dark mode glow shadow"` | Hover states, image contrast |
| 7 (Pagination) | `ux "pagination dark disabled states"` | Disabled opacity, touch targets |
| 8–9 (Favorites) | `ux "modal overlay dark glassmorphism"` | Scrim opacity, dismiss patterns |
| 10 (ScrapeLog) | `ux "dropdown panel dark animation"` | Dropdown timing, z-index |
| 11 (DetailPage) | `ux "detail page dark image gallery"` | Image display on dark BG |
| Before verification | `ux "dark mode contrast accessibility reduced-motion"` | Final a11y check |

The skill script is located at:
```
<ui-ux-pro-max-skill>/scripts/search.py "<query>" --domain ux
```

---

## Breaking Changes

**No.** This is a purely visual change. No API changes, no data model changes,
no route changes. The app looks different but behaves identically.

---

## Approval Table

| Approval | Status  | Date |
|----------|---------|------|
| Reviewer | approved | 2026-04-11 |
| Human    | approved | 2026-04-12 |

---

## Reference Patterns

- Aurora Dark login: `docs/mockup_login.html` → "Aurora Dark" tab
- Current light components: `frontend/src/components/*.tsx`
- Current Tailwind config: `frontend/tailwind.config.js`

---

## Design System — Aurora Dark Tokens

### Colors

| Token              | Value                          | Usage                          |
|--------------------|--------------------------------|--------------------------------|
| `--bg-deep`        | `#0f0f23`                      | Page background                |
| `--bg-card`        | `rgba(15, 15, 35, 0.6)`       | Card/panel background          |
| `--bg-elevated`    | `rgba(255, 255, 255, 0.05)`   | Hover states, input backgrounds|
| `--border`         | `rgba(255, 255, 255, 0.08)`   | Card borders, dividers         |
| `--border-hover`   | `rgba(255, 255, 255, 0.15)`   | Hover border emphasis          |
| `--text-primary`   | `#F8FAFC`                      | Headings, primary text         |
| `--text-secondary` | `rgba(248, 250, 252, 0.65)`   | Body text, descriptions        |
| `--text-muted`     | `rgba(248, 250, 252, 0.35)`   | Hints, timestamps              |
| `--accent-indigo`  | `#6366F1`                      | Primary accent (links, active) |
| `--accent-violet`  | `#A78BFA`                      | Icon accents, highlights       |
| `--accent-pink`    | `#EC4899`                      | Secondary accent, gradients    |
| `--accent-teal`    | `#2DD4BF`                      | Success, positive indicators   |
| `--price`          | `#FDE68A`                      | Price display (warm yellow)    |
| `--badge-new`      | `#34D399`                      | "NEU" badge                    |
| `--glow-indigo`    | `rgba(99, 102, 241, 0.15)`    | Card hover glow                |

### Shadows & Effects

| Effect           | Value                                                             |
|------------------|-------------------------------------------------------------------|
| Card shadow      | `0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.2)`    |
| Card hover       | `0 0 30px rgba(99,102,241,0.12), 0 8px 24px rgba(0,0,0,0.25)`   |
| Backdrop blur    | `blur(20px) saturate(1.2)`                                       |
| Border           | `1px solid rgba(255,255,255,0.08)`                                |
| Border radius    | Cards: `16px`, Buttons/Inputs: `12px`, Badges: `8px`             |

### Typography

| Element   | Size   | Weight | Color           |
|-----------|--------|--------|-----------------|
| Page h1   | 24px   | 700    | text-primary    |
| Card title| 15px   | 600    | text-primary    |
| Body      | 14px   | 400    | text-secondary  |
| Small     | 13px   | 400    | text-secondary  |
| Hint      | 12px   | 400    | text-muted      |
| Price     | 18px   | 700    | price (yellow)  |

### Aurora Background

Shared background element used as a layout wrapper. Three animated gradient
blobs (`radial-gradient`) with `blur(80px)`, low opacity (0.15–0.25). Uses a
custom `aurora-drift` animation (8–12s period, slow translate + scale shift)
instead of Tailwind's `animate-pulse` (which is only 2s and barely visible for
this use case). Define custom keyframes in Tailwind config or `index.css`.
Applied once in the root layout, not repeated per page.

---

## Steps

---

### Step 1 — Tailwind config: Aurora Dark tokens [ open ]

**File:** `frontend/tailwind.config.js`

Extend the existing config with Aurora Dark color tokens. Keep existing light
colors (they may be needed for transition period or fallback).

Add under `theme.extend.colors`:

```js
aurora: {
  deep: '#0f0f23',
  card: 'rgba(15, 15, 35, 0.6)',
  elevated: 'rgba(255, 255, 255, 0.05)',
  border: 'rgba(255, 255, 255, 0.08)',
  'border-hover': 'rgba(255, 255, 255, 0.15)',
  'text-primary': '#F8FAFC',
  'text-secondary': 'rgba(248, 250, 252, 0.65)',
  'text-muted': 'rgba(248, 250, 252, 0.35)',
  indigo: '#6366F1',
  violet: '#A78BFA',
  pink: '#EC4899',
  teal: '#2DD4BF',
  price: '#FDE68A',
  'badge-new': '#34D399',
  'glow-indigo': 'rgba(99, 102, 241, 0.15)',
},
```

Add under `theme.extend.boxShadow`:

```js
'aurora-card': '0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.2)',
'aurora-hover': '0 0 30px rgba(99,102,241,0.12), 0 8px 24px rgba(0,0,0,0.25)',
```

Add under `theme.extend.animation` and `theme.extend.keyframes`:

```js
animation: {
  'aurora-drift': 'aurora-drift 10s ease-in-out infinite alternate',
},
keyframes: {
  'aurora-drift': {
    '0%':   { transform: 'translateY(0) scale(1)',    opacity: '0.2' },
    '100%': { transform: 'translateY(-30px) scale(1.05)', opacity: '0.12' },
  },
},
```

Also update `frontend/src/index.css`: replace the existing `.shimmer` keyframe
colors (`#f0f0f0`, `#e0e0e0`) with dark-theme equivalents (`#1a1a2e`, `#252540`)
and update `.card-transition:hover` shadow to use the `aurora-hover` shadow value.

---

### Step 2 — Aurora layout wrapper (`frontend/src/components/AuroraBackground.tsx`) [ open ]

New file. Shared background with animated gradient blobs. Used once in `App.tsx`
to wrap the entire authenticated app.

```tsx
export default function AuroraBackground({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen bg-aurora-deep">
      {/* Animated gradient blobs — use custom aurora-drift animation (defined in tailwind.config.js) */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-[-20%] left-[10%] w-[60%] h-[60%] rounded-full opacity-20 blur-[100px] animate-aurora-drift"
             style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.4), transparent 70%)' }} />
        <div className="absolute bottom-[-10%] right-[5%] w-[50%] h-[50%] rounded-full opacity-[0.15] blur-[100px] animate-aurora-drift"
             style={{ background: 'radial-gradient(circle, rgba(236,72,153,0.3), transparent 70%)', animationDelay: '3s', animationDirection: 'alternate-reverse' }} />
        <div className="absolute top-[40%] right-[25%] w-[35%] h-[35%] rounded-full opacity-10 blur-[80px] animate-aurora-drift"
             style={{ background: 'radial-gradient(circle, rgba(45,212,191,0.3), transparent 70%)', animationDelay: '6s' }} />
      </div>
      {/* Content */}
      <div className="relative z-10">
        {children}
      </div>
    </div>
  )
}
```

---

### Step 3 — App.tsx: Aurora wrapper + header redesign [ open ]

**File:** `frontend/src/App.tsx`

**Prerequisite:** PLAN_008 must be implemented first. After PLAN_008, `App.tsx`
contains an `AuthenticatedApp` sub-component with header, PlzBar, routes, and
FavoritesModal. If PLAN_008's App.tsx structure differs from what's described
here, adapt accordingly — the goal is to wrap the authenticated layout in
`<AuroraBackground>` and restyle the header.

Changes:
1. Wrap `AuthenticatedApp` in `<AuroraBackground>`
2. Redesign header: translucent dark background with `backdrop-filter: blur(12px)`,
   white text, subtle bottom border
3. Update loading state to match dark theme (dark background, light text)

Header style reference:
- Background: `rgba(15, 15, 35, 0.8)` with `backdrop-blur-lg`
- Logo text: `#A78BFA` (violet accent)
- Border bottom: `rgba(255, 255, 255, 0.06)`
- User email / logout: `rgba(248, 250, 252, 0.5)` / violet accent

---

### Step 4 — PlzBar redesign [ open ]

**File:** `frontend/src/components/PlzBar.tsx`

Convert from light sticky bar to Aurora style:
- Background: translucent dark (`rgba(15, 15, 35, 0.7)`) with `backdrop-blur`
- Input: dark inset (`rgba(255,255,255,0.05)`), light border, white text
- City label: `text-secondary`
- Favorites button: violet accent border, translucent background
- Sticky positioning preserved (z-30)

---

### Step 5 — FilterPanel redesign [ open ]

**File:** `frontend/src/components/FilterPanel.tsx`

Convert from light panel to Aurora style:
- Background: translucent card style
- Search input, distance slider, sort dropdown: dark inputs with subtle borders
- Active sort option: indigo accent
- Labels: `text-muted`
- Sticky positioning preserved (z-20)
- **Important:** Re-verify the sticky `top` offset value (currently `top-[6.25rem]`)
  after Steps 3–4, in case header or PlzBar height changed

---

### Step 6 — ListingCard redesign [ open ]

**File:** `frontend/src/components/ListingCard.tsx`

This is the most visible component. Convert to Aurora card:
- Card background: `aurora-card` with border `rgba(255,255,255,0.08)`
- Hover: glow shadow (`aurora-hover`), border brightens to 0.15
- Image area: unchanged (photos remain as-is)
- Title: `text-primary`
- Price: warm yellow (`#FDE68A`), bold
- Location/distance: `text-secondary`
- Date: `text-muted`
- Favorite star: `#FDE68A` when active
- "NEU" badge: teal (`#34D399`) background with dark text
- "Verkauft" overlay: semi-transparent dark overlay

---

### Step 7 — Pagination redesign [ open ]

**File:** `frontend/src/components/Pagination.tsx`

Simple conversion:
- Buttons: translucent background, white text, subtle border
- Active/current page: indigo accent
- Disabled: reduced opacity

---

### Step 8 — FavoriteCard redesign [ open ]

**File:** `frontend/src/components/FavoriteCard.tsx`

Same card style as ListingCard but horizontal layout:
- Dark translucent card, subtle border
- Remove button: red accent on hover

---

### Step 9 — FavoritesModal redesign [ open ]

**File:** `frontend/src/components/FavoritesModal.tsx`

- Backdrop: darker overlay (`rgba(0, 0, 0, 0.6)`) with blur
- Modal card: Aurora card style (translucent dark, border, rounded-2xl)
- Header/close button: white text, subtle hover
- "Verkaufte entfernen" button: translucent with teal accent

---

### Step 10 — ScrapeLog redesign [ open ]

**File:** `frontend/src/components/ScrapeLog.tsx`

- Dropdown panel: Aurora card style
- Status indicators: teal (success), pink (error)
- Timestamps: `text-muted`
- Border between entries: `rgba(255,255,255,0.06)`

---

### Step 11a — DetailPage redesign: layout + metadata [ open ]

**File:** `frontend/src/pages/DetailPage.tsx`

Largest page (267 lines). Split into two sub-steps to keep agent context
manageable.

This step covers the outer layout and metadata:
- Back button: translucent with violet accent
- Main content card wrapper: Aurora card style (translucent, border, rounded)
- Metadata grid (title, price, location, distance, date, seller): dark inset
  sections with `rgba(255,255,255,0.03)` background
- Price: warm yellow (`#FDE68A`), prominent
- Google Maps link: indigo accent
- Loading and error states: dark-themed

---

### Step 11b — DetailPage redesign: gallery + actions [ open ]

**File:** `frontend/src/pages/DetailPage.tsx`

Continues the DetailPage redesign:
- Image gallery: dark background, subtle border around thumbnails, maintain
  existing click/navigation behavior
- Description section: `text-secondary` on dark background
- Sold toggle button: translucent with pink accent when sold, confirmation
  dialog preserved
- Favorite toggle: yellow star on dark, same behavior as ListingCard

---

### Step 12 — ListingsPage: grid and empty states [ open ]

**File:** `frontend/src/pages/ListingsPage.tsx`

- Results count text: `text-secondary`
- Loading skeleton: dark shimmer animation
- Empty state: `text-muted` with subtle icon
- Grid gap and responsive behavior: unchanged

---

## Verification

```bash
# 1. Start frontend dev server
cd frontend && npm run dev

# 2. Visual checks (browser at http://localhost:4200):
#    - Page background is dark (#0f0f23) with animated gradient blobs
#    - Header is translucent dark with blur
#    - All cards have dark translucent backgrounds with subtle borders
#    - Text is readable (white/light on dark)
#    - Prices are warm yellow
#    - Hover states show indigo glow
#    - NEU badge is teal
#    - Responsive: check 375px, 768px, 1280px viewports

# 3. Type check
cd frontend && npx tsc --noEmit

# 4. Run existing tests (should still pass — no behavioral changes)
cd frontend && npx vitest run

# 5. Contrast check: primary text on card background ≥ 4.5:1
#    #F8FAFC on rgba(15,15,35,0.6) over #0f0f23 ≈ 14:1 ✓
```
