# PLAN 018 — Dynamic Free-Tier LLM Cascade

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved (after revise) | 2026-04-15 |
| Human    | approved | 2026-04-15 |

## Implementation Status (pre-review draft already in repo)

Parts of this plan exist as uncommitted working-tree changes (drafted
during the discussion phase). The plan still lists them as steps for
clarity; status fields below indicate what is done vs open. Any
implementer MUST reconcile with the working tree, not re-create.

| Step | Status | Location |
|------|--------|----------|
| 1 DB migration | partially-implemented, needs `is_active` column added | `backend/app/db.py` |
| 2 model_cascade.py | implemented (draft) | `backend/app/analysis/model_cascade.py` |
| 3 extractor wiring | implemented (draft) | `backend/app/analysis/extractor.py` |
| 4 scheduler seed | partially-implemented, `add_job` missing | `backend/app/main.py` |
| 5 admin endpoint | open | `backend/app/api/admin.py` (new), `deps.py` (needs `require_admin`) |
| 6 frontend panel | open | `frontend/src/components/LLMAdminPanel.tsx` (new) |
| 7 tests | open | `backend/tests/test_model_cascade.py` (new), extend existing |

## Context & Goal

**Problem.** The analysis pipeline currently pays ~0.13 €/day because the
configured primary model (`qwen/qwen3-30b-a3b:free`) no longer exists on
OpenRouter, so every call falls through to the paid fallback
(`mistralai/mistral-nemo`). The `OPENROUTER_MODEL` env var is static —
OpenRouter adds/renames/removes free models weekly, so a static list goes
stale without us noticing.

**Goal.** Replace the single-primary + single-fallback with a **DB-backed
cascade of free-tier models** that self-refreshes every 12 h from OpenRouter's
`/v1/models` endpoint. On each `analyze_listing()` call the cascade is tried
in order; repeatedly-failing models auto-disable for 1 h. The paid
`mistralai/mistral-nemo` stays as the last-resort safety net via `.env`
(never tracked in DB).

Admin-role users get a small panel in their profile that shows the live
cascade state: which models are active, which are temporarily disabled,
last refresh timestamp, recent errors.

## Breaking Changes

**No** — the public interface of `analyze_listing()` is unchanged. The env
vars `OPENROUTER_MODEL` / `OPENROUTER_FREE_MODELS` become **seed values**
for the DB on first boot; after that the DB is the source of truth.
`OPENROUTER_FALLBACK_MODEL` in `.env` keeps its role as paid safety-net
exactly as today.

Old rows / configs keep working: if the DB table is empty (e.g. fresh
checkout), the startup seed populates it from env. No data migration
needed for listings.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  OpenRouter API — /v1/models                                         │
└────────────────┬─────────────────────────────────────────────────────┘
                 │ 12h cron (AsyncIOScheduler)
                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  model_cascade.refresh_from_openrouter()                             │
│    - filter: price==0 + structured_outputs + not aggregator          │
│    - sort by created DESC, take top N (default 4)                    │
│    - upsert into llm_models (preserve failure counters for survivors)│
│    - delete models no longer in top-N                                │
│    - detailed log: added / kept / removed                            │
└────────────────┬─────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Postgres: llm_models                                                │
│    model_id PK, position, is_active, disabled_until,                 │
│    consecutive_failures, last_error, created_at, last_refresh_at ... │
└────────────────┬─────────────────────────────────────────────────────┘
                 │
    ┌────────────┴───────────────┐
    │                            │
    ▼                            ▼
┌───────────────────┐      ┌─────────────────────────────────────────┐
│ extractor.py      │      │ GET /api/admin/llm-models               │
│ analyze_listing() │      │   role=admin only                        │
│  - load cascade   │      │   returns full DB rows for UI           │
│  - try each       │      └─────────────┬───────────────────────────┘
│  - record success │                    │
│    / failure      │                    ▼
│  - paid fallback  │      ┌─────────────────────────────────────────┐
│    (env, no DB)   │      │ ProfilePage → <LLMAdminPanel />          │
└───────────────────┘      │  table: model | active | last error |   │
                           │          disabled_until | ctx            │
                           └──────────────────────────────────────────┘
