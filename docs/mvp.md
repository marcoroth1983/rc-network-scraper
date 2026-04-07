# RC-Markt Scout — MVP Roadmap

## MVP Goal

A working web app where a user can browse RC airplane listings from rc-network.de, see each listing's location, and filter by distance to their own PLZ.

## Phases

### Phase 1: Scraper Core
Build the Python scraper that can extract listings from rc-network.de.

- Set up Python project structure (FastAPI, Docker Compose with PostgreSQL from day one)
- Implement overview page crawler: iterate `/forums/biete-flugmodelle.132/page-X`, collect thread URLs and external IDs
- Implement detail page parser: extract title, price, condition, shipping, description, images, author, date, `Artikelstandort` (PLZ + city)
- Rate limiting: configurable delay (default 1.0s)
- Store results in PostgreSQL (via Docker)
- Seed `plz_geodata` table from CSV, enrich listings with lat/lon at scrape time
- Incremental scraping: skip fresh listings, re-scrape stale ones, upsert on conflict
- Tests with saved HTML fixtures (no live requests)

**Deliverable:** Dockerized backend that scrapes listings into PostgreSQL with geodata enrichment.

---

### Phase 2: Geodata & Distance API
Add PLZ-to-coordinate resolution and distance calculation.

- Integrate offline German PLZ database (CSV)
- PLZ lookup: resolve PLZ to lat/lon
- Haversine distance calculation
- Enrich existing listings with coordinates on import
- API endpoints:
  - `GET /api/listings` — with query params: `plz`, `max_distance`, `sort`, `search`, `page`
  - `GET /api/listings/{id}` — single listing detail
  - `GET /api/geo/plz/{plz}` — resolve PLZ to coordinates
  - `POST /api/scrape` — trigger scrape run

**Deliverable:** Running FastAPI backend serving enriched listings with distance filtering.

---

### Phase 3: Frontend
React UI for browsing and filtering listings.

- Project setup: Vite + React + TypeScript + Tailwind
- PLZ input with localStorage persistence
- Listing card grid (thumbnail, title, price, city, distance, date)
- Listing detail view (all images, full description, link to original)
- Filter panel: max distance slider, sort dropdown, text search
- Responsive layout (mobile-first)
- Connect to backend API

**Deliverable:** Functional web app running locally — full scrape-to-display pipeline.

---

### Phase 4: Polish & Deployment
Prepare for private VPS hosting.

- Add frontend (nginx) to existing Docker Compose stack
- Background scrape scheduler (periodic re-scrape)
- Basic error handling and loading states in frontend
- Environment-based configuration
- Private access only — firewall/VPN restricted to owner

**Deliverable:** Deployable Docker Compose stack for private VPS.

---

### Phase 5: Alerts (Future)
Optional notifications for new listings matching saved criteria.

- Saved search definitions (PLZ + radius + keywords)
- Background job compares new scrape results against saved searches
- Notification channel (email or push — TBD)

**Deliverable:** Automated alerts for matching new listings. Low priority — only after Phase 4 is stable.
