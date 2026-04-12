# Security & Infrastructure Audit — 2026-04-13

**Scope:** VPS deployment of RC-Markt Scout at `rcn-scout.d2x-labs.de`
**Perspective:** Security engineer + DevOps engineer
**Method:** Static analysis of all configuration files, Docker setup, auth code, CI/CD pipeline, and network architecture. No live penetration testing performed.
**Status:** Audit only — no changes made.

---

## Executive Summary

The deployment is **solid for a single-user hobby project**. Authentication, network isolation, and SSL are correctly configured. There are no critical vulnerabilities that would allow unauthorized access. However, several hardening opportunities exist that range from low-effort improvements to nice-to-haves.

**Severity ratings:** CRITICAL (immediate action needed) | HIGH (should fix soon) | MEDIUM (recommended) | LOW (nice-to-have) | INFO (observation, no action needed)

---

## 1. Authentication & Authorization

### 1.1 Google OAuth Flow — GOOD

| Aspect | Status | Detail |
|--------|--------|--------|
| CSRF protection | OK | `state` parameter stored in httponly cookie, validated with `secrets.compare_digest()` |
| Token exchange | OK | Server-side code exchange (not implicit flow) |
| Session cookie | OK | `httponly=True`, `secure=True` (prod), `samesite=lax` |
| JWT expiration | OK | 30-day TTL, validated on every request via `decode_jwt()` |
| User approval gate | OK | `is_approved` flag checked on every authenticated request — unapproved users get 401 |
| Scope | OK | `openid email profile` — minimal, no unnecessary permissions |

### 1.2 Route Protection — GOOD

All business endpoints (`/api/listings`, `/api/scrape`, `/api/searches`, `/api/favorites`, `/api/geo`) require `get_current_user` dependency which:
1. Reads `session` cookie
2. Decodes and validates JWT (signature + expiration)
3. Fetches user from DB
4. Checks `is_approved == True`

**No unprotected business routes found.**

### 1.3 Frontend Auth Guard — GOOD

`App.tsx` checks `useAuth()` → if no user, redirects to `/login`. This is a UX guard only (the real enforcement is backend-side, which is correct).

### 1.4 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| AUTH-1 | MEDIUM | No JWT revocation mechanism | If a session cookie is stolen, it remains valid for up to 30 days. There's no server-side session store to invalidate individual tokens. For single-user this is acceptable, but rotating `JWT_SECRET` is the only way to force logout of all sessions. |
| AUTH-2 | LOW | No `prompt=consent` on re-auth | Google may skip consent screen for returning users. Not a security issue per se, but `prompt=consent` would ensure users explicitly re-consent each login. |
| AUTH-3 | INFO | `is_approved` default is `false` | New signups via Google OAuth are blocked until manually approved in DB. This is correct — prevents random Google users from accessing the app. |

---

## 2. Network Architecture & Isolation

### 2.1 Docker Network Topology — GOOD

```
Internet → Traefik (web network) → nginx (web + default) → backend (default) → db (default)
```

| Service | External Network (`web`) | Internal Network (`default`) | Exposed Ports |
|---------|-------------------------|------------------------------|---------------|
| nginx   | Yes                     | Yes                          | 80 (to Traefik only) |
| backend | No                      | Yes                          | None          |
| db      | No                      | Yes                          | None          |

**Backend and DB are not reachable from outside the Docker network.** Only nginx is on the `web` network, and only Traefik can reach it. This is correct.

### 2.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| NET-1 | MEDIUM | No HTTP → HTTPS redirect defined in Traefik labels | The `docker-compose.prod.yml` only defines the `websecure` entrypoint. If Traefik's global config doesn't enforce HTTP→HTTPS redirect, port 80 may either be open with no redirect or return a Traefik 404. **Verify:** Does Traefik's static config have a global HTTP→HTTPS redirect? If not, add a `web` (port 80) router with redirect middleware. |
| NET-2 | LOW | `/health` endpoint is unauthenticated | Returns `{"status":"ok"}`. Minimal info leak — reveals the app is running. Acceptable for monitoring/Traefik health checks, but could be restricted to internal network if desired. |
| NET-3 | INFO | No VPS firewall scripts in repo | Firewall config (ufw/iptables) is presumably managed outside this repo. **Verify on VPS:** `ufw status` or `iptables -L`. Recommended: only ports 22, 80, 443 open. |