```

## Data Model

```sql
CREATE TABLE llm_models (
    model_id              TEXT PRIMARY KEY,           -- openrouter model id
    position              INTEGER NOT NULL,           -- cascade order, lower = tried first
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,  -- clear AKTIV indicator
    context_length        INTEGER,
    created_upstream      TIMESTAMPTZ,                -- openrouter's created_at
    added_at              TIMESTAMPTZ NOT NULL DEFAULT now(),  -- first seen by us
    last_refresh_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    disabled_until        TIMESTAMPTZ,                -- if set + future, temporarily skipped
    last_error            TEXT
);
CREATE INDEX ix_llm_models_position ON llm_models (position);
```

**Two orthogonal "off" flags:**
- `is_active = FALSE` → permanently off (admin toggle, future feature; not writable yet from UI in this plan)
- `disabled_until > now()` → temporarily off (automatic, 1 h after 3 consecutive failures)

A model is **considered active for cascade** when `is_active = TRUE AND
(disabled_until IS NULL OR disabled_until < now())`.

## Failure & Recovery Policy

- **Failure** = `_try_analyze` returns `None` (structured-output *and*
  JSON-fallback both failed — covers 404/410/429/500/invalid JSON/timeout).
- 3 consecutive failures → `disabled_until = now() + 1h`,
  `consecutive_failures = 3`, `last_error` stored (500 chars max).
- Success resets `consecutive_failures = 0`, `disabled_until = NULL`,
  `last_error = NULL`.
- After 1 h the model re-enters the cascade automatically. If it fails
  again immediately, it gets disabled for another hour (counter keeps
  climbing).
- The 12 h refresh **preserves** `consecutive_failures` and
  `disabled_until` for models that survive the refresh — a flaky model
  doesn't get a free pass just because upstream still lists it.

## Configuration (env)

```
# Existing — becomes the seed list on first boot
OPENROUTER_FREE_MODELS=qwen/qwen3-next-80b-a3b-instruct:free,...

# Existing — paid last-resort, stays in env, never in DB
OPENROUTER_FALLBACK_MODEL=mistralai/mistral-nemo

# New — optional tuning knobs
LLM_CASCADE_TOP_N=4                  # how many free models to keep
LLM_CASCADE_FAILURE_THRESHOLD=3      # strikes before disable
LLM_CASCADE_DISABLE_HOURS=1          # how long a disable lasts
LLM_CASCADE_REFRESH_HOURS=12         # how often to refresh from OpenRouter
```

## Logging

All scheduler + cascade events go to the `app.analysis.model_cascade`
logger at `INFO`. Sample output the user should see on startup +
each refresh:

```
INFO app.analysis.model_cascade: seeded 4 models from env
INFO app.analysis.model_cascade: refresh starting — top_n=4
INFO app.analysis.model_cascade: upstream returned 248 models, 7 eligible (free + SO + non-aggregator)
INFO app.analysis.model_cascade: refresh done
  added   = ['nvidia/nemotron-3-super-120b-a12b:free']
  kept    = ['qwen/qwen3-next-80b-a3b-instruct:free', 'nvidia/nemotron-nano-9b-v2:free']
  removed = ['arcee-ai/trinity-large-preview:free']
INFO apscheduler.executors.default: Job "llm_cascade_refresh" executed successfully
```

Per-call tracking logs (already present, formatted):

```
INFO app.analysis.extractor: LLM analyze: id=3574 "Multiplex Easy Glider" — cascade=['qwen/...', 'nvidia/...']
WARNING app.analysis.extractor: LLM [qwen/qwen3-next-80b-a3b-instruct:free] structured-output: RateLimitError — trying JSON fallback
WARNING app.analysis.extractor: LLM [qwen/...] json-fallback: RateLimitError
WARNING app.analysis.extractor: LLM [qwen/...] exhausted — next in cascade
INFO app.analysis.extractor: LLM SUCCESS [nvidia/nemotron-3-super-120b-a12b:free]: id=3574 "Multiplex Easy Glider"
```

When a model crosses the failure threshold:

```
WARNING app.analysis.model_cascade: DISABLE [qwen/qwen3-next-80b-a3b-instruct:free]
  — consecutive_failures=3, disabled_until=2026-04-15T21:43:00+00:00, last_error=RateLimitError: 429
