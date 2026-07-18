# Cockpit Admin Auth — rcn-scraper side Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.
> **REQUIRED SPEC:** this plan implements the rcn-scraper side of `docs/COCKPIT_ADMIN_ADAPTER.md` (the boundary contract) and is **BOUND to its §8 hardening**. Read the contract first.

**Goal:** Let the d2x cockpit call rcn-scraper's `/api/admin/*` server-to-server, authenticated by a **short-lived RS256 JWT assertion verified via the cockpit's JWKS** (no shared secret), while keeping rcn-scraper's existing cookie-admin as an independent **break-glass** path. Add the **last-admin invariant** and cross-app audit. Does NOT retire the standalone admin SPA (that is a later, gated step — contract §8 rollout).

**Architecture:** A new auth dependency `require_cockpit_admin` verifies a cockpit-minted RS256 assertion (JWKS, strict profile, jti-replay for destructive routes), resolves the operator by **immutable `google_id`**, and returns a `CockpitOperator`. The 8 admin routes accept **either** the existing cookie session **or** the cockpit assertion (dual-auth) during the transition. rcn-scraper's `backend` joins a dedicated internal `d2x-internal` docker network (stays off Traefik) so the cockpit reaches it privately.

**Tech Stack:** FastAPI + PyJWT (already a dep; use `jwt.PyJWKClient` for RS256/JWKS), SQLAlchemy async, Docker Compose. No new heavy dependency (PyJWT already present).

**Breaking Changes:** No (additive/dual-auth). The cookie path stays. Recovery = revert; the cookie-admin path is unaffected throughout.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-07-18 |
| Human | approved | 2026-07-18 |

_Plan review closed 2026-07-18 (2 cycles). Bound to the Codex-hardened contract §8. Cycle 1: 4 blocking (jti wiring, FastAPI DI, last-admin TOCTOU, JWKS hardening) + 3 non-blocking — all fixed. Cycle 2: verified the 4 fixes correct; 1 new blocking (sync httpx/threading.Lock in async path) + 2 non-blocking — all fixed (async httpx + asyncio.Lock, target SELECT, step numbering). Orchestrator closed after cycle 2: the cycle-2 blocking was a mechanical async conversion, self-verified. Human pre-approved autonomous execution ("mach das autonom", 2026-07-18)._

---

## Context (verified 2026-07-17 via repo scan)

- **Admin routes** (`backend/app/api/admin.py`): 8 routes, router `prefix="/admin"`, every one `Depends(require_admin)`. Routes 4 `PATCH /admin/users/{id}/approval` and 5 `DELETE /admin/users/{id}` bind the admin as `current_admin` and have self-guards (`if user_id == current_admin.id …` → 400). Full path prefix `/api/admin` (business router `/api` + `/admin`).
- **Auth** (`backend/app/api/deps.py`): `get_current_user` reads cookie `"session"` → `decode_jwt` → `int(sub)` → load `User`, rejects `not is_approved`. `require_admin(user=Depends(get_current_user))` → 403 if `user.role != "admin"`, returns `User`.
- **JWT** (`backend/app/security.py`): PyJWT, `create_jwt`/`decode_jwt`, **HS256**, secret `settings.JWT_SECRET`, algorithm `settings.JWT_ALGORITHM` (config.py:43), `sub`=str(user_id). This is the cookie path — **leave it unchanged** (break-glass).
- **User model** (`backend/app/models.py:82-94`): `id:int` PK, **`google_id:str` unique** (the immutable identity), `email:str` unique, `role:str` (default `"member"`, admin when `== "admin"`), `is_approved:bool`.
- **Config** (`backend/app/config.py`): `Settings` (pydantic); `JWT_SECRET`/`JWT_ALGORITHM`/`JWT_EXPIRE_DAYS` present; env-driven. Add cockpit settings here.
- **Compose** (`docker-compose.prod.yml`): `backend` service = `default` network only, no Traefik labels (private, uvicorn `:8000`). Networks: `default` + `web` (external). `admin` + `nginx` on `web`.
- **Tests:** `backend/pytest.ini` (`asyncio_mode=auto`); run `docker compose exec backend pytest tests/ -v` (CLAUDE.md:43). Test dir `backend/tests/`.
- **Contract §8 binding requirements** (MUST): last-admin invariant; google_id match; strict JWT profile (kid, alg allow-list, iss/aud/exp/nbf, `exp-iat ≤ 5min`, recent iat, skew ≤ 60s); ignore `jku`/`x5u`/inline `jwk`/`x5c`; JWKS fail-closed + HTTPS-only + timeout/size cap + unknown-kid throttle; **jti single-use replay cache on destructive routes** (PATCH approval, DELETE, POST refresh); no startup coupling; keep cookie break-glass.