---

## 3. Database Security

### 3.1 Configuration — GOOD

| Aspect | Status | Detail |
|--------|--------|--------|
| Credentials | OK | DB_USER and DB_PASSWORD injected via `.env` on VPS, not hardcoded in `docker-compose.prod.yml` |
| Network exposure | OK | DB container is on `default` network only — not reachable from internet or `web` network |
| No published ports | OK | Production compose does not map any host ports for DB (unlike dev which maps 5433:5432) |
| Volume persistence | OK | Named volume `pgdata` survives container restarts |

### 3.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| DB-1 | HIGH | No database backups configured | There is no backup strategy visible. A disk failure or accidental `docker volume rm` would permanently lose all data. **Recommendation:** Set up a cron job for `pg_dump` to a separate location (e.g., daily dump to `/opt/backups/` + rotation). |
| DB-2 | MEDIUM | DB password strength unknown | The `.env` on VPS was created manually. **Verify on VPS:** Is the password a strong random value (not `change-me` from the example)? |
| DB-3 | LOW | No connection pooling limits | SQLAlchemy defaults are used. Fine for single-user, but no explicit `pool_size` / `max_overflow` configured. |
| DB-4 | LOW | SQL injection via `text()` in auth upsert | `auth.py:91-98` uses `text()` with named parameters (`:google_id`, `:email`, `:name`). Named parameters are safe — SQLAlchemy properly parameterizes them. **Not a vulnerability**, but worth noting the pattern. |

---

## 4. Secrets Management

### 4.1 Git Repository — GOOD

| Aspect | Status | Detail |
|--------|--------|--------|
| `.env` in `.gitignore` | OK | `.env` and `.env.*` are excluded (except `.env.example`) |
| `.env` tracked in git | OK | `git ls-files` confirms `.env` is NOT tracked |
| `.env.example` | OK | Contains only placeholder values (`your-client-id`, `change-me`) |
| Production secrets | OK | Stored in VPS `.env` file and GitHub Actions secrets — not in repo |

### 4.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| SEC-1 | MEDIUM | VPS IP address visible in plan doc + GitHub secrets name | `152.53.238.3` is documented in `docs/PLAN_011_vps_deployment.md`. Not a vulnerability by itself (it's just an IP), but worth knowing it's in a potentially public repo. If the repo is public, this exposes the server IP. |
| SEC-2 | MEDIUM | JWT_SECRET rotation procedure not documented | If the secret is compromised, all sessions must be invalidated. The procedure (change env var, restart backend) should be documented. |
| SEC-3 | LOW | No secret scanning in CI | No automated check for accidentally committed secrets (e.g., GitHub secret scanning, truffleHog, or gitleaks). |
| SEC-4 | INFO | `GOOGLE_CLIENT_ID` is not a secret | The client ID is sent to the browser as part of the OAuth redirect URL. Only `GOOGLE_CLIENT_SECRET` needs protection. Both are treated as env vars, which is fine. |

---

## 5. SSL/TLS

### 5.1 Configuration — GOOD

| Aspect | Status | Detail |
|--------|--------|--------|
| TLS termination | OK | Handled by Traefik with Let's Encrypt (`certresolver=letsencrypt`) |
| Certificate renewal | OK | Automatic via Traefik |
| `COOKIE_SECURE=true` | OK | Set in `docker-compose.prod.yml` — cookies only sent over HTTPS |

### 5.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| TLS-1 | MEDIUM | No HSTS headers configured | Neither Traefik labels nor nginx config set `Strict-Transport-Security`. Browsers will not enforce HTTPS-only after first visit. **Recommendation:** Add HSTS via Traefik middleware or nginx `add_header`. |
| TLS-2 | LOW | TLS version/cipher control unknown | Depends on Traefik's default TLS configuration. Modern Traefik defaults are good (TLS 1.2+), but **verify** TLS config is not downgraded. |

