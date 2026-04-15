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

## VPS Access (Staging)

```bash
# SSH
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3

# Logs
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker compose -f /opt/rcn-scout/docker-compose.prod.yml logs --tail=150 backend"

# Container status
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 "docker ps"
```

Full infrastructure reference (all servers, SSH keys, domains): `D:\DEVELOPMENT\_workplace_AI\INFRASTRUCTURE.md`

> If SSH times out: fail2ban may have banned the current IP. Unban via Netcup SCP Console
> (https://www.servercontrolpanel.de) or run `sudo fail2ban-client set sshd unbanip <ip>` on the VPS.

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
- Frontend tests import all Vitest globals explicitly: `import { describe, it, expect, vi } from 'vitest'` (globals are NOT enabled in vitest config)
