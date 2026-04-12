# PLAN 011 — VPS Deployment: rcn-scout.d2x-labs.de

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-12 |
| Human | approved | 2026-04-12 |

## Context & Goal

Deploy RC-Network Scout to the existing staging VPS (`152.53.238.3`) as `rcn-scout.d2x-labs.de`.

- **CI/CD**: GitHub Actions builds Docker images on every push to `main`, pushes to `ghcr.io`, deploys via SSH
- **Infrastructure**: Plugs into the existing Traefik v3 reverse proxy with automatic Let's Encrypt SSL
- **Initial data**: Local DB state is dumped and restored once as the starting dataset
- **Repo**: `https://github.com/marcoroth1983/rc-network-scraper`

## Breaking Changes

**No** — this is a greenfield deployment. No existing production environment exists.

---

## Architecture Overview

```
Internet
    │  HTTPS rcn-scout.d2x-labs.de
    ▼
┌───────────────────────────────────────────┐
│  Traefik (already running in /opt/infra)  │
│  network: web                             │
└──────────────────┬────────────────────────┘
                   │ web network
                   ▼
┌──────────────────────────────────────────────────┐
│  /opt/rcn-scout/  (Docker Compose stack)         │
│                                                  │
│  ┌──────────────────────────────────────┐         │
│  │  nginx  (port 80)                   │         │
│  │  ghcr.io/.../rc-network-scraper/nginx│         │
│  │  networks: web + default             │         │
│  │                                      │         │
│  │  /          → serve static frontend  │         │
│  │  /api/*     → proxy to backend:8000  │         │
│  └──────────────────────┬───────────────┘         │
│                         │ default network          │
│  ┌──────────────────────▼───────────────┐         │
│  │  backend  (port 8000)                │         │
│  │  ghcr.io/.../rc-network-scraper/backend│         │
│  │  network: default only               │         │
│  └──────────────────────┬───────────────┘         │
│                         │ default network          │
│  ┌──────────────────────▼───────────────┐         │
│  │  db  (PostgreSQL 16)                 │         │
│  │  network: default only               │         │
│  │  volume: pgdata (persistent)         │         │
│  └──────────────────────────────────────┘         │
└──────────────────────────────────────────────────┘
```

**Key points:**
- `nginx` is the only container on the `web` network → only entry point visible to Traefik
- `backend` and `db` are internal — no external ports exposed
- Frontend static files are baked into the nginx image at build time
- Backend image contains only the Python app (no source mounts)

---

## Files to Create

| File | Purpose |
|------|---------|
| `backend/Dockerfile.prod` | Production backend image (no --reload, COPY source) |
| `frontend/Dockerfile` | Multi-stage: Node build → nginx:alpine serve |
| `frontend/nginx.conf` | Nginx config: serve SPA + proxy `/api` to backend |
| `docker-compose.prod.yml` | Production stack (no dev mounts, Traefik labels) |
| `.github/workflows/deploy.yml` | CI/CD: build → push ghcr.io → SSH deploy |
| `.env.prod.example` | Production env vars template |

---

## Steps

### Step 1 — `backend/Dockerfile.prod`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Key difference from dev `Dockerfile`: adds `COPY . .` and removes `--reload`.

---

