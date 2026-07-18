# Cockpit Admin Adapter — Boundary Contract (DRAFT)

> **Status: REVIEWED + CODEX-HARDENED 2026-07-17 — ready for owner sign-off.** Auth crypto (§3, RS256/JWKS short-lived signed assertion) is research-validated and confirmed sound by an independent Codex high-reasoning cross-check. That cross-check returned **FLAWED** on the first draft and surfaced real holes — **all folded into §4 (immutable `google_id` identity + last-admin invariant + break-glass) and §8 (MUST-implement hardening: strict JWT profile, replay protection for destructive routes, JWKS/rotation rules, no startup coupling, strict rollout order, break-glass-before-retirement).** The two implementation plans (`rcn-scraper` PLAN_036, cockpit PLAN_006) are BOUND to §8. Pending: owner sign-off (§7 decisions + the §8 hardening), then the plans are written + approved. Shared spec both sides build against; template for future adapters (do-it, …).

## 1. Purpose

The d2x control-plane cockpit consumes rcn-scraper's admin API and **rebuilds the admin UI natively** (Sequence design) as the `rc-scout` app's **Admin facet** ("Adapt" pattern). The standalone admin SPA (`admin.rcn-scout.d2x-labs.de`) is **retired** — not deployed separately. The cockpit is the single unified admin; rcn-scraper stays the data/logic owner and exposes its `/api/admin/*` as the integration surface.

**Hard constraint (owner):** no shared long-lived "god" secret that grants full admin if leaked. Real per-user identity + audit. See §3.

## 2. Data contract — the 8 admin endpoints (verified against `backend/app/api/admin.py`, 2026-07-17)

All are router-relative to `/api/admin`, all guarded by `require_admin` (role == "admin"). The cockpit adapter mirrors these exactly (the existing `admin/src/api/client.ts` is the reference client).

| # | Method + path | Params | Response | Notes the adapter MUST preserve |
|---|---|---|---|---|
| 1 | `GET /api/admin/llm-models` | — | `LLMModelRow[]` | |
| 2 | `POST /api/admin/llm-models/refresh` | — | `LLMModelRow[]` | triggers upstream refresh |
| 3 | `GET /api/admin/users` | — | `UserRow[]` | order: pending first, then newest |
| 4 | `PATCH /api/admin/users/{id}/approval` | path `id:int`; body `{ is_approved: bool }` | `UserRow` | **self-guard:** 400 if caller revokes their own approval; 404 if missing |
| 5 | `DELETE /api/admin/users/{id}` | path `id:int` | 204 | **self-guard:** 400 on self-delete; **404 if missing**; GDPR hard-delete cascades |
| 6 | `GET /api/admin/users/{id}/stats` | path `id:int` | `UserStats` | |
| 7 | `GET /api/admin/metrics/summary` | — | `MetricsSummary` | |
| 8 | `GET /api/admin/metrics/timeseries` | query `days:int` (1..365, default 30) | `MetricsTimeseries` | server zero-fills the window |

