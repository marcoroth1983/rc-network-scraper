# Admin Console — Styleguide

> Design reference for the standalone admin/support console ("RC-Scout Ops").
> Tokens extracted **1:1 from the Coinza reference dashboard**. Colors are best-effort
> visual estimates from the reference image — verify against the source PNG before locking.
>
> **Deliberate departure:** this is NOT the violet glassmorphism of the user-facing PWA.
> The console uses a neutral near-black surface scale with green/red financial accents and
> a blue primary action. This visual separation is intentional (operator tool ≠ end-user app).

## Library Stack

| Concern | Library | Note |
|---|---|---|
| Primitives / layout | **shadcn/ui** (Radix + Tailwind) | Sidebar, Card, Table, Badge, Button, DropdownMenu, Command (⌘K), Tooltip, Avatar. Copy-in, no runtime lock-in. **Not Mantine.** |
| Charts | **Recharts** | Area/Line/Bar + sparklines, gradient fills, tooltip bubble. |
| Icons | **lucide-react** | Matches the reference line-icon style (shadcn default). |
| Styling | **Tailwind CSS** | Already in project stack. |
| Font | **Inter** (`@fontsource/inter`) | Geometric sans, dashboard standard. `tabular-nums` for all figures. |

## Color Tokens

Neutral surface scale (near-black, NOT pure `#000`):

| Token | Hex | Usage |
|---|---|---|
| `--bg-app` | `#0D0D0D` | Main content background |
| `--bg-sidebar` | `#0A0A0A` | Sidebar (one step darker than app) |
| `--surface` | `#161616` | Cards, KPI tiles, chart card |
| `--surface-2` | `#1C1C1C` | Nested controls (search box, token rows, tooltip) |
| `--surface-active` | `#242424` | Active nav pill, hover state |
| `--border` | `#262626` | Card / divider borders (≈ `rgba(255,255,255,0.07)`) |
| `--border-subtle` | `rgba(255,255,255,0.05)` | Table row dividers, hairlines |

Text:

| Token | Hex | Usage |
|---|---|---|
| `--text-primary` | `#FAFAFA` | Headings, values |
| `--text-secondary` | `#A1A1AA` | Labels, secondary values |
| `--text-tertiary` | `#6B6B70` | Section nav labels (uppercase), chart axis labels |

Accents:

| Token | Hex | Pill background | Usage |
|---|---|---|---|
| `--primary` (blue) | `#2E6BFF` | — | Primary CTA (e.g. "Swap" button → our primary actions) |
| `--success` (green) | `#3FD984` | `rgba(63,217,132,0.12)` | Positive delta, "Aktiv", up-trend line/sparkline |
| `--danger` (red) | `#F75555` | `rgba(247,85,85,0.12)` | Negative delta, "Inaktiv"/error, down-trend |
| `--warning` (amber) | `#F5B544` | `rgba(245,181,68,0.12)` | "Pausiert" (LLM), warnings (introduced — not in image, keeps palette coherent) |
| `--brand-gradient` | `#4F7BFF → #8B5CF6` | — | Logo diamond only |

Status colors **always pair with an icon + text label** — never color alone (a11y).

## Geometry

| Token | Value | Applies to |
|---|---|---|
| `--radius-shell` | `24px` | Outer app shell (floating panel) |
| `--radius-card` | `16px` | Cards, KPI tiles, chart card (`rounded-2xl`) |
| `--radius-control` | `12px` | Buttons, search box, range toggles (`rounded-xl`) |
| `--radius-pill` | `8px` | Delta/status pills |
| `--radius-icon` | `10px` | Icon squares in cards/nav |

## Spacing

4/8px rhythm.

| Context | Value |
|---|---|
| Card padding | `20–24px` |
| Grid gap (KPI row, chart grid) | `16px` |
| Section vertical gap | `24px` |
| Sidebar width (desktop) | `~240px` |
| Nav item height | `40px` |

## Typography Scale

Font: **Inter**, `tabular-nums` on all numeric data (prevents jitter on live countdowns).

| Role | Size / Weight | Color |
|---|---|---|
| Page title ("Welcome back…") | `24px / 600` | primary |
| Card value (KPI / price) | `28–30px / 700` | primary |
| Card label | `12px / 500` | secondary |
| Body / table cell | `14px / 400` | primary/secondary |
| Section nav label | `11px / 600`, uppercase, `tracking-wide` | tertiary |
| Chart axis | `11px / 400` | tertiary |

## Component Specs

**Sidebar** — `--bg-sidebar`, fixed `~240px`, full height. Logo + name top. Grouped nav
under uppercase section labels (`GENERAL`, `SYSTEM`). Nav item: icon (lucide, 18px) + label,
`40px` height, `--radius-control`. Active item: `--surface-active` pill + primary-weight text.
Bottom: profile card (avatar + name + email) on `--surface`.

**Top bar** — breadcrumb (tertiary) over page title. Right cluster: search box (`--surface-2`,
`⌘K` hint chip) + circular icon buttons (notifications, info) on `--surface`.

**KPI card** — `--surface`, `--radius-card`, padding `20px`. Top: icon square (`--radius-icon`)
+ label. Big value (`tabular-nums`). Delta pill: `--radius-pill`, success/danger bg + text,
with up/down chevron icon.

**Chart card** — title + entity icon + big value + delta. Range toggle row (1D 7D 1M 3M 1Y All);
active = `--surface-active` pill. Recharts area chart: line stroke `--success` 2px, gradient fill
`rgba(63,217,132,0.25) → transparent`, grid `#1C1C1C` subtle, axis text tertiary, tooltip bubble
on `--surface-2` `--radius-pill`. Empty + loading (skeleton) states required.

**Data table** (LLM cascade, user approval) — sortable headers (caret, `aria-sort`),
row divider `--border-subtle`, hover `--surface-2`. Entity cell: icon + name/sub. Status badge:
icon + text on tinted pill. Trend cell: Recharts sparkline (green/red, no axes). `tabular-nums`
on numeric columns.

**Primary button** — `--primary` bg, white text, `--radius-control`, full-width in forms.

## Panel Mapping (PWA admin → console)

The current PWA admin area moves **out** of the PWA into this console:

| Reference element | Console panel | Backed by |
|---|---|---|
| 4 KPI cards | Metrics tiles (Nutzer, Annoncen, Favoriten, Saved Searches, …) | `/api/metrics/summary` |
| Main area chart + range toggle | Metrics timeseries (listings/users/logins/notifications), 7/30/90 | `/api/metrics/timeseries` |
| Recent-transactions table + sparklines | **LLM-Kaskade** status table | `/api/llm/*` |
| (list/management view) | **Nutzer-Verwaltung** (approval) | user-approval endpoints |
| Sidebar nav | Overview · Metriken · LLM-Kaskade · Nutzer · (Logout) | — |