```

## Admin UI

**Backend — new endpoint:**

```
GET /api/admin/llm-models
Auth: role=admin (existing auth middleware)
Response: [
  {
    "model_id": "qwen/qwen3-next-80b-a3b-instruct:free",
    "position": 0,
    "is_active": true,
    "active_now": true,        // is_active AND not currently disabled
    "context_length": 262144,
    "created_upstream": "2025-09-11T…",
    "added_at": "2026-04-15T…",
    "last_refresh_at": "2026-04-15T…",
    "consecutive_failures": 0,
    "disabled_until": null,
    "last_error": null
  },
  ...
]
```

**Frontend — new component** `components/LLMAdminPanel.tsx`, shown in
`ProfilePage` only when `user.role === 'admin'`:

- Table: model_id, active badge (green/red/amber-for-disabled-until),
  last_error truncated, disabled_until countdown if set,
  context length, last_refresh_at relative ("vor 3 h").
- Header: "Letzte Aktualisierung: vor X Min."
- Refresh button → POST `/api/admin/llm-models/refresh` (admin-only,
  triggers `refresh_from_openrouter()` immediately). Returns the same
  shape as GET; UI updates in place.

## Files to Create / Modify

**Create:**
- `backend/app/analysis/model_cascade.py` — DB ops, refresh, failure tracking
- `backend/app/api/admin.py` — `/api/admin/llm-models` (GET + POST refresh)
- `frontend/src/components/LLMAdminPanel.tsx` — admin UI panel

**Modify:**
- `backend/app/db.py` — `CREATE TABLE llm_models` + **`ADD COLUMN IF NOT EXISTS is_active`**
- `backend/app/api/deps.py` — add `require_admin` dependency that wraps
  `get_current_user` and raises 403 when `user.role != "admin"`
- `backend/app/config.py` — add `LLM_CASCADE_*` tuning knobs,
  drop obsolete `OPENROUTER_MODEL` (seed via `OPENROUTER_FREE_MODELS`)
- `backend/app/analysis/extractor.py` — load cascade from DB,
  record success/failure, paid fallback unchanged
- `backend/app/main.py` — seed on startup + 12 h refresh scheduler job
- `backend/app/api/routes.py` — mount admin router
- `frontend/src/pages/ProfilePage.tsx` — mount `<LLMAdminPanel />`
  when `user.role === 'admin'`
- `frontend/src/api/client.ts` — `getLLMModels()`, `refreshLLMModels()`

## Steps

Each step has a status field. Allowed values: `open | implemented |
reviewed | approved`. Implementer updates the field as work progresses.

1. **DB schema** — `status: partially-implemented`
   - Add `llm_models` table in `init_db()` (already in repo, lines 131–148).
   - **MISSING:** `ALTER TABLE llm_models ADD COLUMN IF NOT EXISTS
     is_active BOOLEAN NOT NULL DEFAULT TRUE` — append inside `init_db()`
     following the existing idempotent-ALTER pattern used elsewhere in
     that function.

2. **`model_cascade.py`** — `status: implemented (draft, uncommitted)`
   - DB read/write helpers: `load_cascade()` (60 s in-process cache),
     `record_success(model_id)`, `record_failure(model_id, error)`,
     `refresh_from_openrouter(top_n)`, `seed_if_empty()`,
     `refresh_job()` (APScheduler entry point).
   - All writes log the resulting state.
   - **Refinement (non-blocking):** widen pricing zero-check in
     `_filter_upstream` from `in ("0", 0)` to `float(v) == 0.0`
     inside a try/except, to absorb upstream format drift
     ("0.0" / float) without wiping the cascade.
   - **Refinement (non-blocking):** when a model crosses the failure
     threshold, log `WARNING DISABLE [<model_id>] — consecutive_failures=N,
     disabled_until=…, last_error=…` so it appears cleanly in scheduler
     logs (not only the per-call WARN from extractor).

3. **Extractor wiring** — `status: implemented (draft, uncommitted)`
   - `analyze_listing()` reads cascade from `model_cascade.load_cascade()`.
   - After each `_try_analyze`, calls `record_success` or `record_failure`.
   - Paid fallback path untouched (env only).

4. **Scheduler + startup seed** — `status: partially-implemented`
   - Call `model_cascade.seed_if_empty()` after `init_db()` (already in repo).
   - **MISSING:** register the 12 h refresh job in the scheduler:
     ```python
     from datetime import datetime
     scheduler.add_job(
         model_cascade.refresh_job,
         trigger="interval",
         hours=12,
         id="llm_cascade_refresh",
         next_run_time=datetime.utcnow(),  # run once on boot with live data
         replace_existing=True,
     )
     ```
   - Update the "Scheduler started" log line to include the new job.

5. **Admin endpoint + role guard** — `status: open`
   - `backend/app/api/deps.py`: add `require_admin` dependency that
     depends on `get_current_user` and raises HTTP 403 when
     `user.role != "admin"`.
   - `backend/app/api/admin.py` (new):
     - `GET /api/admin/llm-models` — list all rows + computed
       `active_now = is_active AND (disabled_until IS NULL OR
       disabled_until < now())`
     - `POST /api/admin/llm-models/refresh` — trigger
       `refresh_from_openrouter()`, return the same shape as GET
     - Both guarded by `Depends(require_admin)`.
   - Mount in `routes.py` under `/api/admin`.

6. **Frontend admin panel** — `status: open`
   - `LLMAdminPanel.tsx` with table + refresh button.
   - Columns: model_id, aktiv badge (green/red/amber-for-disabled-until),
     last_error (truncated, tooltip for full), disabled_until countdown
     if set, context_length, last_refresh_at relative.
   - Header: "Letzte Aktualisierung: vor X Min."
   - Refresh button → `refreshLLMModels()`; updates table in place.
   - Mount conditionally in `ProfilePage` when `user.role === 'admin'`.
   - Styling: aurora glass (rgba(15,15,35) surface, rgba(255,255,255,0.08)
     borders, #A78BFA active, #EC4899 disabled/error).
   - API client: `getLLMModels()`, `refreshLLMModels()` in `api/client.ts`.

7. **Tests** — `status: open`
   - See "Test files" section below.

## Test files

- `backend/tests/test_model_cascade.py` — covers:
  - `_filter_upstream` respects pricing / SO / aggregator rules
  - `_filter_upstream` handles pricing strings `"0"`, `"0.0"`, int `0`, float `0.0`
  - `refresh_from_openrouter` preserves failure counters for kept models
  - `refresh_from_openrouter` with upstream returning zero eligible →
    existing rows preserved (no wipe)
  - `record_failure` disables after threshold
  - `record_failure` invalidates the in-process cache
  - `record_success` clears disable state and counter
  - `load_cascade` excludes disabled rows
  - `seed_if_empty` is a true no-op when table is non-empty
- `backend/tests/test_analysis_job.py` — **existing**, extend with:
  - cascade exhaustion falls through to paid fallback
  - empty cascade goes straight to paid fallback
- `frontend/src/components/__tests__/LLMAdminPanel.test.tsx` — shallow
  render with mock data, verify refresh button calls the API.

## Verification

Run after implementation:

```bash
# 1. Backend rebuild & start
docker compose up -d --build backend
docker compose logs -f backend | head -40
# Expect:
#   "Database initialised"
#   "model_cascade: seeded 4 models from env"
#   "model_cascade: refresh starting — top_n=4"
#   "model_cascade: refresh done — added=[...] kept=[...] removed=[...]"
#   "Scheduler started — ... llm_cascade_refresh every 12h"