**Schemas** (inline in `admin.py`; the cockpit's `@d2x/types` mirrors these):
- `UserRow { id:int, email:str, name:str|null, is_approved:bool, role:str, created_at:datetime, last_seen_at:datetime|null }`
- `LLMModelRow { model_id:str, position:int, is_active:bool, active_now:bool, context_length:int|null, created_upstream:datetime|null, added_at:datetime, last_refresh_at:datetime, consecutive_failures:int, disabled_until:datetime|null, last_error:str|null }`
- `MetricsSummary { users_total, users_approved, users_pending, users_active_7d, users_active_30d, listings_total, favorites_total, saved_searches_total }` (all int)
- `MetricsTimeseries { days:int, listings_new:[{day:str,value:int}], listings_closed, users_new, logins, notifications }`
- `UserStats { user_id:int, saved_searches:int, favorites:int, push_devices:int, logins_total:int, logins_30d:int, created_at:datetime, last_seen_at:datetime|null }`

**Contract stability:** these shapes are the boundary. If rcn-scraper changes an admin schema, this doc + the cockpit `@d2x/types` mirror update in lockstep.

## 3. Auth — the security core (PROPOSED, pending cross-check)

**Today:** `/api/admin/*` requires a `session` cookie = **HS256** JWT (`sub`=int user id, 30d exp, symmetric secret `JWT_SECRET`), then `role == "admin"`. This is per-end-user, cookie-bound — it does NOT fit a server-to-server call from the cockpit.

**Proposed cockpit path (no shared god-key):**
1. **Identity source = the cockpit's own login.** The cockpit already authenticates the operator (Google OAuth + email allowlist). No new IdP/SSO needed.
2. **Cockpit → rcn-scraper is server-to-server** with a **short-lived, asymmetric, user-scoped assertion**:
   - The cockpit backend signs a JWT with its **private key (RS256)**. rcn-scraper verifies with the cockpit's **public key** only (published at a cockpit JWKS URL or shipped as a pinned PEM). A leaked public key is useless; **no shared symmetric secret exists**.
   - Claims: `iss: "d2x-cockpit"`, `aud: "rcn-scraper-admin"`, short `exp` (≤ 2–5 min), `sub`/`act`: the **acting operator's email** (from the cockpit session), and `role: "admin"`. Optionally a per-request `jti` for audit.
   - rcn-scraper adds a **new auth dependency** (e.g. `require_cockpit_admin`) that: verifies the RS256 assertion (issuer/aud/exp), extracts the operator email, and authorizes. This is **in addition to** the existing cookie path (which the retired SPA used) — or replaces it once the SPA is gone.
3. **Network isolation (defense-in-depth):** rcn-scraper's backend stays **private** (no public Traefik route, as today). The cockpit reaches it only over a **shared internal docker network** (see §5) — the admin API is never internet-exposed. So even a forged assertion needs internal network access.

**Standing-credential honesty:** the only standing secret is the cockpit's **private signing key** (same trust tier as the cockpit's session secret it already holds; asymmetric, never shared, rotatable). Absolute "zero credential" is only SPIFFE/mTLS-auto-rotation — out of scope for ~3–5 admins. This meets "no shared god-key + real identity + contained blast radius".

**Assertion spec (LOCKED — validated against current best-practice, 2026-07-17, sources below):**
- **Algorithm: RS256** (default — mandatory-to-implement, best PyJWT + Node library support). EdDSA (Ed25519) is an acceptable alternative since we own both ends (smaller/faster) — decide at plan time; RS256 unless a reason.
- **Key distribution: JWKS.** The cockpit publishes its public key at `https://admin.d2x-labs.de/.well-known/jwks.json` (with a `kid`); rcn-scraper fetches + caches it → **zero-downtime key rotation**, no PEM redeploy. (Pinned-PEM env is the fallback if a JWKS fetch path is undesirable.)
- **TTL: 1–5 minutes** (short — limits the replay window; minted per request/short session).
- **Claims:** `iss:"d2x-cockpit"`, `aud:"rcn-scraper-admin"`, `exp` (≤5 min), `nbf`, `iat`, `sub`/`act`: acting operator email, `role:"admin"`, `jti` (audit/replay).
- **Verifier (rcn-scraper) MUST:** pin an **algorithm allow-list** (reject `alg:none`/HS*), verify signature via JWKS, and check `iss`/`aud`/`exp`/`nbf`.
- **Verifier hardening (resolves review N1–N3):**
  - **Ignore token-embedded key headers** — the verifier fetches the key ONLY from the pinned JWKS config URL, and MUST reject/ignore `jku`, `x5u`, and inline `jwk`/`x5c` header params (else an attacker supplies their own key). Match by `kid` against the pinned JWKS only.
  - **JWKS fetch fails CLOSED** — if the cockpit JWKS URL is unreachable and no key is cached, **deny** (503/401), never allow. Cache the JWKS with a sane TTL; refresh on unknown `kid`.
  - **Replay:** the short `exp` (≤5 min) bounds the replay window. `jti` is logged for **audit**, not replay-prevention. If stricter is wanted later, add a small server-side `jti` seen-cache (TTL = token TTL) — optional, not required for v1.
