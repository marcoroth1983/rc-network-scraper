# Retire Standalone Admin Console + Fix Deploy Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Bring the codebase in line with the already-live cockpit reality: retire the now-superseded standalone admin console (code + CI + compose), align the repo `docker-compose.prod.yml` to the live VPS state, and fix the false-green deploy pipeline (DEPLOY-01) so releases actually deploy and can't silently no-op.

**Architecture:** The d2x-control-plane cockpit now provides admin/analytics for rcn (verified live: cockpit → rcn `/api/admin/*` via RS256/JWKS over the private `d2x-internal` network). The standalone `admin/` SPA (`admin.rcn-scout.d2x-labs.de`, PLAN-034) is dead — not deployed, superseded. This plan removes it from the repo and makes the repo `docker-compose.prod.yml` **identical to the live VPS compose** (admin removed, cockpit env present, no `COOKIE_DOMAIN`/`ADMIN_URL`), then fixes `deploy.yml` to (a) **scp the compose to the VPS** on every deploy (root cause of DEPLOY-01: the workflow never synced it), (b) pin `backend`+`nginx` atomically via `IMAGE_TAG=<short-sha>` (replaces the manual `d4c8961` pin), (c) fail loudly (`set -euo pipefail`), (d) verify the deploy is **real** (running image digest == freshly pulled digest) so a stale no-op can't pass as green.

**Tech Stack:** GitHub Actions (`appleboy/ssh-action` + `appleboy/scp-action`), Docker Compose v2 on the VPS, Traefik. No application-code change (backend Python untouched → the deployed cockpit auth `d4c8961` is preserved functionally).

**Breaking Changes:** **No live impact.** The `admin.rcn-scout.d2x-labs.de` subdomain is already not deployed (removing it from the repo changes nothing running). The backend switches from a hand-pinned `d4c8961` image to `IMAGE_TAG=<sha>` built from the same tree → functionally identical (no backend code change). Users unaffected. The next release will re-build + re-deploy nginx+backend at the new SHA and scp the aligned compose.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-07-23 |
| Human | approved | 2026-07-23 |

_Human pre-approved autonomous execution ("ja leg los … mach das autonom", 2026-07-23). Reviewer to be set after review-plan cycle. Both must be `approved` before executing-plans runs._

---

## Context (verified live 2026-07-23 via VPS SSH + repo scan)

- **Live VPS `/opt/rcn-scout/docker-compose.prod.yml`** (the alignment truth): `db` + `backend` + `nginx` only — **no `admin` service**. `backend` pinned to `ghcr.io/marcoroth1983/rc-network-scraper/backend:d4c8961`, env has `COCKPIT_AUTH_ENABLED: "true"` + `COCKPIT_JWKS_URL: https://admin.d2x-labs.de/.well-known/jwks.json`, **no** `COOKIE_DOMAIN`/`ADMIN_URL`, joins `d2x-internal` (alias `rcn-scraper-backend`). `nginx` = `${IMAGE_TAG:-latest}`, Traefik router `rcn-scout.d2x-labs.de`. Networks: `default`, `web` (external), `d2x-internal` (external).
- **Repo `docker-compose.prod.yml` (stale drift):** still has the `admin` service (lines 62-76) + Traefik router `admin.rcn-scout.d2x-labs.de`; backend env still has `COOKIE_DOMAIN: .rcn-scout.d2x-labs.de` (34) + `ADMIN_URL: https://admin.rcn-scout.d2x-labs.de` (35) and **lacks** the `COCKPIT_*` env. Backend already joins `d2x-internal` alias `rcn-scraper-backend` (41-44). `d2x-internal` network already declared external (85-86).
- **`.github/workflows/deploy.yml` (DEPLOY-01):** builds+pushes 3 images incl. `admin` (49-57); deploy step runs `docker compose -f docker-compose.prod.yml pull nginx backend admin` (74) **against the compose file already on the VPS — never scp'd**. The VPS compose has no `admin` service → `pull … admin` → `no such service: admin` → aborts (no `set -e`) → `up -d` no-ops → `/health` hits the old site → false green. It does NOT copy the compose to the VPS. Health step: `curl --fail … http://localhost/health` (78).
- **VPS `/opt/rcn-scout/.env` keys** (compose substitution source): `DB_USER, DB_PASSWORD, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET, IMAGE_TAG, OPENROUTER_*, TELEGRAM_*(legacy), VAPID_*`. `COCKPIT_*` are **literals in the compose**, not from `.env` → scp'ing the aligned compose carries them. `IMAGE_TAG` present (empty).
- **`admin/` directory** still in the repo (Vite/React SPA, its own Dockerfile/nginx.conf). **`admin/` is NOT in the dev `docker-compose.yml`** (only prod compose + CI reference it).
- **PWA (`frontend/`)** has **no admin pages/routes** (removed in PLAN-034); only benign role gates remain (`ScrapeLog.tsx:62`, `DetailPage.tsx:247,524`, `useAuth.ts:7` type) — **keep these, not in scope.**
- **Deployed backend `d4c8961`** = on `main`, contains PLAN-036 cockpit dual-auth + all review fixes. Backend Python is NOT touched by this plan.
- **deploy trigger:** `release: published` (`deploy.yml:3-5`); secrets `VPS_HOST_STAGING`/`VPS_USER_STAGING`/`VPS_SSH_KEY_STAGING` (66-71).

