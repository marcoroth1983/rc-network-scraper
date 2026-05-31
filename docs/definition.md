# RC-Markt Scout — Product Definition

> **Personal hobby project** — built for a single user, not a public service.
> No enterprise concerns (multi-tenancy, auth, SLAs). Keep it simple.

## Vision

A web application that scrapes RC model listings from rc-network.de, enriches them with geolocation data, and presents them in a clean, Kleinanzeigen-style interface with distance-based filtering and category selection.

## Problem

Browsing rc-network.de "Biete" forums is tedious: listings don't show location in the overview, forcing users to open each one individually and manually look up distances via Google Maps.

## Target User

The project owner — a single RC model enthusiast looking for used RC equipment within a reasonable travel distance.

## Core Features

### F1: Listing Scraper
- Scrape listing overview pages from all 7 "Biete" categories on rc-network.de (sequentially, 2s delay between requests)
- Supported categories: Flugmodelle, Schiffsmodelle, Antriebstechnik, RC-Elektronik & Zubehör, RC-Cars & Funktionsmodelle, Einzelteile & Sonstiges, Zu verschenken
- For each listing, fetch the detail page and extract:
  - Title
  - Price (`Preis:` field)
  - Condition (`Zustand:` field)
  - Shipping (`Versandart/-kosten:` field)
  - Location (`Artikelstandort:` field — format: `PLZ, City`)
  - Description text
  - Images (thumbnail URLs)
  - Link to original listing
  - Author name
  - Post date
- Handle pagination automatically

### F2: Geolocation & Distance
- Map extracted PLZ to coordinates using an offline German PLZ database
- User sets a reference location (PLZ input)
- Calculate distance (Haversine formula) from reference to each listing
- Display distance per listing

### F3: Listing Display
- Card-based layout similar to Kleinanzeigen/eBay
- Each card shows: thumbnail, title, price, condition, city, PLZ, distance, post date
- Click-through to full detail view with all images, full description, and link to original listing

### F4: Search & Filter
- Filter by maximum distance (km radius)
- Filter by category (on first visit: category picker modal; persisted in localStorage)
- Sort by: distance, price, date
- Text search across title and description

### F5: Web Push Alerts (active)

- Per-user opt-in via `/profile` notifications panel.
- Trigger: new listing matches for any **active** SavedSearch (existing pipeline via `notification_registry.dispatch(MatchResult)`).
- Also delivers favorites status changes (sold / price / deleted) via the favorites sweep.
- Multi-device: each browser install registers its own subscription; devices removable individually.
- Sole notification channel — Telegram was removed in PLAN-027.
- iOS: requires PWA install (Add to Home Screen) — see `limitations.md`.

## Scope Boundaries

- **In scope:** All 7 "Biete" category subforums on rc-network.de
- **Out of scope:** Other rc-network.de sections (e.g. "Suche"), other marketplaces, user accounts/auth on our side, buying/messaging through our app
- **Scraping ethics:** Respect robots.txt, rate-limit requests, cache aggressively, include User-Agent identification

## Entities

### Listing
- `id` (internal)
- `external_id` (thread ID from rc-network.de — globally unique across all forums)
- `category` (one of the 7 category keys)
- `url` (original listing URL)
- `title`
- `price` (nullable — not all listings have a price)
- `condition` (nullable)
- `shipping` (nullable)
- `description`
- `images` (list of URLs)
- `author`
- `posted_at`
- `plz`
- `city`
- `latitude`
- `longitude`
- `scraped_at`

### UserLocation (ephemeral, stored client-side)
- `plz`
- `latitude`
- `longitude`