### Step 2 — `frontend/nginx.conf`

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # Health check endpoint (not under /api prefix in FastAPI)
    location /health {
        proxy_pass         http://backend:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Proxy /api/* to backend container
    location /api/ {
        proxy_pass         http://backend:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # SPA fallback — all unknown paths serve index.html
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

### Step 3 — `frontend/Dockerfile`

```dockerfile
# Stage 1: Build React app
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

---

### Step 4 — `docker-compose.prod.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: rcscout
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - default

  backend:
    image: ghcr.io/marcoroth1983/rc-network-scraper/backend:${IMAGE_TAG:-latest}
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/rcscout
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
      JWT_SECRET: ${JWT_SECRET}
      PUBLIC_BASE_URL: https://rcn-scout.d2x-labs.de
      FRONTEND_URL: https://rcn-scout.d2x-labs.de
      ALLOWED_ORIGINS: https://rcn-scout.d2x-labs.de
      COOKIE_SECURE: "true"
      SCRAPE_DELAY: "1.0"
    networks:
      - default

  nginx:
    image: ghcr.io/marcoroth1983/rc-network-scraper/nginx:${IMAGE_TAG:-latest}
    restart: unless-stopped
    depends_on:
      - backend
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.rcn-scout.rule=Host(`rcn-scout.d2x-labs.de`)"
      - "traefik.http.routers.rcn-scout.entrypoints=websecure"
      - "traefik.http.routers.rcn-scout.tls.certresolver=letsencrypt"
      - "traefik.http.services.rcn-scout.loadbalancer.server.port=80"
      - "traefik.docker.network=web"
    networks:
      - default
      - web

volumes:
  pgdata:

networks:
  default:
  web:
    external: true
```

---

### Step 5 — `.github/workflows/deploy.yml`

Trigger: every push to `main`.

```yaml
name: Build & Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Generate short SHA tag
        id: tag
        run: echo "sha=${GITHUB_SHA::7}" >> $GITHUB_OUTPUT

      - name: Build & push backend image
        uses: docker/build-push-action@v6
        with:
          context: ./backend
          file: ./backend/Dockerfile.prod
          push: true
          tags: |
            ghcr.io/marcoroth1983/rc-network-scraper/backend:latest
            ghcr.io/marcoroth1983/rc-network-scraper/backend:${{ steps.tag.outputs.sha }}

      - name: Build & push nginx/frontend image
        uses: docker/build-push-action@v6
        with:
          context: ./frontend
          file: ./frontend/Dockerfile
          push: true
          tags: |
            ghcr.io/marcoroth1983/rc-network-scraper/nginx:latest
            ghcr.io/marcoroth1983/rc-network-scraper/nginx:${{ steps.tag.outputs.sha }}

      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST_STAGING }}
          username: ${{ secrets.VPS_USER_STAGING }}
          key: ${{ secrets.VPS_SSH_KEY_STAGING }}
          script: |
            cd /opt/rcn-scout
            docker compose -f docker-compose.prod.yml pull nginx backend
            docker compose -f docker-compose.prod.yml up -d
            docker image prune -f
```

---

### Step 6 — `.env.prod.example`

Template for `/opt/rcn-scout/.env` on the VPS:

```bash
# Database credentials (choose strong values for production)
# IMPORTANT: DB_PASSWORD must be URL-safe (no @, :, /, % chars) — it is
# interpolated directly into DATABASE_URL as postgresql+asyncpg://user:pass@host
DB_USER=rcscout
DB_PASSWORD=change-me-strong-password

# Google OAuth2 — add https://rcn-scout.d2x-labs.de/api/auth/google/callback
# as Authorized Redirect URI in Google Cloud Console
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret

# JWT — generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=change-me-64-char-hex

# Image tag (optional — leave empty to always use :latest)
IMAGE_TAG=
```

---

---

> **BREAK** — Steps 1–6 create files in the repository (automatable). Steps 7–10 are manual one-time operations on external systems (VPS, GitHub, Google Cloud). Commit and push repo changes first, then proceed.

---

### Step 7 — One-time VPS setup (manual)

Run these once before the first deploy:

```bash
# 1. Create project directory
sudo mkdir -p /opt/rcn-scout
sudo chown deploy:deploy /opt/rcn-scout

# 2. Upload docker-compose.prod.yml from local
scp -i ~/.ssh/id_netcup docker-compose.prod.yml deploy@152.53.238.3:/opt/rcn-scout/

# 3. Create .env on VPS with production values
#    (use .env.prod.example as template)
nano /opt/rcn-scout/.env   # on VPS