---

## 6. CI/CD Pipeline

### 6.1 Configuration — GOOD

| Aspect | Status | Detail |
|--------|--------|--------|
| Image registry auth | OK | `GITHUB_TOKEN` (automatic) for push to ghcr.io |
| VPS deploy auth | OK | SSH key stored in GitHub Actions secrets |
| Image tagging | OK | Both `latest` and short SHA tag — allows rollback |
| Minimal permissions | OK | `contents: read`, `packages: write` — least privilege |
| Build/deploy separation | OK | Deploy job depends on build job completing |

### 6.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| CI-1 | MEDIUM | No deployment health check after `docker compose up -d` | The deploy script pulls and starts containers but doesn't verify they actually came up healthy. A failed backend start would go unnoticed until someone visits the site. **Recommendation:** Add `curl --fail https://rcn-scout.d2x-labs.de/health` after deploy, or at minimum `docker compose ps` to verify. |
| CI-2 | MEDIUM | Every push to `main` triggers deploy | No manual approval gate. An accidental merge or force-push deploys immediately. Acceptable for solo hobby project, but consider `workflow_dispatch` for manual control if desired. |
| CI-3 | LOW | SSH key `VPS_SSH_KEY_STAGING` has unknown scope | **Verify on VPS:** Does the `deploy` user have sudo access? Ideally it should NOT. The deploy user should only be able to run docker commands (member of `docker` group) and access `/opt/rcn-scout/`. |
| CI-4 | LOW | No image vulnerability scanning | Container images are built from `python:3.12-slim` and `nginx:alpine` but not scanned for CVEs. **Recommendation:** Add `trivy` or `docker scout` scan step in CI. |
| CI-5 | INFO | `docker image prune -f` runs after every deploy | Good — prevents disk space issues from accumulated old images. |

---

## 7. Application Security

### 7.1 CORS — ACCEPTABLE

```python
allow_origins=["https://rcn-scout.d2x-labs.de"]
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
```

Origin is correctly locked to the production domain. `allow_methods=["*"]` and `allow_headers=["*"]` are more permissive than necessary but not exploitable when the origin list is strict.

### 7.2 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| APP-1 | LOW | No rate limiting on auth endpoints | `/api/auth/google` can be called repeatedly. Not exploitable (it redirects to Google), but `/api/scrape` could be spammed to trigger many scrape jobs. The existing 409 (already running) guard helps, but no general rate limit exists. |
| APP-2 | LOW | No security headers (CSP, X-Frame-Options, etc.) | nginx serves frontend without security headers. **Recommendation:** Add `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` in nginx config. |
| APP-3 | LOW | No request body size limit in nginx | Large POST bodies could consume memory. nginx default is 1MB (`client_max_body_size`), which is adequate. FastAPI/uvicorn also has limits. |
| APP-4 | INFO | Scrape delay configurable via env | `SCRAPE_DELAY=1.0` in production. Respectful toward rc-network.de. |

---

## 8. Nginx Configuration

### 8.1 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| NGX-1 | LOW | No `server_tokens off` | nginx version is visible in error pages and `Server` header. Minor info leak. |
| NGX-2 | INFO | Proxy timeout 60s | Adequate for scrape operations that may take time. |

---

## 9. Docker Image Security

### 9.1 Findings

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| IMG-1 | LOW | Backend runs as root inside container | `Dockerfile.prod` does not create or switch to a non-root user. Best practice is `RUN useradd -r app && USER app`. Reduces blast radius if the container is compromised. |
| IMG-2 | INFO | Base images are slim/alpine | Good — minimal attack surface. |
| IMG-3 | INFO | No `.dockerignore` for backend | All files including tests and `.env.example` are copied into the production image. Not a security issue but adds unnecessary weight. |

---

## Summary Table

