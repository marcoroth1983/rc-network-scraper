# rc-scanner — Umami Analytics Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Add cookieless, self-hosted **Umami** page-view tracking to the public rc-scanner frontend (`rcn-scout.d2x-labs.de`) — a single `<script>` snippet in the Vite HTML shell — so page views appear in the shared Umami dashboard at `analytics.d2x-labs.de`.

**Architecture:** The Umami stack already runs (self-hosted, cookieless) at `analytics.d2x-labs.de`. This plan only **onboards** the public frontend: create a "website" in Umami → obtain its `website-id`, then add the standard `<script defer …>` snippet to `frontend/index.html`. Mirrors the immo-calculator onboarding (`D:\DEVELOPMENT\_workplace_AI\immo-calculator`) — **with one deliberate difference: rc-scanner has no CSP, so no CSP edit is needed** (immo-calc's onboarding had to add `analytics.d2x-labs.de` to `script-src`/`connect-src` because its `nginx.conf` sets a strict CSP; rc-scanner sets none). No backend change, no dependency, no migration.

**Weight:** **Thin.** Additive; 1 file modified (`frontend/index.html`); no backend, no migration, no CSP; ≤ 4 tasks. One plan-review cycle, Codex parallel OFF, automated-only verification.

**Tech Stack:** Umami snippet (`analytics.d2x-labs.de/script.js`), Vite/React 18 SPA served by nginx behind Traefik. GitHub Actions release-gated deploy.

**Breaking Changes:** No. Additive: a single `<script>` tag in the public frontend's HTML shell.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-07-16 |
| Human | approved | 2026-07-16 |

---

## Context (pre-write scan, verified 2026-07-16)

- **Two SPAs in this repo:** `frontend/` (public, `rcn-scout.d2x-labs.de`) and `admin/` (`admin.rcn-scout.d2x-labs.de`), each its own Vite shell + nginx image (`docker-compose.prod.yml:44-74`). **This plan scopes analytics to the PUBLIC frontend only.** The admin SPA is an ops tool — not tracked here (see Out of Scope). Repeat later with its own Umami website + id if ever wanted.
- **HTML entry (public):** `frontend/index.html` — Vite shell: `<html lang="en">`, `<title>RC Scout</title>`, `<head>` ends at line 17, `<div id="root">` + `/src/main.tsx` (lines 19-20). Snippet goes in `<head>` before `</head>` (line 17). Mirror reference: immo-calc `index.html:8` (same `<script defer …>` form).
- **Router:** **BrowserRouter** (`frontend/src/main.tsx:3,19`). Path-based → Umami's default History-API tracking covers route changes. **No hashchange hook** needed (immo-calc needed one only because it uses `HashRouter`; see immo-calc `src/main.tsx:18-20`). Not applicable here.
- **CSP — NONE (verified).** `frontend/nginx.conf:8-11` sets `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` — **no `Content-Security-Policy`**. Backend `backend/app/main.py:201-207` registers only `CORSMiddleware` — no security-header/CSP middleware. No `<meta http-equiv="Content-Security-Policy">` anywhere. → **No CSP edit needed**; nothing blocks the external Umami script or its `POST /api/send` beacon.
- **Access model (~5 approved users):** Google OAuth + JWT, app-level only (`backend/app/main.py:209` auth router; `get_current_user` in `backend/app/api/deps.py:12-29` gates on the DB flag `user.is_approved`, not a static email list; envs `GOOGLE_CLIENT_ID`/`JWT_SECRET` in `docker-compose.prod.yml:27-29`). nginx serves `index.html` statically to **every** visitor (`frontend/nginx.conf:50-52`, `location / → try_files … /index.html`) with no auth check — the whitelist gates the `/api/*` data layer, not the static HTML shell. → **The Umami snippet loads for all visitors (including the login screen), so tracking works for the ~5 authorized users. No auth gate blocks the script.** (Note: CLAUDE.md's "single user, no auth" line is stale — OAuth + whitelist is the real model.)
- **Domain:** `rcn-scout.d2x-labs.de` (`docker-compose.prod.yml:51`, Traefik `Host(...)`).
- **Deploy trigger:** `release: published` (`.github/workflows/deploy.yml:3-5`) — builds nginx/backend/admin images, then SSH-deploys to the VPS with a `/health` gate. Same release convention as immo-calculator.
- **Served in prod:** Vite build → nginx static (`root /usr/share/nginx/html`, SPA fallback). The snippet in `index.html` reaches prod once built + released.

Umami admin credentials for Task 1 are held out-of-band (NOT in this repo).

---

### Task 1: Create the Umami website → website-id [DONE]

**DONE 2026-07-16 — website created in the live Umami. `website-id = b9f5f2b4-0764-4d02-8513-6a76fc13b4d6` (name `rc-scout`, domain `rcn-scout.d2x-labs.de`).** Created via the api-client `userId`+`APP_SECRET` path on the VPS (secret never left the box), not the Python/admin-password snippet below (kept as reference). Use this id verbatim in Task 2.

**Owner step — requires the live Umami admin credentials for `analytics.d2x-labs.de` (out-of-band, not in this repo).** No repo change; produces the `website-id` that Task 2 consumes.

**Step 1:** Run from any machine that can reach `analytics.d2x-labs.de` (Python stdlib only). Replace `<ADMIN_PW>` with the out-of-band Umami admin password:
```python
import json, urllib.request, urllib.error
BASE = "https://analytics.d2x-labs.de"
def call(m, p, tok=None, body=None):
    r = urllib.request.Request(BASE + p, data=(json.dumps(body).encode() if body else None), method=m)
    r.add_header("Content-Type", "application/json")
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
_, d = call("POST", "/api/auth/login", body={"username": "admin", "password": "<ADMIN_PW>"})
tok = d["token"]
s, site = call("POST", "/api/websites", tok, {"name": "rcn-scout", "domain": "rcn-scout.d2x-labs.de"})
print("rcn-scout website-id:", site.get("id"), s)
```

**Step 2:** Record the printed `website-id` for Task 2. (No commit — this is a Umami-side action.)

---

### Task 2: Add the Umami snippet to the public HTML shell (no CSP change) [ ]

**Depends on:** Task 1

**Files:**
- Modify: `frontend/index.html` (insert before `</head>`, line 17)

**Reuse check:** Mirrors immo-calc `index.html:8` (`<script defer src="https://analytics.d2x-labs.de/script.js" data-website-id="…">`). Same snippet form; only the `data-website-id` value differs. No new component.

**Step 1:** In `frontend/index.html`, add inside `<head>` (immediately before the `</head>` on line 17), replacing `RCN_WEBSITE_ID` with the id from Task 1:
```html
    <script defer src="https://analytics.d2x-labs.de/script.js" data-website-id="b9f5f2b4-0764-4d02-8513-6a76fc13b4d6"></script>
```
Do **NOT** touch `admin/`. Do **NOT** add any CSP or edit `frontend/nginx.conf` — no CSP exists (Context) and none is required for the snippet to load. No route-change hook is needed (BrowserRouter — Umami auto-tracks via History API).

**Step 2: Commit**
```bash
git add frontend/index.html
git commit -m "feat(analytics): cookieless Umami snippet on public frontend (analytics.d2x-labs.de)"
```

---

### Task 3: Release + deploy [ ]

**Depends on:** Task 2

**Step 1:** Patch version bump + `CHANGELOG.md` entry mirroring the repo's release convention — under `### Added`: "Cookielose Zugriffsstatistik (Umami) auf der öffentlichen Seite". Commit.

**Step 2:** Cut a GitHub Release for the new tag. The `release: published` workflow (`.github/workflows/deploy.yml`) builds the nginx/frontend image and SSH-deploys it to the VPS (`/health`-gated). The snippet reaches prod once the release deploys.

---

## Verification

Automated / real-browser checks after the release deploys (no test suite touched — additive HTML only):

1. **Script load:** In a real browser at `https://rcn-scout.d2x-labs.de`, open DevTools → Network: `analytics.d2x-labs.de/script.js` returns **200**, and a `POST …/api/send` returns **200** on page load (no CSP to block it).
2. **Route tracking:** Navigate between routes (BrowserRouter) → a second `POST …/api/send` fires (Umami History-API auto-track). Confirm the `rcn-scout` website shows page views in the Umami dashboard at `analytics.d2x-labs.de`.
3. **Authorized-user reach:** Log in as one of the ~5 whitelisted Google accounts → confirm the page view still registers (the snippet is in the static shell, unaffected by the app-level auth gate).
4. **No regression:** Public site loads and behaves as before; no console CSP/errors introduced.

## Plan Review
<!-- dglabs.agent.review-plan — 2026-07-16 -->

### Self-Review Gate (Pass 0)
- [x] 1. Placeholder scan — `grep -nE "TODO|FIXME|XXX|TBD"` → 0 matches.
- [x] 2. Dropped-field orphan scan — n/a, no field renamed/dropped during editing.
- [x] 3. Line-anchor freshness — all `path:line` refs verified against live files: `frontend/index.html` head ends line 17, `<div id="root">`/`main.tsx` mount lines 19-20; `frontend/src/main.tsx:3,19` (BrowserRouter import/usage); `frontend/nginx.conf:8-11` (security headers, no CSP); `backend/app/main.py:201-207` (CORSMiddleware only), `:209` (auth router); `docker-compose.prod.yml:27-29` (env vars), `:51` (Traefik Host rule); `.github/workflows/deploy.yml:3-5` (release trigger). All match exactly.
- [x] 4. Test-count consistency — n/a, no tests touched (additive HTML only, correctly declared in Verification).
- [x] 5. Deleted-class caller check — n/a, nothing deleted.
- [x] 6. Mirror-reference verification — immo-calc `index.html:8` confirmed to contain the exact `<script defer src="https://analytics.d2x-labs.de/script.js" data-website-id="…">` form cited; immo-calc `src/main.tsx:18-20` confirmed to contain the `hashchange` → `window.umami?.track(...)` hook cited as the reason rc-scanner (BrowserRouter) does *not* need one.
- [x] 7. Convention contradictions across tasks — n/a, single linear task chain (Task1 website-id → Task2 consumes verbatim → Task3 releases). `website-id = b9f5f2b4-0764-4d02-8513-6a76fc13b4d6` is identical in Task 1 (line 39) and Task 2 (line 78).

### Structural Checklist (Pass 1.A)
- [x] Required sections present (Context, Breaking Changes, Steps, Verification, Out of Scope)
- [x] Step status markers present (`[DONE]`, `[ ]`, `[ ]`)
- [x] Step granularity suitable for a fresh AI instance (Task 2 is a single-line HTML insert; Task 1 already executed manually; Task 3 is a standard release-cut, matching repo convention)
- [x] Test files named per step — n/a correctly declared (no tests touched, additive HTML only)
- [x] Breaking changes marked — explicitly "No" with rationale (additive `<script>` tag)
- [x] BREAK markers sensible — zero BREAKs, consistent with a 3-task thin plan

### Codebase Verification (concrete claims)
All claims independently re-verified against the live repo (2026-07-16):
- `frontend/index.html`: `</head>` is line 17, `<div id="root">` is line 19, `<script type="module" src="/src/main.tsx">` is line 20 — plan's insertion point and line references are exact.
- `frontend/src/main.tsx`: `BrowserRouter` imported line 3, used line 19 — confirmed. Umami's default History-API auto-tracking applies; no `hashchange` hook needed (correctly contrasted with immo-calc's `HashRouter`).
- CSP claim: repo-wide grep for `Content-Security-Policy` returns zero hits outside the plan itself. `frontend/nginx.conf:8-11` sets only HSTS/X-Content-Type-Options/X-Frame-Options/Referrer-Policy. `backend/app/main.py:201-207` registers only `CORSMiddleware`. No meta CSP tag anywhere. Claim confirmed — this is the load-bearing assumption for the whole plan and it holds.
- Domain/Traefik: `docker-compose.prod.yml:51` — `Host(\`rcn-scout.d2x-labs.de\`)` confirmed on the `nginx` service (public frontend), distinct from `rcn-admin`/`admin.rcn-scout.d2x-labs.de` (line 67) — the plan correctly scopes to the public site only.
- Deploy trigger: `.github/workflows/deploy.yml:3-5` — `on: release: types: [published]` confirmed; job builds and pushes `nginx`/`frontend` image (context `./frontend`, lines 39-47) among others, then SSH-deploys with a `/health` gate (lines 66-78) — matches plan's Task 3 description.
- Task 1 → Task 2 website-id consistency: `b9f5f2b4-0764-4d02-8513-6a76fc13b4d6` used verbatim in both — confirmed.
- Minor inaccuracy found and fixed: the Context section claimed an "email whitelist in `backend/app/api/deps.py`". Actual code (`get_current_user`, `deps.py:12-29`) gates on the DB flag `user.is_approved`, not a static email list — corrected in place. Non-blocking: doesn't affect Task 2/3 actions or the (still-true) conclusion that the static HTML shell is served to all visitors unauthenticated.

### AI-Review Pass 2
Skipped per thin-plan UI-only default (orchestrator classified Weight: Thin — additive, 1 file modified, no backend/migration/CSP/contract change, ≤ 4 tasks; plan explicitly states "Codex parallel OFF"). No complex state machine, unusual async, or new accessibility convention present that would warrant opt-in.

### 🔴 Blocking
None.

### 🟡 Non-Blocking
1. [Agent] `docs/PLAN_035_umami_analytics.md:28` (pre-fix) — Context prose called the auth model an "email whitelist" when the code implements an `is_approved` boolean flag (no email list exists in `deps.py`). Fixed in this review pass; flagged for visibility since the phrase also appears in Marco's own project-state framing ("~5 users") and could mislead future plans referencing the same file.
2. [Agent] Task 1's Python snippet (lines 44-61) hardcodes `username: "admin"` — reasonable as an out-of-band, already-executed, one-off script (Task 1 is `[DONE]`), but if ever re-run for a second onboarding (e.g. the admin SPA, noted in Out of Scope) the snippet should be parameterized rather than copy-pasted with the domain/name hardcoded. No action needed now.

### Verdict
APPROVED — all codebase claims verified accurate (index.html line anchors, BrowserRouter, no-CSP assertion, domain/Traefik config, deploy trigger, website-id consistency, immo-calc mirror references), Self-Review Gate passes 7/7, structural checklist passes, and the one factual inaccuracy found (email-whitelist vs. is_approved flag) was non-blocking and has been corrected in place.

---

## Out of Scope

- The Umami stack itself (already live; owned by the `d2x-analytics` project).
- **Adding a CSP to rc-scanner.** rc-scanner intentionally has no CSP today; introducing one is a separate hardening task (risk of breaking Google-OAuth redirects / inline styles) — not part of analytics onboarding.
- The **admin SPA** (`admin.rcn-scout.d2x-labs.de`) — ops-only; onboard later with its own website-id if wanted.
- Any event- or user-level tracking beyond page views.