**Out of scope (contract §8 rollout — later/gated):** retiring the `admin` service + `admin.rcn-scout.d2x-labs.de` + the `admin/` SPA dir; dropping the cookie/HS256 path. Those come only after the cockpit facet is verified live through a key rotation.

---

## Task 1: Cockpit-auth config [DONE]

**Files:** Modify `backend/app/config.py`

**Step 1:** Add settings (mirror the existing pydantic `Settings` fields; all env-driven, with safe defaults that leave the feature OFF until configured):
```python
COCKPIT_AUTH_ENABLED: bool = False           # master switch for the cockpit path
COCKPIT_JWKS_URL: str = ""                    # e.g. https://admin.d2x-labs.de/.well-known/jwks.json
COCKPIT_ISSUER: str = "d2x-cockpit"
COCKPIT_AUDIENCE: str = "rcn-scraper-admin"
COCKPIT_MAX_TOKEN_TTL_SECONDS: int = 300      # enforce exp - iat <= this
COCKPIT_CLOCK_SKEW_SECONDS: int = 60
```
Validate: if `COCKPIT_AUTH_ENABLED` then `COCKPIT_JWKS_URL` must be a non-empty https URL (mirror the existing non-empty validators in config.py).

**Step 2: Commit**
```bash
git add backend/app/config.py
git commit -m "feat(config): cockpit-auth settings (RS256/JWKS, off by default)"
```

---

## Task 2: Cockpit assertion verifier + `require_cockpit_admin` [DONE]

**Depends on:** Task 1

**Files:** Create `backend/app/cockpit_auth.py`; Test `backend/tests/test_cockpit_auth.py`