# 2. DB contents
docker compose exec db psql -U rcscout -d rcscout -c \
  "SELECT model_id, position, is_active, consecutive_failures, disabled_until FROM llm_models ORDER BY position"

# 3. Admin endpoint (use admin JWT)
curl -s -b "session=$ADMIN_JWT" http://localhost:8002/api/admin/llm-models | jq .

# 4. Run backend tests
docker compose exec backend pytest tests/test_model_cascade.py tests/test_analysis_job.py -v

# 5. Manually simulate a failure (psql), reload cascade, verify exclusion
docker compose exec db psql -U rcscout -d rcscout -c \
  "UPDATE llm_models SET disabled_until = now() + interval '1 hour' WHERE position = 0"
docker compose exec backend python -c "
import asyncio
from app.analysis import model_cascade
print(asyncio.run(model_cascade.load_cascade()))"
# Expect: first model missing from the returned list

# 6. Manual refresh via admin endpoint
curl -s -X POST -b "session=$ADMIN_JWT" \
  http://localhost:8002/api/admin/llm-models/refresh | jq .

# 7. Frontend — login as admin, open /profile,
#    verify LLM Admin panel renders, matches DB state, refresh button works
```

## Assumptions & Risks

- **Assumption:** OpenRouter `/v1/models` response shape stays stable
  (documented fields `pricing`, `supported_parameters`, `context_length`,
  `created`). Acceptable: any upstream shape change surfaces as a
  refresh failure, logged clearly; cascade keeps running on last
  known-good state.
- **Note (by design, not a bug):** `load_cascade()` uses a 60 s
  in-process cache per backend worker. After a `refresh_from_openrouter`
  commit, other workers may continue to serve the pre-refresh list for
  up to 60 s before their cache TTL expires. Single-worker dev env sees
  immediate effect because `record_failure` invalidates the local cache
  and `refresh_from_openrouter` does too.
- **Risk:** Upstream briefly returns 0 eligible models (e.g. API hiccup).
  Mitigation: `refresh_from_openrouter` aborts with a logged warning
  and does **not** wipe the existing table. Cascade stays intact.
- **Risk:** All 4 free models rate-limit simultaneously at peak scrape.
  Mitigation: paid fallback (`mistral-nemo`) via env catches it.
  Cost is bounded because by the time the third free model fails for
  the 3rd time in a row, it's disabled for an hour — no endless retries.
- **Latency risk:** During a 4-free-all-rate-limited window, a single
  `analyze_listing` call can take up to ~2 min
  (4 models × 2 attempts × 15 s timeout) before reaching the paid
  fallback. The 3-strikes-1-hour disable rule caps this at 3 calls
  per model before they drop out of the cascade, so the tax is bounded
  to ~12 slow calls total per hour-long upstream incident.
- **Risk:** Admin panel exposes `last_error` strings that could contain
  sensitive upstream data. Mitigation: already truncated to 500 chars;
  admin-only endpoint; this is a private-single-user app.

## Out of Scope

- Admin-toggle for `is_active` (manual override via UI). The column
  exists so we can add this later; for now it's always set to `TRUE`
  on insert and not written by any runtime code path.
- Per-listing analytics of which model produced a given result.
- Model cost tracking. OpenRouter's dashboard already shows this.

## Reviewer Notes

**Reviewer (plan-reviewer agent, 2026-04-15, gpt + heuristic review):**
Verdict ⚠️ REVISE → fixed. Four blocking gaps were identified:
1. `is_active` column present in plan text but missing in the drafted
   `db.py` migration → added as `ALTER TABLE ... ADD COLUMN IF NOT
   EXISTS is_active` in step 1.
2. 12 h APScheduler `add_job(...)` was not registered in `main.py` →
   step 4 now explicitly requires it with the concrete snippet.
3. No `require_admin` dependency exists in `deps.py` → added to
   "Files to Modify" and to step 5.
4. Steps lacked status fields → every step now has an explicit
   `status:` line.

Non-blocking refinements folded in: widened pricing zero-check,
explicit DISABLE log, extra test cases, latency risk noted,
cache-TTL-by-design noted, `active_now` computation spelled out.

Codex second-opinion pass was attempted but did not complete within
the review window; low risk because the primary review covered both
design and code-path verification against the repo.