---

## Task 1: Align repo `docker-compose.prod.yml` to the live VPS state [DONE]

**Files:** Modify `docker-compose.prod.yml`

**Reuse check:** No new component; the live VPS compose is the canonical reference — mirror it exactly (minus the manual `backend` pin, which Task 3 replaces with the `IMAGE_TAG` model). After this task the repo compose must equal the live compose except: `backend` image uses `${IMAGE_TAG:-latest}` (not the literal `d4c8961`).

**Step 1:** In the `backend` service `environment:`, **remove** these two lines:
```yaml
      COOKIE_DOMAIN: .rcn-scout.d2x-labs.de
      ADMIN_URL: https://admin.rcn-scout.d2x-labs.de
```
and **add** (after `VAPID_SUBJECT`), matching the live literals:
```yaml
      # Cockpit assertion path (PLAN-036 dual-auth; cookie break-glass kept). issuer/audience use in-code defaults.
      COCKPIT_AUTH_ENABLED: "true"
      COCKPIT_JWKS_URL: https://admin.d2x-labs.de/.well-known/jwks.json
```
Leave the `backend` image as `ghcr.io/marcoroth1983/rc-network-scraper/backend:${IMAGE_TAG:-latest}` (Task 3 makes the deploy set `IMAGE_TAG`). Leave the `backend` `networks:` (default + d2x-internal alias) unchanged.

**Step 2:** **Delete the entire `admin:` service block** (repo lines 62-76 — the service, its Traefik `rcn-admin` router labels, and its `networks`). Leave `db`, `backend`, `nginx`, `volumes`, and the `networks:` section (incl. `d2x-internal` external) intact.

**Step 3: Commit**
```bash
git add docker-compose.prod.yml
git commit -m "chore(deploy): align prod compose to live — drop admin service + COOKIE_DOMAIN/ADMIN_URL, add cockpit env (PLAN-037)"
```

---

## Task 2: Remove the standalone `admin/` app + its CI image [DONE]

**Depends on:** none (independent of Task 1)

**Files:** Delete `admin/` (whole directory); Modify `.github/workflows/deploy.yml`

**Step 1:** Remove the standalone admin SPA entirely:
```bash
git rm -r admin/
```

**Step 2:** In `.github/workflows/deploy.yml`, **delete the "Build & push admin image" step** (the `docker/build-push-action` block with `context: ./admin`, ~lines 49-57). (The `pull` list on line 74 is fixed in Task 3.) Do not touch the nginx/backend build steps.

**Step 3: Commit**
```bash
git add -A
git commit -m "chore(admin): remove retired standalone admin console + its CI image build (superseded by d2x cockpit) (PLAN-037)"
```

---

## Task 3: Fix the deploy pipeline (DEPLOY-01) — sync compose, atomic tag, honest health [DONE]

**Depends on:** Task 1, Task 2

**Files:** Modify `.github/workflows/deploy.yml`

**Reuse check:** The build job already computes `steps.tag.outputs.sha` (`GITHUB_SHA::7`). Reuse it as `IMAGE_TAG`. The repo already uses `appleboy/ssh-action`; add `appleboy/scp-action@v0.1.7` (same secrets) for the compose copy.

**Step 1 — pull list:** In the deploy `script`, change `docker compose -f docker-compose.prod.yml pull nginx backend admin` → `pull nginx backend` (admin no longer exists).

