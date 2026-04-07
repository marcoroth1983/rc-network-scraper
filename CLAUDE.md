# RC-Markt Scout

Personal hobby project — scrapes RC airplane listings from rc-network.de, enriches with geodata, displays in a Kleinanzeigen-style UI with distance filtering.

## Key Facts

- **Single user** — no auth, no multi-tenancy, no public access
- **VPS deployment is private** — firewall/VPN restricted to the owner only
- **Keep it simple** — no enterprise patterns, no over-engineering
- Docs are the source of truth: `docs/definition.md`, `docs/architektur.md`

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy (async)
- Database: PostgreSQL 16 (Docker, dev and prod)
- Scraping: httpx + BeautifulSoup4
- Geodata: `plz_geodata` DB table (seeded from CSV, not loaded in-memory)
- Frontend: React 18+, TypeScript, Vite, Tailwind CSS

## Development

```bash
docker compose up --build -d      # Start PostgreSQL + backend
docker compose exec backend pytest tests/ -v  # Run tests
```

## Guidelines

- No auth/permission layers — single user behind network restriction
- Prefer simple solutions over configurable/extensible ones
- Rate-limit scraping (min 500ms between requests)
- Tests use saved HTML fixtures, no live requests