**Step 1:** Implement the verifier (PyJWT `PyJWKClient`, strict profile per contract §8). A single cached `PyJWKClient` (module-level, HTTPS + timeout); reject token-embedded key headers; enforce `exp-iat` + recent `iat`; fail closed.
```python
from dataclasses import dataclass
import time, jwt
from jwt import PyJWKClient, InvalidTokenError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from app.config import settings
from app.models import User
# ... async db session dep import (mirror deps.py's session dependency)

class JwksUnreachable(Exception):
    """Distinct from InvalidTokenError → maps to 503, never allow (fail-closed)."""

@dataclass
class CockpitOperator:
    google_id: str          # assertion `sub` — the self-guard compares THIS, no matched_user needed
    email: str
    jti: str | None         # set on the cockpit path (for replay); None on the cookie path
    token_exp: float | None # for the jti cache TTL

# --- Hardened JWKS fetcher (contract §8 #6): ASYNC httpx (never block the event loop —
#     cycle-2 fix), 64 KB size cap, per-unknown-kid cooldown, asyncio.Lock ---
import httpx, asyncio
_JWKS: dict = {"keys": [], "fetched": 0.0}
_UNKNOWN_KID_LAST: dict[str, float] = {}
_LOCK = asyncio.Lock()   # asyncio, NOT threading — this path is async
_MAX_JWKS_BYTES = 64 * 1024
_JWKS_TTL = 300          # cache lifespan
_KID_COOLDOWN = 30       # min seconds between refetches triggered by the same unknown kid

async def _fetch_jwks() -> dict:
    url = settings.COCKPIT_JWKS_URL
    if not url.startswith("https://"):
        raise JwksUnreachable("JWKS url must be https")
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:  # no cross-host redirects
            r = await c.get(url)
            r.raise_for_status()
            if len(r.content) > _MAX_JWKS_BYTES:                     # response-size cap
                raise JwksUnreachable("JWKS too large")
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise JwksUnreachable(str(e))

async def _get_key(kid: str):
    now = time.time()
    async with _LOCK:
        fresh = now - _JWKS["fetched"] < _JWKS_TTL
        have = any(k.get("kid") == kid for k in _JWKS["keys"])
        if not have and not fresh:
            _JWKS.update(keys=(await _fetch_jwks()).get("keys", []), fetched=now)
        elif not have and fresh:
            # unknown kid on a fresh cache → allow ONE throttled refetch (anti refetch-storm/kid-spray)
            if now - _UNKNOWN_KID_LAST.get(kid, 0) >= _KID_COOLDOWN:
                _UNKNOWN_KID_LAST[kid] = now
                _JWKS.update(keys=(await _fetch_jwks()).get("keys", []), fetched=now)
        jwk = next((k for k in _JWKS["keys"] if k.get("kid") == kid), None)
    if jwk is None:
        raise InvalidTokenError("unknown kid")
    return jwt.PyJWK(jwk).key

async def _verify(token: str) -> dict:
    # Reject alg confusion + token-embedded keys: only RS256, key ONLY from our pinned JWKS (by kid).
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256" or "kid" not in header:
        raise InvalidTokenError("bad alg/kid")
    if any(k in header for k in ("jku", "x5u", "jwk", "x5c")):
        raise InvalidTokenError("embedded key header rejected")
    key = await _get_key(header["kid"])   # raises JwksUnreachable (→503) or InvalidTokenError (→401)
    claims = jwt.decode(
        token, key, algorithms=["RS256"],
        issuer=settings.COCKPIT_ISSUER, audience=settings.COCKPIT_AUDIENCE,
        leeway=settings.COCKPIT_CLOCK_SKEW_SECONDS,
        options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]},
    )
    now = time.time()
    if claims["exp"] - claims["iat"] > settings.COCKPIT_MAX_TOKEN_TTL_SECONDS:
        raise InvalidTokenError("ttl too long")
    if claims["iat"] > now + settings.COCKPIT_CLOCK_SKEW_SECONDS:
        raise InvalidTokenError("iat in future")
    if now - claims["iat"] > settings.COCKPIT_MAX_TOKEN_TTL_SECONDS + settings.COCKPIT_CLOCK_SKEW_SECONDS:
        raise InvalidTokenError("iat too old")
    if claims.get("role") != "admin":
        raise InvalidTokenError("not admin")
    return claims

# Plain helper (NOT a FastAPI dependency) — session passed explicitly, so it composes without DI misuse.
async def verify_cockpit_bearer(request: "Request", db: "AsyncSession") -> CockpitOperator:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "cockpit assertion required")
    claims = await _verify(auth[7:])   # InvalidTokenError / JwksUnreachable bubble up to the caller to map
    google_id = claims["sub"]
    return CockpitOperator(google_id=google_id, email=claims.get("email", ""),
                           jti=claims["jti"], token_exp=float(claims["exp"]))
```
FastAPI dependency wraps the helper with its OWN injected session + error mapping (resolves review B2 + N1 + N3 — real dep name is `get_session` from `backend/app/db.py:337`):
```python
async def require_cockpit_admin(request: Request,
                                db: AsyncSession = Depends(get_session)) -> CockpitOperator:
    try:
        return await verify_cockpit_bearer(request, db)
    except JwksUnreachable:
        raise HTTPException(503, "cockpit key set unreachable")   # fail-closed, distinct from 401
    except InvalidTokenError:
        raise HTTPException(401, "invalid cockpit assertion")
```

**Step 2:** Add a **single-use jti replay cache** — async-safe in-process TTL dict `{jti: exp}`, pruned lazily; `def consume_jti(jti: str, exp: float) -> bool` returns False if already seen (else records + returns True). In-process is fine for the single backend replica; if rcn-scraper ever runs multiple backend replicas, move to a shared store (Redis) — note in the contract.