**Step 2 — scp the compose to the VPS BEFORE the ssh deploy step.** Add, as the first three steps of the `deploy` job (before the existing "Deploy to VPS" step), in this exact order:
```yaml
      - name: Checkout
        uses: actions/checkout@v4

      - name: Copy compose to VPS
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.VPS_HOST_STAGING }}
          username: ${{ secrets.VPS_USER_STAGING }}
          key: ${{ secrets.VPS_SSH_KEY_STAGING }}
          source: docker-compose.prod.yml
          target: /opt/rcn-scout/

      - name: Generate short SHA tag
        id: tag
        run: echo "sha=${GITHUB_SHA::7}" >> $GITHUB_OUTPUT
```
The `deploy` job already has `permissions: contents: read`. The Checkout step puts `docker-compose.prod.yml` on the runner for scp. The `tag` step (id `tag`) makes `${{ steps.tag.outputs.sha }}` available to the following ssh-action step — it must run in this job because `steps.*` context is job-local (the `build` job's step outputs are not reachable from `deploy` via `steps.*`; `GITHUB_SHA` is a global env var so the same `::7` slice gives the same value). The `tag` step must precede the "Deploy to VPS" ssh-action step; it can come before or after the scp step since both are independent.

**Step 3 — atomic SHA pin + honest deploy.** Replace the ssh `script` body with (note `set -euo pipefail`, `IMAGE_TAG` export so backend+nginx pin to the just-built SHA, `--force-recreate`, and the **real-deploy assertion**):
```bash
set -euo pipefail
cd /opt/rcn-scout
export IMAGE_TAG="${{ steps.tag.outputs.sha }}"
# ensure the internal cockpit network exists (idempotent)
docker network inspect d2x-internal >/dev/null 2>&1 || docker network create d2x-internal
docker compose -f docker-compose.prod.yml pull nginx backend
docker compose -f docker-compose.prod.yml up -d --force-recreate --remove-orphans nginx backend
# Honest gate: the running images MUST equal the freshly-pulled tag (catches silent no-op)
for svc in nginx backend; do
  running=$(docker inspect --format '{{.Image}}' "rcn-scout-${svc}-1")
  pulled=$(docker image inspect --format '{{.Id}}' "ghcr.io/marcoroth1983/rc-network-scraper/${svc}:${IMAGE_TAG}")
  [ "$running" = "$pulled" ] || { echo "DEPLOY STALE: rcn-scout-${svc}-1 not on ${IMAGE_TAG}"; exit 1; }
done
docker image prune -f
sleep 10
curl --fail --retry 3 --retry-delay 5 --max-time 10 http://localhost/health
```

**Step 4: Commit**
```bash
git add .github/workflows/deploy.yml
git commit -m "fix(ci): DEPLOY-01 — scp compose to VPS, atomic IMAGE_TAG pin, set -e, real-deploy digest gate (PLAN-037)"
```

---

## Task 4: Docs — reflect retirement + close backlog items [DONE]

**Depends on:** none

**Files:** Modify `docs/definition.md`, `docs/limitations.md`, `docs/backlog.md`; move `docs/PLAN_036_cockpit_admin_auth.md` → `docs/archive/`

**Step 1:** `docs/definition.md` — update the Admin Console row: the standalone console is **removed**; admin/analytics for rcn is now the central **d2x-control-plane cockpit** (`admin.d2x-labs.de`) calling rcn's `/api/admin/*` via RS256/JWKS over the private `d2x-internal` network (PLAN-036). Remove the stale note about the PWA `/admin` removal only if it still references a live standalone console; keep it factual.

**Step 2:** `docs/limitations.md` — the "Standalone Admin Console built but frozen" entry is now **resolved**: replace it with a short note that the console + its subdomain were **retired in PLAN-037** and the admin surface is the d2x cockpit.

**Step 3:** `docs/backlog.md` — mark **DEPLOY-01** resolved (strike through + "Fixed in PLAN-037: compose scp-sync, atomic IMAGE_TAG, real-deploy digest gate"). DEPLOY-02 stays struck (already superseded). Remove/close the "Admin Console (PLAN-034) — deferred review items" section entries that concern the now-deleted SPA (they reference deleted files); keep any that are backend-relevant (e.g. auth-callback error-path tests still apply to `backend/app/api/auth.py`). Add one new item: **DEPLOY-03 (backend image versioning)** — until PLAN-037, backend was hand-pinned to `d4c8961`; now `IMAGE_TAG=<sha>` pins backend+nginx atomically per release — confirm this is the desired model (vs. per-service pins) after the first PLAN-037 release.

**Step 4:** Archive the completed cockpit plan:
```bash
git mv docs/PLAN_036_cockpit_admin_auth.md docs/archive/
```

**Step 5: Commit**
```bash
git add -A
git commit -m "docs: retire standalone admin console, close DEPLOY-01, archive PLAN-036 (PLAN-037)"
```

---

## Verification

Automated checks (this plan changes CI + compose + deletes a UI app — no backend/pytest logic touched; the full suite still runs as a regression guard).

1. **Repo compose == live intent:** `docker-compose.prod.yml` has no `admin:` service, no `COOKIE_DOMAIN`/`ADMIN_URL`, has `COCKPIT_AUTH_ENABLED`/`COCKPIT_JWKS_URL`, backend+nginx on `${IMAGE_TAG:-latest}`.
2. **No dangling admin references:** `grep -rn "admin/" docker-compose.prod.yml .github/workflows/deploy.yml` → none; `ls admin/` → absent; `git grep -n "rcn-admin\|admin.rcn-scout" -- ':!docs/archive'` → none outside archived plans.
3. **Compose validity:** `IMAGE_TAG=test docker compose -f docker-compose.prod.yml config -q` exits 0.
4. **deploy.yml sanity:** contains the scp step, `set -euo pipefail`, `export IMAGE_TAG`, the per-service digest assertion, and a `tag` id step in the deploy job; no `admin` in build or pull.
5. **Full backend suite (regression):** `docker compose run --rm backend pytest tests/ -q` → all pass (host port 8002 taken by an unrelated container — use `run --rm`, never port-bind).
6. **Frontend prod image still builds:** `docker build -f frontend/Dockerfile -t rcn-nginx-verify frontend` → success (admin removal must not affect the public app).

### Deploy + live verification (orchestrator, after merge to main)
7. Cut a release (`gh release create`) → the fixed workflow builds nginx+backend, scp's the aligned compose, deploys with `IMAGE_TAG=<sha>`, the **digest gate passes** (proves a real deploy), `/health` 200.
8. **Post-deploy live checks:** public site `https://rcn-scout.d2x-labs.de/` 200 + fresh `Last-Modified`; cockpit still reads rcn users+models (RS256 path intact — backend env unchanged); `admin.rcn-scout.d2x-labs.de` returns no rcn admin app (subdomain retired); backend still private (no Traefik/ports).

## Out of Scope
- **Backend image versioning model** (per-service pin vs. global `IMAGE_TAG`) beyond adopting `IMAGE_TAG=<sha>` — flagged as backlog DEPLOY-03 for confirmation after the first release.
- The **d2x-control-plane / cockpit side** (its own repo/plans, e.g. "PLAN_007 Stage E").
- Any change to backend Python, the cockpit auth logic, or the JWKS/issuer/audience values (all verified correct live).
- Removing the benign PWA `role==='admin'` UI gates (legitimate, kept).

---

## Plan Review
<!-- dglabs.agent.review-plan — 2026-07-23 -->

### Self-Review Gate (Pass 0)
- [x] 1. Placeholder scan — no TODO/FIXME/XXX/TBD/placeholder in plan body.
- [x] 2. Dropped-field orphan scan — no renames/drops within the plan; no stale identifiers.
- [x] 3. Line-anchor freshness — all verified against actual files: `admin:` at lines 62-76 ✓, `COOKIE_DOMAIN` at line 34 ✓, `ADMIN_URL` at line 35 ✓, admin build step lines 49-57 ✓, `pull … admin` at line 74 ✓, `d2x-internal` alias at lines 41-44 ✓, network external declaration at lines 85-86 ✓.
- [x] 4. Test-count consistency — no test-count claims.
- [x] 5. Deleted-class caller check — `admin/` directory not referenced in dev `docker-compose.yml` (confirmed); only referenced in `docker-compose.prod.yml` (Task 1) and `deploy.yml` (Tasks 2+3), both targeted. No frontend imports from `admin/`. PWA `role==='admin'` guards are benign and kept.
- [x] 6. Mirror-reference verification — no Mirror instructions.
- [x] 7. Convention contradictions — Tasks 1/2 are independent; Task 3 depends on both; contracts are consistent across tasks.

### Structural Checklist (Pass 1.A)
- [x] Required sections present (Context & Goal, Breaking Changes in intro, Tasks 1-4, Verification)
- [x] Step status markers — all tasks have `[ ]`
- [x] Step granularity — each task is scoped for a single agent pass; Tasks 1+2 are independent, Task 3+4 explicit dependencies
- [x] Test files — no new test files; Verification items 5+6 name exact commands
- [x] Breaking changes — explicitly "No live impact" with justification
- [x] BREAK markers — none (correct default for this non-interactive CI/compose plan)

### 🔴 Blocking
1. [Agent] **Task 3 Step 2 — `tag` step YAML absent and placement language ambiguous** (FIXED IN PLAN): The original Step 2 showed only Checkout + scp-action YAML while Step 3 said to "re-add the short-SHA step at the top" — which conflicted with Step 2's own "first steps" instruction and left the YAML unspecified for a fresh implementer. Without the explicit `id: tag` step before the ssh-action step, `${{ steps.tag.outputs.sha }}` evaluates empty; `export IMAGE_TAG=""` causes `docker image inspect "...nginx:"` to fail (loudly, not silently). **Fix applied:** Step 2 now shows all three steps to add in order (Checkout → scp-action → Generate short SHA tag) with full YAML and an explanation of why `tag` must live in the deploy job (`steps.*` context is job-local; `GITHUB_SHA` is globally available for the same slice).

### 🟡 Non-Blocking
1. [AI-Review] **`export IMAGE_TAG` in SSH session is transient — VPS `.env` not updated.** After deploy, `IMAGE_TAG` in `/opt/rcn-scout/.env` remains empty; a subsequent manual `docker compose up` on the VPS would use `${IMAGE_TAG:-latest}`, pulling `latest` instead of the deployed SHA. The plan correctly pre-acknowledges this as backlog DEPLOY-03. Acceptable for a single-user hobby project where all deploys go through the fixed CI pipeline. Mitigation if needed: add `sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${IMAGE_TAG}/" /opt/rcn-scout/.env` to the SSH script before the compose commands.

2. [AI-Review] **No workflow concurrency control.** Two overlapping `release: published` events (e.g. rapid re-publish) could race on the same VPS. For a single-author project this is theoretical. A `concurrency: group: deploy / cancel-in-progress: false` key in the `deploy` job would eliminate the risk at zero cost.

3. [AI-Review] **`curl http://localhost/health` may not route through Traefik to the new service.** Traefik matches by `Host:` header; `curl http://localhost/health` sends `Host: localhost`, which does not match `rcn-scout.d2x-labs.de`. In practice this likely hits Traefik's default backend (the previous running service), making the health check a pure aliveness probe rather than a version-validated one. The **digest gate** (added by Task 3) is the reliable deploy validator; the curl is a secondary "something is listening" guard. Acceptable. A more precise check would use `-H "Host: rcn-scout.d2x-labs.de" http://localhost/health` or the public URL.

4. [AI-Review] **Digest gate uses hard-coded container naming convention** `rcn-scout-${svc}-1`. This relies on Docker Compose v2's default naming: `<project_name>-<service>-<index>`, where project name = directory basename = `rcn-scout`. Safe given the VPS directory is `/opt/rcn-scout` and the compose file has no `name:` override. If the naming ever changes, `docker compose -f docker-compose.prod.yml ps -q "${svc}"` is the more resilient alternative.

5. [Agent] **Blank line residue after admin block deletion.** Deleting lines 62-76 leaves two adjacent blank lines (line 61 after nginx's `networks:`, line 77 before `volumes:`). Cosmetic only — YAML is valid with consecutive blanks. The coder can delete one to keep clean formatting.

6. [Agent] **Task 2 Step 3 uses `git add -A`.** Global CLAUDE.md discourages `git add -A` (risk of accidentally staging secrets). In this context (only `admin/` deletions + `deploy.yml` modification in flight), the risk is nil. Acceptable as-is; can be replaced with `git rm -r admin/ && git add .github/workflows/deploy.yml` for strict compliance.

### Verdict
APPROVED — one blocking issue (missing `tag` step YAML in Task 3) fixed directly in the plan; all codebase facts verified correct; deploy safety logic (scp sync, digest gate, `set -euo pipefail`) is sound for the project's scale.