# 4. Authenticate Docker to pull from ghcr.io
#    Create a PAT on GitHub: Settings → Developer Settings → PATs
#    Scopes required: read:packages
echo "<PAT>" | docker login ghcr.io -u marcoroth1983 --password-stdin
```

**Note:** `GITHUB_TOKEN` in the workflow is enough to push images. The VPS only needs a PAT with `read:packages` to pull. Alternatively, set the ghcr.io packages to **public** via GitHub → Packages → Change visibility → Public — then no VPS auth is needed at all.

---

### Step 8 — Initial DB dump & restore (one-time)

Run on local dev machine, then restore on VPS after the stack is first started:

```bash
# --- LOCAL ---
# 1. Dump the local DB (port 5433 as per docker-compose.yml)
docker compose exec db pg_dump \
  --no-owner --no-acl \
  -U rcscout rcscout \
  > rcscout_dump.sql

# 2. Transfer to VPS
scp -i ~/.ssh/id_netcup rcscout_dump.sql deploy@152.53.238.3:/opt/rcn-scout/

# --- VPS ---
# 3. Start only the DB container first
#    IMPORTANT: do NOT run `docker compose up -d` (all services) before the
#    restore is complete. If the backend starts first, init_db() will create
#    empty tables. The pg_dump uses plain SQL with CREATE TABLE — restoring
#    into an already-initialized schema will produce conflicts.
cd /opt/rcn-scout
docker compose -f docker-compose.prod.yml up -d db

# 4. Wait for DB to be healthy, then restore
#    Source .env explicitly so $DB_USER is available in the shell
source /opt/rcn-scout/.env
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U "$DB_USER" -d rcscout < rcscout_dump.sql

# 5. Remove dump file
rm /opt/rcn-scout/rcscout_dump.sql

# 6. Start remaining services (first deploy runs; CI/CD takes over from here)
docker compose -f docker-compose.prod.yml up -d
```

---

### Step 9 — GitHub Secrets setup (one-time)

In `https://github.com/marcoroth1983/rc-network-scraper/settings/secrets/actions`:

| Secret | Value |
|--------|-------|
| `VPS_HOST_STAGING` | `152.53.238.3` |
| `VPS_USER_STAGING` | `deploy` |
| `VPS_SSH_KEY_STAGING` | contents of `~/.ssh/id_netcup` |

`GITHUB_TOKEN` is automatic — no setup needed.

---

### Step 10 — Google OAuth redirect URI

In [Google Cloud Console](https://console.cloud.google.com) → Credentials → OAuth 2.0 Client ID:

Add to **Authorized redirect URIs**:
```
https://rcn-scout.d2x-labs.de/api/auth/google/callback
```

The backend constructs this URI as `{PUBLIC_BASE_URL}/api/auth/google/callback` (see `backend/app/api/auth.py`). The exact string must match what Google sends back.

---

## Verification

After the first successful deploy:

```bash
# 1. Check service health (no auth required)
curl -s https://rcn-scout.d2x-labs.de/health
# Expected: {"status":"ok"}

# 2. Check containers are running on VPS
ssh -i ~/.ssh/id_netcup deploy@152.53.238.3 \
  "cd /opt/rcn-scout && docker compose -f docker-compose.prod.yml ps"
# Expected: all 3 services (db, backend, nginx) in state "running"
```

Note: `/api/listings` requires authentication — test it via browser after SSO login.

```
# 3. Browser tests (manual)
# https://rcn-scout.d2x-labs.de           → Login page with search icon + "RC-Network Scout"
# → "Mit Google anmelden"                 → Google OAuth flow completes
# → Redirected back, listings page loads  → cards with data visible
# → Enter PLZ + km radius                 → distance filter works
```

---

## Assumptions & Risks

| Risk | Mitigation |
|------|-----------|
| `docker/build-push-action@v6` not yet released | Use `@v5` if v6 is unavailable at implementation time |
| `DB_USER` mismatch between dump owner and prod user | `--no-owner --no-acl` flags in pg_dump cover this |
| Frontend env vars baked into image | All API calls go to `/api/` (relative), no env vars needed at build time — safe |
| `COOKIE_SECURE=true` requires HTTPS | Traefik enforces HTTPS redirect — always satisfied in prod |
| ghcr.io package visibility | Either set to public or add VPS PAT auth (Step 7 covers both options) |