**Step 3:** Write tests `test_cockpit_auth.py` — mint tokens with a test RS keypair; monkeypatch `_get_key`/`_fetch_jwks` to return the test public key. One `def test_` per: valid token → CockpitOperator (with google_id + jti); `alg:none` rejected; HS256 rejected; embedded `jku` header rejected; expired rejected; `exp-iat` > max rejected; future `iat` rejected; wrong `iss`/`aud` rejected; **unknown kid → 401**; **JWKS unreachable → `JwksUnreachable` (dep maps to 503)**; **`consume_jti` returns True once then False on replay**; **oversized JWKS response rejected**.

**Step 4: Commit**
```bash
git add backend/app/cockpit_auth.py backend/tests/test_cockpit_auth.py
git commit -m "feat(auth): RS256/JWKS cockpit assertion verifier + require_cockpit_admin (contract §8)"
```

---

## Task 3: Wire dual-auth + last-admin invariant + audit into admin routes [DONE]

**Depends on:** Task 2

**Files:** Modify `backend/app/api/admin.py`; Modify/add `backend/app/api/deps.py` (a combined dependency); Test `backend/tests/test_admin_lastadmin.py`

**Step 1: Combined admin dependency (composes via DI — resolves review B2).** `require_any_admin` is itself a FastAPI dependency with its OWN injected session; it calls PLAIN helpers (never calls another `Depends`-function directly):
```python
async def require_any_admin(request: Request,
                            db: AsyncSession = Depends(get_session)) -> CockpitOperator:
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
    if settings.COCKPIT_AUTH_ENABLED and has_bearer:
        try:
            return await verify_cockpit_bearer(request, db)   # plain helper from Task 2
        except JwksUnreachable:
            raise HTTPException(503, "cockpit key set unreachable")
        except InvalidTokenError:
            raise HTTPException(401, "invalid cockpit assertion")
    # Cookie break-glass path — inline get_current_user's logic with the injected db (do NOT call
    # require_admin/get_current_user as functions). Load user from the `session` cookie, require
    # is_approved + role=="admin", wrap as an operator with jti=None:
    user = await _load_cookie_user(request, db)               # plain helper (mirror deps.get_current_user body)
    if user.role != "admin":
        raise HTTPException(403, "Admin role required")
    return CockpitOperator(google_id=user.google_id, email=user.email, jti=None, token_exp=None)
```
Add the plain helper `_load_cookie_user(request, db)` (extract the decode+load body from `deps.get_current_user` so both it and this reuse it — Boy-Scout dedupe).