| Severity | Count | IDs |
|----------|-------|-----|
| CRITICAL | 0 | — |
| HIGH | 1 | DB-1 |
| MEDIUM | 7 | AUTH-1, ~~NET-1~~, ~~DB-2~~, SEC-1, SEC-2, TLS-1, CI-1, CI-2, VPS-1 |
| LOW | 10 | AUTH-2, NET-2, DB-3, SEC-3, APP-1, APP-2, APP-3, NGX-1, IMG-1, CI-3, CI-4 |
| INFO | 7 | AUTH-3, NET-3, DB-4, SEC-4, TLS-2, APP-4, NGX-2, IMG-2, IMG-3, CI-5 |

---

## Recommended Priority Actions

### Must Do (before forgetting about it)

1. **DB-1: Set up database backups.** A simple cron job (`pg_dump` daily to `/opt/backups/` with 7-day rotation) protects against data loss. This is the single most impactful improvement.

### Should Do (low effort, high value)

2. **CI-1: Add health check after deploy.** One `curl --fail` line in the deploy script catches broken deployments.
3. **TLS-1: Add HSTS header.** One line in nginx or one Traefik middleware label.
4. **NET-1: Verify HTTP→HTTPS redirect.** Check Traefik's static config or add a redirect middleware.
5. **SEC-2: Document secret rotation procedure.** A few lines in docs covering JWT_SECRET and Google OAuth credential rotation.

### Nice to Have

6. **IMG-1: Run backend as non-root user.** Two lines in Dockerfile.
7. **APP-2: Add security headers in nginx.** A few `add_header` directives.
8. **NGX-1: Disable server tokens.** One line: `server_tokens off;`.
9. **CI-4: Add container image scanning.** One CI step with trivy.

---

## VPS Verification (performed via SSH on 2026-04-13)

| Check | Result | Detail |
|-------|--------|--------|
| Firewall (ufw) | OK | `default: deny (incoming), allow (outgoing)`. Only ports 22, 80, 443 open (IPv4+IPv6). |
| DB password | OK | 32-char random alphanumeric string. Strong. |
| JWT_SECRET | OK | 64-char hex string generated with `secrets.token_hex(32)`. |
| `deploy` user sudo | **RISK** | `deploy` has passwordless sudo. Should be restricted to docker commands only, or sudo removed entirely (docker group membership suffices for container ops). |
| HTTP→HTTPS redirect | OK | Traefik static config: `entrypoints.web.http.redirections.entryPoint.to=websecure`. All HTTP traffic is redirected. |
| Traefik TLS | OK | Traefik v3 defaults to TLS 1.2+ with modern cipher suites. `entrypoints.websecure.http.tls=true` enforces TLS on all HTTPS hosts. Unknown hosts get empty 503 (catch-all router). |
| SSH config | OK | `PasswordAuthentication no`, `PermitRootLogin no`. Key-only access. |
| Docker socket | OK | Mounted as `/var/run/docker.sock:ro` (read-only) in Traefik. No TCP exposure. |

### New finding from VPS check

| ID | Severity | Finding | Detail |
|----|----------|---------|--------|
| VPS-1 | MEDIUM | `deploy` user has unrestricted sudo | The deploy user (used by CI/CD SSH) can run any command as root. If the SSH key or GitHub secret is compromised, the attacker has full root access. **Recommendation:** Remove sudo access and rely on docker group membership, or restrict sudo to specific commands via `/etc/sudoers.d/deploy`. |

---

## Remediation Log

| ID | Status | Date | Detail |
|----|--------|------|--------|
| NET-1 | Resolved (already configured) | 2026-04-13 | Traefik global HTTP→HTTPS redirect was already in place. |
| DB-2 | Resolved (verified) | 2026-04-13 | Strong 32-char random password confirmed on VPS. |
| CI-1 | Fixed | 2026-04-13 | Added `curl --fail --retry 3` health check after deploy in `.github/workflows/deploy.yml`. |
| TLS-1 | Fixed | 2026-04-13 | Added HSTS header (`max-age=3600`) in `frontend/nginx.conf`. Increase to `max-age=31536000` after confirming no issues. |
| SEC-2 | Fixed | 2026-04-13 | Secret rotation procedure documented in `docs/SECRET_ROTATION.md`. |

---

*Initial audit performed by static analysis at commit `a1e06b0`. VPS verification and remediations performed on 2026-04-13.*