- **Why not Traefik ForwardAuth trusted-identity headers:** that pattern has a recurring header-spoofing CVE class (CVE-2026-35051, CVE-2026-54763, underscore-alias bypass, fixed only in Traefik ≥ v2.11.51 / v3.6.22 / v3.7.6). A **signed JWT the app validates cannot be forged without the private key** and sidesteps the entire class — our server-to-server call does not rely on forwarded headers at all.

**Remaining OPEN (operational, not security-blocking):**
- Whether rcn-scraper keeps its cookie-auth path after the SPA retires (recommended: drop it, cockpit-only). See §7.

_Auth references (verified 2026-07-17): Traefik header-spoofing advisories [GHSA-5m6w-wvh7-57vm](https://github.com/traefik/traefik/security/advisories/GHSA-5m6w-wvh7-57vm), [CVE-2026-35051](https://www.systemshardening.com/articles/network/traefik-forwardauth-bypass/); service-to-service signed-JWT best practice — [microservices.io part 3 (2025)](https://microservices.io/post/architecture/2025/07/22/microservices-authn-authz-part-3-jwt-authorization.html), [WorkOS HMAC vs RSA vs ECDSA](https://workos.com/blog/hmac-vs-rsa-vs-ecdsa-which-algorithm-should-you-use-to-sign-jwts), [Scott Brady — which signing algorithm](https://www.scottbrady.io/jose/jwts-which-signing-algorithm-should-i-use), [David Sulc — JWKS zero-downtime rotation](https://www.davidsulc.com/blog/jws-apis-jwks-basics)._

## 4. Acting-admin identity & self-protection (must not be lost)

rcn-scraper's self-guards compare `target_user_id == current_admin.id` (its own int PK). The cockpit operator is a **different identity domain** (cockpit Google user, may or may not have an rcn-scraper `users` row).

**Resolution (HARDENED post-Codex cross-check 2026-07-17):**
- **Identity match is by immutable `google_id`, NOT email.** rcn-scraper's `users.google_id` (unique, stable) is the join key. The assertion carries the operator's Google **`sub` (= google_id)** as the identity claim + email for display/audit only. Email is fragile (case/alias/rename → could flip the same human to "unmatched" and bypass a self-guard) — Codex High finding. Normalize defensively, but authorize/self-match on `google_id`.
- **NEW invariant — last-admin protection (Codex Critical fix):** routes 4 (revoke approval) and 5 (delete) MUST refuse to remove/demote the **last remaining approved `role=="admin"` user**, checked at the DB level, **independent of the self-guard**. Without this, an unmatched cockpit operator (`matched_user is None`) — or a compromised one — could delete every rcn-scraper admin and hard-lock the app. This invariant holds for matched AND unmatched operators.
- Self-guard (no self-revoke/self-delete) still applies when `matched_user is not None` (compare `target_user_id == matched_user.id`).
- **Break-glass:** rcn-scraper KEEPS its own cookie-auth + `role=="admin"` path (its own Google login) as an independent admin route — **not dropped** until the cockpit facet is verified live through restarts + a full key rotation (§8). This guarantees a recovery path if the cockpit/JWKS is down.
- Every mutating call logs `google_id` + email + `jti` for cross-app audit.

**`require_cockpit_admin` return contract (LOCKED — resolves review B1):** the dependency returns a small value object, NOT a `User` (the operator may have no row):
```python
@dataclass
class CockpitOperator:
    google_id: str             # assertion `sub` — the immutable identity join key
    email: str                 # display / audit only
    role: str                  # "admin" (from the assertion), already checked
    matched_user: User | None  # users row iff google_id matches, else None
```
Route handlers: (a) enforce the **last-admin invariant** (above) always; (b) apply the self-guard only when `matched_user is not None` (`target_user_id == matched_user.id`). `google_id` + `email` + `jti` logged on every mutating call. This is a **new** dependency; `require_admin` (returns `User`, cookie path) stays as break-glass until the final cutover (§8).

## 5. Network topology

- rcn-scraper `backend` = `default` network only, **no Traefik labels** (private). Keep it private.
- **Internal URL the cockpit calls (LOCKED — resolves review B2):** `http://backend:8000/api/admin/*` — docker **service name `backend`** (no `container_name` set → the compose service name is the network DNS name), **uvicorn port 8000** (`backend/Dockerfile` CMD `--port 8000`; confirm against rcn-scraper's `nginx.conf` `proxy_pass` at plan time). Never the public `rcn-scout.d2x-labs.de` route.
- Reachability: attach both stacks to a **shared, internal, non-public docker network** — a dedicated **`d2x-internal` external network** both composes join. On it, rcn-scraper's `backend` MUST expose a **mandatory unique alias** `networks.d2x-internal.aliases: [rcn-scraper-backend]` (a bare `backend` collides across stacks — Codex Medium). The cockpit calls `http://rcn-scraper-backend:8000/api/admin/*`.
- **Restrict membership:** only the cockpit backend + rcn-scraper backend join `d2x-internal` (not every container) — the shared network expands lateral reach to the private admin port, so keep it minimal (Codex Medium).
- **CORS is a non-issue** (N4): this is a server-to-server call from the cockpit's NestJS backend, not a browser request — rcn-scraper's `ALLOWED_ORIGINS` does not need the cockpit origin, and must NOT be widened for this.

## 6. What each side does

**rcn-scraper (its own plan, next number `PLAN_036`):**
- Add `require_cockpit_admin` (RS256 assertion verify) alongside/replacing the cookie path on `/api/admin/*`.
- Config: the cockpit public key (JWKS URL or `COCKPIT_PUBLIC_KEY` PEM env), issuer/aud config.
- Attach backend to the shared internal network for cockpit reachability (keep it off Traefik).
- **Retire** the `admin` service + `admin.rcn-scout.d2x-labs.de` Traefik route + the `admin/` SPA dir — **only after** the cockpit facet is live (transition, not before).
- Fix stale `CLAUDE.md:7,48` ("single user, no auth" — actually Google-SSO + role-based).
- Audit log line per mutating admin call (operator email + jti).

**d2x-control-plane cockpit (plan `PLAN_006`):**
- `@d2x/types`: mirror the 8 schemas above.
- NestJS **rc-scout admin adapter module**: mints the RS256 assertion (holds the private key server-side), calls rcn-scraper's `/api/admin/*` internally, exposes them under the cockpit's own guarded routes (`/api/apps/rc-scout/admin/*` or similar), preserving role gating.
- **Private-key storage/rotation (resolves review N6):** the RS256 private key lives **server-side only** (env `COCKPIT_JWT_PRIVATE_KEY` / mounted secret — never in the repo, never shipped to the browser), tagged with a `kid`. The matching public key is served at the cockpit JWKS endpoint. Rotation = publish a new `kid` in JWKS, sign new tokens with it, retire the old `kid` after the TTL window (zero-downtime, no rcn-scraper redeploy).
- Frontend: the **Admin facet** for rc-scout (Sequence UI) — Users (list/approve/delete/stats), LLM-Models (list/refresh), Metrics (summary + timeseries charts) — replacing the placeholder facet. Mirrors the retired SPA's pages (`UsersPage`, `LlmPage`, `MetricsPage`) in the Sequence design.

## 7. Open decisions for the owner (checkpoint)
_(Auth format = resolved/locked in §3.)_
1. Shared internal network approach (§5) — dedicated `d2x-internal` external network vs. attach the cockpit to rcn-scraper's compose network. (Couples the two deploy stacks — deploy-plan concern.)
2. Drop rcn-scraper's cookie-auth path entirely once the SPA retires? (recommended: yes — cockpit-only.)
3. Retirement timing of `admin.rcn-scout.d2x-labs.de` — after the cockpit facet is verified live (transition, not before).
4. RS256 vs EdDSA for the assertion (RS256 default; EdDSA fine since we own both ends).

## 8. Hardening — MUST implement (Codex high-reasoning cross-check, 2026-07-17: verdict FLAWED → hardened)

The implementation plans (PLAN_036 / PLAN_006) are BOUND to these. Crypto direction (RS256/JWKS) confirmed sound; the following close the real holes:

**Security**
1. **Last-admin invariant** — DB-level refusal to delete/demote the last approved `role=="admin"` user, independent of the self-guard (§4). *Critical.*
2. **Immutable identity** — match operator by `google_id` (assertion `sub`), not email (§4).
3. **Strict JWT profile** — verifier enforces: required `kid`, fixed alg (allow-list, reject `none`/HS*), exact `iss`/`aud`, **`exp - iat` ≤ 5 min AND recent `iat`** (not just individual claim checks), small bounded clock skew (≤60s), unique `jti`.
4. **Replay protection for DESTRUCTIVE routes** — single-use `jti` seen-cache (TTL = token lifetime) on the mutating routes (PATCH approval, DELETE, POST refresh). Audit-only `jti` is insufficient there (Codex High). Reads may rely on short `exp` alone.
5. **Minting** strictly server-side, bound to an authenticated cockpit request; never reachable by any browser/SPA. Per-route audience/scope if cheap.
6. **JWKS client rules** — HTTPS only, no redirects to other hosts, request timeout + response-size cap, cache with TTL, throttle unknown-`kid` refetch (no refresh-storm), reject weak keys. Fail CLOSED.
7. **Key-rotation protocol** — publish new `kid` in JWKS → wait for verifier cache propagation → sign with new `kid` → retain old public key until all tokens signed with it have expired (> max TTL) → then remove. Never sign with a `kid` not yet propagated.
8. **Private key = issuer-wide credential** — honest framing: its compromise forges every admin assertion until rotation + cache expiry. Store as a mounted secret, restrict access, monitor, have the rotation runbook ready.

**Deployment / coupling (owner's explicit worry)**
9. **No startup coupling** — neither app's container startup/readiness may depend on the sibling being live. rcn-scraper serves its own site + break-glass cookie-admin even if the cockpit/JWKS is down. Separate alerts for "JWKS unreachable" vs "backend connectivity".
10. **`d2x-internal` preflight** — the external network is created + verified on the VPS BEFORE either compose change deploys (a deploy-step guard, not an assumption). Document creation + recovery.
11. **Rollout order (strict):** create network → rcn-scraper gains cockpit-auth **alongside** its existing cookie-admin (dual-auth) → cockpit facet built + verified live → test cold JWKS cache / cockpit restart / **one full key rotation** with break-glass intact → **only then** retire the standalone admin SPA + `admin.rcn-scout.d2x-labs.de` → **finally** (separate, explicit step) drop the cookie/HS256 path if desired. No indefinite dual-auth, but retirement is LAST.
12. **Break-glass preserved** — a tested recovery admin path (rcn-scraper's own cookie login) survives restarts, a JWKS outage, and one full key rotation before the SPA is retired. Retiring destructive-capable admin before this is verified turns the soft coupling into an irreversible hard one (Codex High).

---

_This DRAFT is grounded in a verified read of rcn-scraper (`admin.py`, `deps.py`, `security.py`, `main.py`, `models.py`, `docker-compose.prod.yml`) on 2026-07-17. Finalize §3/§5 before the implementation plans (`rcn-scraper` PLAN_036, cockpit PLAN_006) are approved._

---

## Review

_Review closed 2026-07-17: REVISE → addressed. 2 blocking fixed (B1 `require_cockpit_admin` returns `CockpitOperator{email,role,matched_user}`, §4; B2 internal URL pinned `http://backend:8000` + network-alias note, §5). 6 non-blocking fixed (jti/replay note, JWKS fail-closed, jku/x5u/embedded-jwk rejection, CORS non-issue, DELETE 404, private-key storage/rotation). Reviewer confirmed §2 data contract + §3 auth + §5 isolation sound against the real code. Original findings below (historical)._

<!-- dglabs.plan-reviewer — 2026-07-17 -->
<!-- Source: verified reads of admin.py, deps.py, security.py, config.py, docker-compose.prod.yml -->

### Verdict
**REVISE** — 2 blocking gaps that would leave each implementation plan with an unresolvable ambiguity before coding starts; 6 non-blocking findings.

---

### Blocking

**B1 — §4 — `require_cockpit_admin` return-type contract is unspecified (PLAN_036 blocker)**

The existing route handlers declare `current_admin: User = Depends(require_admin)` and branch on `current_admin.id` for the self-guards (lines 134 and 273 in `admin.py`). The contract says "if no matching rcn-scraper row, the operation proceeds without self-guard" — but does not specify what the new dependency returns in that case. The implementer faces three mutually incompatible options with different downstream effects:

1. Return `User | None` → every route handler that uses `current_admin.id` must be defensively patched: `if current_admin is not None and user_id == current_admin.id`.
2. Return a synthesised sentinel (`User(id=-1, ...)`) → self-guard comparisons silently pass, no route-handler changes needed, but it is a type lie.
3. Introduce a new `CockpitPrincipal` type → all six admin routes need dual-dependency signatures.

The contract must pick one and document it. Without this, PLAN_036's core auth dependency is ambiguous, and PLAN_006 cannot know what behavior to rely on for the "no rcn-scraper row" operator case.

**Recommended resolution:** add a sub-section to §4: `require_cockpit_admin` returns `User | None`; the two mutating routes (`PATCH /approval`, `DELETE /users/{id}`) receive an updated check `if current_admin is not None and user_id == current_admin.id`; read-only routes receive `_` as today (no change needed).

---

**B2 — §5 — Internal Docker service address for cockpit → rcn-scraper call is a placeholder, not a resolved value (PLAN_006 blocker)**

The contract writes `http://rcn-scraper-backend:PORT/api/admin/*`. Verified against `docker-compose.prod.yml`: the service is named `backend` (not `rcn-scraper-backend`). On a `d2x-internal` external network the cockpit would resolve it as the container hostname — either the compose service name within the rcn-scraper stack (which is `backend`, colliding with a likely same-named service in the cockpit stack), or an explicit `container_name`. Neither `container_name`, nor the internal port, is declared in the current compose file (FastAPI default is `8000`, but this is not documented in the contract or compose file). PLAN_006 cannot configure the NestJS adapter's `baseUrl` without the concrete hostname and port.

**Recommended resolution:** specify in §5:
- Assign `container_name: rcn-scraper-backend` to the `backend` service in `docker-compose.prod.yml` (or equivalent explicit hostname) and confirm the internal listening port (e.g. `8000`).
- Add to §7 the decision: `container_name` vs. hostname alias on the external network.
- PLAN_006 configures: `RCN_SCRAPER_ADMIN_BASE_URL=http://rcn-scraper-backend:8000`.

---

### Non-Blocking

**N1 — §3 — `jti` replay: no server-side jti-seen cache mandated**

The contract lists `jti` under claims and says "audit/replay" but does not mandate rcn-scraper maintain a jti-seen cache for the TTL window (1–5 min). Within the window a captured token is replayable. For ~3–5 admins and 1-5 min TTL this risk is low, but the decision should be explicit (accept risk, or add an in-memory/Redis jti set). If accepted, note it in `limitations.md`.

**N2 — §3 — JWKS-fetch failure behavior unspecified**

If the cockpit JWKS endpoint is unreachable at startup or during a request, the contract does not say whether rcn-scraper should fail closed (reject all admin requests) or serve from a stale cached key. The safe default is fail closed; implementers should not have to guess. Add one sentence to §3.

**N3 — §3 — `jku`/`x5u` header suppression not mentioned**

The contract mandates an algorithm allow-list to prevent `alg:none` attacks, but does not state that the JWKS-fetch URL must come from config (never from the token's `jku` header). Some PyJWT usage patterns (e.g. calling `PyJWKClient.get_signing_key_from_jwt(token)` after constructing the client from a user-controlled URL, or using `python-jose` with default options) can follow a token-embedded `jku`. Since PLAN_036 implementers will choose the verification pattern, one bullet in §3 should say: "JWKS URL is taken from config only — never from the JWT headers (`jku`, `x5u`); reject tokens that carry these headers."

**N4 — §3 — CORS / ALLOWED_ORIGINS clarification**

`config.py` shows prod `ALLOWED_ORIGINS: https://rcn-scout.d2x-labs.de`. FastAPI's CORSMiddleware only fires when an `Origin` request header is present (browser requests). A cockpit NestJS server-to-server HTTP call does not send `Origin`, so CORS is not a blocker — but this should be stated explicitly in §3 or §5 to prevent a PLAN_036 implementer from widening ALLOWED_ORIGINS unnecessarily ("cockpit backend makes server-to-server HTTP calls; no CORS config change required").

**N5 — §2 — DELETE /users/{user_id} 404 on non-existent user is undocumented**

The code raises 404 if the DELETE's `RETURNING id` yields no row (`admin.py` line 281). The contract table only documents 204 and the 400 self-guard. PLAN_006's adapter error-handling should know that 404 is a possible response from DELETE as well.

**N6 — Cockpit private key storage and rotation procedure unspecified**

§6 says the cockpit "holds the private key server-side" but does not say how (env var `COCKPIT_RS256_PRIVATE_KEY`? mounted secret? KMS?). PLAN_006 needs this decision before implementation. Recommend: env var (PEM, base64-encoded) injected at deploy time, with a note on rotation procedure (generate new pair, publish new `kid` in JWKS, deploy cockpit with new key — old tokens expire within TTL, no downtime).

---

### §2 Data Contract — Accuracy (verified line-by-line against admin.py)

All 8 endpoints, paths, methods, and Pydantic schema field names/types confirmed accurate. Three minor observations (none blocking the contract):

- Route path params are named `user_id` in code vs. `id` in the contract table (`{id}`). This is internal naming only; the URL shape is identical. Keep the table's `{id}` notation for brevity, or align — no functional difference.
- `UserRow.name: str | None` confirmed (line 22). `LLMModelRow` all 11 fields confirmed (lines 33–43). `UserStats` all 8 fields confirmed (lines 287–294). `MetricsSummary` and `MetricsTimeseries` confirmed.
- The self-guard on PATCH approval (line 134): triggers **before** the UPDATE, so it correctly short-circuits on self-revoke without touching the DB. 404 fires only after the UPDATE returns no RETURNING row. This behavior is accurately described in the contract.

### §3 Auth Design — Security Soundness (verified)

The RS256/JWKS assertion design is sound for this use case. The no-shared-god-key requirement is genuinely met: the only standing credential is the cockpit's RS256 private key (single-repo secret, never shared, asymmetric). The existing HS256 cookie path (`security.py` uses `JWT_SECRET` symmetric key; `deps.py` reads the `session` cookie) is separate and will be retired post-migration per §7. `iss`/`aud`/`exp`/`nbf` binding + algorithm allow-list + short TTL = correct mitigations. Gaps are N1/N2/N3 above.

### §5 Network Topology — Accuracy (verified)

`docker-compose.prod.yml` confirmed: `backend` service is on `default` network only, zero Traefik labels. `nginx` and `admin` services carry Traefik labels and join `web` external network. The backend is private from the public internet. The isolation claim is accurate. The unresolved concrete address is B2 above.