**Step 2:** Change the 8 admin routes from `Depends(require_admin)` → `Depends(require_any_admin)`, binding `operator: CockpitOperator`. **Self-guard (routes 4 & 5)** — compare by `google_id` (uniform for matched/unmatched; an unmatched operator's google_id matches no row, so it never self-triggers):
```python
if operator.google_id and target.google_id == operator.google_id and <revoking-approval | deleting>:
    raise HTTPException(400, "cannot revoke/delete your own admin account")
```

**Step 3: jti single-use replay on destructive routes (resolves review B1 / §8 #4).** At the TOP of routes 2 (refresh), 4 (approval), 5 (delete), when the cockpit path is active:
```python
if operator.jti and not consume_jti(operator.jti, operator.token_exp):
    raise HTTPException(409, "assertion already used")
```
(Cookie path has `jti is None` → skipped; it isn't replayable in the same way.)

**Step 4: Last-admin invariant, LOCKED against TOCTOU (resolves review B3 / §8 #1).** Do the count-lock-and-mutate **in one transaction** using the route's own session. Routes 4/5 currently go straight to UPDATE/DELETE without loading the row — first **load `target`** (add the SELECT if absent): `target = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none(); if target is None: raise HTTPException(404)`. Then lock the approved-admin rows `FOR UPDATE` so concurrent requests serialize:
```python
# inside the route's `async with AsyncSessionLocal() as session:` transaction, BEFORE the mutation:
if target.role == "admin" and target.is_approved:  # demote(4)/delete(5) of an approved admin
    locked = (await session.execute(
        select(User.id).where(User.role == "admin", User.is_approved == True)
        .with_for_update()
    )).scalars().all()
    if len(locked) <= 1:
        raise HTTPException(409, "cannot remove the last approved admin")
# ... then the existing PATCH/DELETE in the SAME transaction/commit
```
Applies to matched AND unmatched operators, independent of the self-guard.

**Step 5: Audit** — one structured log line per mutating call (routes 2, 4, 5): `operator.google_id`, `operator.email`, `operator.jti`, action, target id.

**Step 6:** Tests `test_admin_lastadmin.py` (mirror the existing `backend/tests/test_admin*.py` fixtures/client) — one `def test_` per: last approved admin cannot be **deleted** (409) nor **demoted** (409) via BOTH a matched and an unmatched cockpit operator; a non-last admin CAN; self-guard still 400s for a matched operator acting on self (by google_id); **replayed jti → 409** on each of the 3 destructive routes; the cookie break-glass path still works (jti=None, no replay error).

**Step 7: Commit**
```bash
git add backend/app/api/admin.py backend/app/api/deps.py backend/tests/test_admin_lastadmin.py
git commit -m "feat(admin): dual-auth (cookie|cockpit) + last-admin invariant + audit (contract §4/§8)"
```

---

## Task 4: Internal network for cockpit reachability [DONE]

**Depends on:** none (infra); independent of code tasks.

**Files:** Modify `docker-compose.prod.yml`

**Step 1:** Add a dedicated **external** internal network and attach ONLY `backend` to it, with a **mandatory unique alias** (contract §5/§8 #9) — keep `backend` off Traefik:
```yaml
services:
  backend:
    networks:
      default: {}
      d2x-internal:
        aliases: [rcn-scraper-backend]
networks:
  # ... existing default + web ...
  d2x-internal:
    external: true
```
**Step 2:** Document the preflight in the plan Verification: `docker network create d2x-internal` must exist on the VPS BEFORE deploy (contract §8 #10). Do NOT add it to `web` or expose it publicly.

**Step 3: Commit**
```bash
git add docker-compose.prod.yml
git commit -m "feat(infra): backend joins internal d2x-internal network (alias rcn-scraper-backend)"
```

---

## Task 5: Doc hygiene [DONE]

**Depends on:** none

**Files:** Modify `CLAUDE.md`

**Step 1:** Fix the stale `CLAUDE.md:7,48` "single user, no auth" → reflect the real model (Google-SSO + role-based admin; and now the cockpit-assertion path). Keep it a one-line-accurate correction, no scope creep.

**Step 2: Commit**
```bash
git add CLAUDE.md
git commit -m "docs: correct stale single-user/no-auth note in CLAUDE.md"
```

---

## Verification

Run once after all tasks `[DONE]` (dglabs.executing-plans Step 5):
```bash
# Backend unit + new tests (project convention)
docker compose exec backend pytest tests/ -v
# or, if the stack isn't up, the repo's local test path:
cd backend && python -m pytest tests/ -v
```
Expected: all tests pass incl. the new cockpit-auth (Task 2) + last-admin (Task 3) suites.

**Static + config check:**
- Confirm the cookie/break-glass path (`require_admin`, `security.py`) is untouched.
- Confirm `COCKPIT_AUTH_ENABLED` defaults False (feature dormant until the cockpit + JWKS + network are in place — no startup coupling, contract §8 #9).
- Confirm no admin route lost its guard and no route is publicly reachable (backend still off Traefik).

**Deploy preflight (documented, not executed here):** `docker network create d2x-internal` on the VPS before the compose change deploys.

---

## Notes

- **Break-glass preserved:** the cookie/HS256 admin path stays fully functional — this plan is additive. It is dropped only in a later, explicit step after the cockpit facet is verified through a key rotation (contract §8 #11/#12).
- **No SPA retirement here** — the `admin` service + `admin.rcn-scout.d2x-labs.de` stay live until the cockpit facet is verified (separate later step).
- **jti replay cache is in-process** (single backend replica today); if rcn-scraper ever scales to multiple backend replicas, move to a shared store (note in contract).
- The cockpit side (minting, JWKS endpoint, adapter, Sequence admin UI) is `d2x-control-plane` PLAN_006, built against the same contract.
