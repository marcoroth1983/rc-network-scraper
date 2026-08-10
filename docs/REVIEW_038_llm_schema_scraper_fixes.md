# Review — PLAN_038 LLM-Schema, Scraper-Robustheit und Backfill

Plan: [`PLAN_038_llm_schema_scraper_fixes.md`](PLAN_038_llm_schema_scraper_fixes.md)

_Reviews append here, newest last. The plan file carries no review content._

---

## Plan Review — cycle 1
<!-- dglabs.agent.review-plan — 2026-08-10 -->

### Self-Review Gate (Pass 0)

- [x] 1. Placeholder scan — zero TODO/FIXME/XXX/TBD matches in plan body
- [x] 2. Dropped-field orphan scan — no stale old-name references; `_ListingAnalysisWire` introduced cleanly
- [x] 3. Line-anchor freshness — all anchors verified against live files:
  - `extractor.py:69-71` ✓ (attributes prompt), `:78` ✓ (`_DRIVE_TYPES`), `:81-99` ✓ (`ListingAnalysis`), `:138-152` ✓ (parse call), `:146` ✓ (`response_format=ListingAnalysis`), `:155` ✓ (`except Exception`), `:177` ✓ (`model_validate_json`)
  - `parser.py:188-205` ✓ (`_extract_images`), `:196` ✓, `:201` ✓
  - `FilterPanel.tsx:361` ✓ (`z-20` sticky header), `:69` ✓ (backdrop `z-40`), `:82` ✓ (sheet `z-50`)
  - `ListingCard.tsx:127` ✓ (`z-20` star button)
  - `routes.py:331` ✓, `job.py:61` ✓, `backfill.py:77` ✓
- [x] 4. Test-count consistency — 4 (Task 1) + 3 (Task 2) = 7 backend tests; matches Verification claim
- [x] 5. Deleted-class caller check — no symbols deleted; n/a
- [x] 6. Mirror-reference verification — no Mirror instructions; n/a
- [x] 7. Convention contradictions across tasks — `_ListingAnalysisWire` / `to_analysis()` contract is used consistently in Tasks 1, 3 (JSON fallback), and the new tests
- [x] 8. Reachability — module edges verified

| task | lands in | must call | edge legal? |
|---|---|---|---|
| Task 1 | `backend/app/analysis/extractor.py` | `pydantic.BaseModel`, `pydantic.ValidationError`, `app.analysis.vocabulary` | Yes |
| Task 2 | `backend/app/scraper/parser.py` | `urllib.parse.urljoin`, `logging` (already imported at line 12) | Yes |
| Task 3 | `frontend/src/components/FilterPanel.tsx` | Tailwind CSS class change only | Yes |
| Task 4 | Production DB (psql via SSH) | `rcn-scout-db-1` container | Yes |
| Task 5 | Production (deploy + backfill script) | `app.analysis.backfill`, `ghcr.io` image | Yes |

Pass-0 gate: **8/8 pass** — all checks clear.

---

### Structural Checklist (Pass 1.A)

- [x] Required sections present (Context & Goal, Breaking Changes, Tasks, Verification)
- [x] Step status markers — all tasks carry `[ ]`
- [x] Step granularity — each task is self-contained and within the agent context-size limits
- [x] Test files named per step — `test_extractor.py` (Task 1), `test_parser.py` (Task 2)
- [x] Breaking changes explicitly marked — "No" with explanation
- [x] BREAK markers — one BREAK before Task 5, justified (irreversible scale + paid API); zero elsewhere

---

### 🔴 Blocking

**1. [Agent] — `extractor.py` / `test_extractor.py` — Two existing tests break after Step 2 changes the parse path**

After Task 1, Step 2 replaces the parse result handling with `parsed.to_analysis()`, the two existing tests that mock `parsed` as a `ListingAnalysis` instance will raise `AttributeError: 'ListingAnalysis' object has no attribute 'to_analysis'`:

- `test_valid_structured_response_returns_correct_analysis` (line 89): builds `expected = ListingAnalysis(...)` and passes it as `mock_parse`'s return value. After the fix the code calls `expected.to_analysis()` — `ListingAnalysis` has no such method.
- `test_model_override_is_passed_to_client` (line 237): same pattern — `expected = ListingAnalysis(manufacturer="Robbe", ...)`.

The plan instructs *adding* four new tests but says nothing about updating these two existing ones. Because the test suite is run as the verification gate (`pytest tests/ -v` must pass), the implementation cannot reach a green state without fixing them. Both tests must be updated to mock a `_ListingAnalysisWire` instance instead of a `ListingAnalysis` instance, e.g.:

```python
expected_wire = _ListingAnalysisWire(manufacturer="Black Horse", model_name="L-39 Albatros",
    drive_type="electric", model_type="airplane", model_subtype="jet", completeness="ARF",
    attributes=[_AttributePair(key="wingspan_mm", value="1700"), _AttributePair(key="weight_g", value="3500")])
mock_parse = AsyncMock(return_value=_make_parse_response(expected_wire))
```

The test assertions remain the same (checking `.manufacturer`, `.attributes == {"wingspan_mm": …}`, etc.) because `to_analysis()` produces a `ListingAnalysis` with the expected values.

**2. [AI-Review] — `test_parser.py` Task 2, Step 3 — Malformed-URL test fixture does not trigger the crash**

The proposed test uses `src="https://example.com/[V] broken.jpg"`. In Python's `urllib.parse.urlsplit`, an unmatched `[` in the **path** segment does not raise `ValueError: Invalid IPv6 URL`. The error only fires when `[` appears in the **netloc** (authority) position. The production crash on listing 12131203 was caused by a src whose authority part was malformed.

The test would pass even without the guard (because `urljoin` wouldn't raise), so it gives false confidence that the fix works. The fixture must place the bracket in the netloc, e.g.:

```python
src = "//[V] OMP broken.jpg"   # or "//[invalid_host/path.jpg"
```

Confirm the chosen input triggers `ValueError` before writing the assertion:

```python
import pytest
from urllib.parse import urljoin
with pytest.raises(ValueError):
    urljoin("https://rc-network.de/t/1/", "//[V] OMP broken.jpg")
```

---

### 🟡 Non-Blocking

**1. [Agent] — `test_extractor.py` — Missing import additions**

The four new tests reference `_ListingAnalysisWire` and `_AttributePair`, which are not in the current import line (`from app.analysis.extractor import ListingAnalysis, analyze_listing`). The plan does not mention adding them. A fresh coder agent following the plan verbatim will hit `NameError`. The import line needs expanding to include `_ListingAnalysisWire, _AttributePair`.

**2. [Agent] — `test_parser.py` — Missing import additions**

The three new parser tests call `_extract_images(post, page_url=…)` and construct `BeautifulSoup(html, "html.parser")` directly. Neither `_extract_images` nor `BeautifulSoup` appears in the current imports (`from app.scraper.parser import parse_detail`). The plan must add: `from app.scraper.parser import _extract_images` and `from bs4 import BeautifulSoup`.

**3. [AI-Review] — Task 4 — Destructive reset runs before the BREAK that guards irreversible production writes**

The BREAK is placed before Task 5. Task 4 (nullifying analysis columns for all active analyzed rows) is itself an irreversible production write and runs without Human approval. The rows could be backed up first (`SELECT id, manufacturer, ... INTO TEMP TABLE before_reset`) or the BREAK could be moved to cover both Task 4 and Task 5. Low impact (≤ 16 rows, no cost), but inconsistent with the stated BREAK rationale.

**4. [AI-Review] — Task 5, Step 1 — Frontend z-index change (Task 3) is not covered by the backend deploy**

The deploy step pulls and recreates only the backend container. If the frontend is served from a separate build artifact (the Vite output), the z-index change is never deployed, yet the Verification section requires a manual mobile check of the sticky-header fix. The plan must reference the frontend build/publish step or confirm the frontend is served from the same container.

**5. [AI-Review] — Task 5, Step 1 — Release tag not specified**

"Follow the project's existing release path" is underspecified for a fresh agent. The exact `docker build`, `docker push`, and tag (commit SHA or release version) are not shown. A stale image could be pulled instead of the one containing Tasks 1–2. The concrete build/push commands should be included or cross-referenced.

**6. [Agent/AI-Review] — Task 5, Step 3 — Detached backfill has no exit-code capture**

`docker exec -d` discards the process exit code. If the backfill crashes mid-run, `tail -3 /tmp/backfill.log` will show the last log line before the crash and may not contain the expected "Backfill complete" line, but the plan provides no explicit failure path for this case. A concrete "if the completion line does not appear within N minutes, inspect the full log and stop" instruction is missing.

---

### Verdict

REVISE — 2 blocking issues: existing tests that will fail at verification (Agent finding 1) and a test fixture that does not exercise the actual crash path (AI-Review finding 2). Both require targeted additions/corrections to the plan before implementation can reach a green test run.

---

## Plan Review — cycle 2
<!-- dglabs.agent.review-plan — 2026-08-10 -->

### Self-Review Gate (Pass 0)

- [x] 1. Placeholder scan — zero TODO/FIXME/XXX/TBD matches in plan body
- [x] 2. Dropped-field orphan scan — Task 1 steps renumbered from 4→7: new Steps 5 (update existing tests), 6 (write tests), 7 (commit). No stale "Step 4" cross-references remain; commit messages and test-file references are correct throughout.
- [x] 3. Line-anchor freshness — all plan-cited line anchors still valid:
  - `test_extractor.py:91` → `expected = ListingAnalysis(` ✓
  - `test_extractor.py:239` → `expected = ListingAnalysis(manufacturer="Robbe", …)` ✓
  - `deploy.yml:89-92` → staleness check loop (`for svc in nginx backend; do …`) ✓
  - `extractor.py:146` → `response_format=ListingAnalysis` ✓
  - `parser.py:188` → `def _extract_images(post: Tag, page_url: str = "") -> list[str]:` ✓
- [x] 4. Test-count consistency — Task 1 Step 6: 4 new tests; Task 2 Step 3: 4 new tests; 2 existing tests updated. Verification section says "8 new, 2 changed" — consistent.
- [x] 5. Deleted-class caller check — no symbols deleted; n/a
- [x] 6. Mirror-reference verification — no Mirror instructions; n/a
- [x] 7. Convention contradictions across tasks — `_ListingAnalysisWire` / `to_analysis()` contract is consistently applied in Steps 2, 3, 5, 6 (Task 1) and the JSON-fallback (Step 3). All four new tests use the wire model.
- [x] 8. Reachability — all task edges legal (identical to cycle 1; no new imports or targets added)

| task | lands in | must call | edge legal? |
|---|---|---|---|
| Task 1 | `backend/app/analysis/extractor.py` | `pydantic.BaseModel`, `pydantic.ValidationError`, `app.analysis.vocabulary` | Yes |
| Task 2 | `backend/app/scraper/parser.py` | `urllib.parse.urljoin`, `logging` (module-level logger exists at line 12) | Yes |
| Task 3 | `frontend/src/components/FilterPanel.tsx` | Tailwind CSS class change only | Yes |
| Task 4 | Production DB (psql via SSH) | `rcn-scout-db-1` container | Yes |
| Task 5 | Production (deploy + backfill script) | `app.analysis.backfill`, `ghcr.io` | Yes |

Pass-0 gate: **8/8 pass** — all checks clear.

---

### Structural Checklist (Pass 1.A)

- [x] Required sections present
- [x] Step status markers — all `[ ]`
- [x] Step granularity — each task self-contained; Task 1 stays within context limits after adding Step 5
- [x] Test files named per step — `test_extractor.py` (Task 1 Steps 5–6), `test_parser.py` (Task 2 Step 3)
- [x] Breaking changes marked — "No" with explanation
- [x] BREAK markers — moved to before Task 4, justified (both Tasks 4 and 5 are irreversible production writes)

---

### Cycle 1 Blocking Findings — Fix Verification

**Blocking 1 (test_extractor.py existing tests):** Task 1 now has Step 5, which explicitly patches `test_extractor.py:91` and `:239` to use `_ListingAnalysisWire` instead of `ListingAnalysis` as the mock's return value, and adds the expanded import block. The fix is genuine and complete.

**Blocking 2 (malformed-URL test fixture):** Task 2 Step 3 now uses `//[V] OMP broken.jpg` (netloc position) and adds `test_malformed_src_really_raises_without_the_guard`, which asserts `pytest.raises(ValueError)` against the exact fixture — making the test self-certifying. The fix is genuine and complete.

---

### Cycle 1 Non-Blocking Findings — Fix Verification

All six non-blocking findings (NB1–NB6) are addressed: import additions for both test files, BREAK moved to cover both irreversible writes, nginx/frontend deploy path documented in Task 5 Step 1, `gh release create v2.11.0` command made explicit, and `/tmp/backfill.rc` exit-code capture added with a polling instruction.

---

### Deploy Workflow Verification (specific to cycle 2 mandate)

- Trigger `release: [published]` — `deploy.yml:5` confirmed ✓
- Builds backend AND nginx image — `deploy.yml:29–47` builds both ✓
- Frontend z-index fix ships inside nginx image — `deploy.yml:39–47` (`context: ./frontend`, `Dockerfile`) ✓
- Staleness check `deploy.yml:89-92` — for-loop over `nginx backend` confirms both containers are on new tag ✓
- `IMAGE_TAG` written to VPS `.env` — `deploy.yml:83` sed-or-append ✓
- v2.11.0 is plausible — previous release is `v2.10.0` (git log `feb6788` / `920941f`) ✓

---

### 🔴 Blocking

**1. [AI-Review] `PLAN_038` — Task 4 reset runs before the deploy, recurring job re-analyzes the reset rows with the broken code during the deploy window**

Task 4 (reset 16 trial rows to `llm_analyzed=false`) happens before Task 5 Step 1 (deploy the fix). The deploy workflow typically takes 5–10 minutes. During that window the recurring analysis job (every 2 minutes, `job.py`) selects all `WHERE llm_analyzed=false` rows. It picks up the 16 freshly reset rows and re-analyzes them using the still-running broken backend, marking them `llm_analyzed=true` again via the degraded JSON-fallback path. After the deploy completes those rows are already marked analyzed, so neither the trial run (Task 5 Step 2) nor the full backfill (Task 5 Step 3) will touch them — the very rows the plan aims to re-analyze with the fixed schema are permanently excluded.

Fix: move the Task 4 reset command to between Task 5 Step 1 (deploy confirmed green) and Task 5 Step 2 (trial run). At that point the backend container is already on the fixed code, so the recurring job can only produce correct results even if it reaches the rows first.

---

### 🟡 Non-Blocking

**1. [Agent] — Task 1 Step 5 — Self-contradictory instruction note**

Step 5 says "Keep the existing field values from the file — the block above shows the shape, not the values." The block directly above shows the exact same values as the live test file (verified). The sentence is harmless since coder and file agree, but it may briefly confuse an agent about whether to trust the block or re-read the file. Suggest removing the note or rewriting as: "The values in the block match the file as of 2026-08-10; copy them verbatim."

**2. [AI-Review] — Task 5 Step 3 — `backfill.py` has no active-only filter; `--limit 2200` claim is implicit**

`backfill.py:_fetch_batch` (verified, line 31–41) queries `WHERE llm_analyzed = false` with no `is_sold` or `is_outdated` filter. The plan states "`--limit 2200` covers the ~2.079 active rows with headroom," relying on the implicit assumption that `ORDER BY scraped_at DESC` places all 2,079 active listings within the first 2,200 of 6,522 total unanalyzed rows. This is plausible (sold/outdated listings were scraped earlier) but undocumented. The plan should add a one-line note acknowledging the ordering dependency, or add `AND is_sold=false AND is_outdated=false` to `_fetch_batch` for the backfill run.

**3. [AI-Review] — Task 4 Step 1 — Reset targets all currently-active-and-analyzed rows, not just trial IDs**

The reset command uses `WHERE llm_analyzed=true AND is_sold=false AND is_outdated=false`, which wipes any rows the recurring job may have correctly analyzed since the trial. The plan says "A materially different count — continue," which could silently erase valid data. Consider adding `AND scraped_at <= '<trial-date>'` or recording the exact 16 IDs before the reset. Low impact for 16 rows, but the plan's own "stop and investigate" language doesn't apply here.

**4. [AI-Review] — Task 1 Step 3 — Dual-parse JSON fallback path not covered by tests**

Step 3 replaces the JSON fallback's single `ListingAnalysis.model_validate_json()` with a try/except that first attempts `_ListingAnalysisWire.model_validate_json().to_analysis()` and falls back to `ListingAnalysis.model_validate_json()`. The existing fallback test (`test_malformed_structured_response_falls_back_to_json_parsing`) uses dict-shaped JSON, which would now hit the `ValidationError` handler and fall through to the `ListingAnalysis` branch. No test verifies the wire-shaped JSON fallback path (pair-list JSON succeeds on the first try). A regression in the `_ListingAnalysisWire.model_validate_json()` branch would be invisible.

**5. [AI-Review] — Task 1 Step 6 — `test_wire_schema_has_no_open_ended_map` is narrower than OpenAI strict-mode requires**

The test asserts only `schema["properties"]["attributes"]["type"] == "array"`. OpenAI strict mode also requires `additionalProperties=false` on all object types and every property listed in `required`. If `_ListingAnalysisWire` is missing these (e.g., Pydantic v2 does not emit them by default without `model_config = ConfigDict(extra="forbid")`), the API will still reject it, and the test would pass despite the schema being invalid. Consider adding `model_config` enforcement or asserting `required` completeness in the test.

**6. [AI-Review] — Task 5 Step 3 — `/tmp/backfill.rc` and `/tmp/backfill.log` are not cleared before launch**

A file left from a previous trial run or aborted backfill at `/tmp/backfill.rc` would make the polling command immediately return a stale exit code, falsely indicating completion while the new run is still active. Add `rm -f /tmp/backfill.rc /tmp/backfill.log` to the launch command before the detached `docker exec -d`, or use a run-specific filename.

---

### Verdict

REVISE — 1 blocking issue: Task 4 reset races the recurring job during the deploy window, permanently excluding the trial rows from the corrective backfill. Fix is a one-step reorder (move Task 4 to after Task 5 Step 1). The 6 non-blocking findings are improvements but do not prevent a correct implementation.

---

## Plan Review — cycle 3
<!-- dglabs.agent.review-plan — 2026-08-10 -->

### Self-Review Gate (Pass 0)

- [x] 1. Placeholder scan — zero TODO/FIXME/XXX/TBD matches in plan body
- [x] 2. Dropped-field orphan scan — Task renumbering (old Reset=4→new 5, old Deploy+Backfill=5→new 4+6) checked exhaustively; all cross-references in the plan body use the new numbers correctly. Details: "Depends on: Task 4" (Task 5) ✓, "Depends on: Task 5" (Task 6) ✓, BREAK "Tasks 5 and 6" ✓, "20 from Task 4 Step 3" ✓, "BREAK declared before Task 5" (Task 6) ✓, Verification "Task 4 Step 1" ✓, "Task 3" ✓. No stale old-number references survive.
- [x] 3. Line-anchor freshness — all anchors verified against live files:
  - `extractor.py:69-71` ✓ (attributes dict-style prompt present and unchanged)
  - `extractor.py:146` ✓ (`response_format=ListingAnalysis,`)
  - `extractor.py:155` ✓ (`except Exception as exc:`)
  - `extractor.py:177` ✓ (`result = ListingAnalysis.model_validate_json(content)`)
  - `parser.py:188` ✓ (`def _extract_images(post: Tag, page_url: str = "") -> list[str]:`)
  - `deploy.yml:89-92` ✓ (`for svc in nginx backend; do … done` staleness gate)
  - `test_extractor.py:91` ✓ (`expected = ListingAnalysis(`)
  - `test_extractor.py:239` ✓ (`expected = ListingAnalysis(manufacturer="Robbe", model_name="Fokker DR.1")`)
- [x] 4. Test-count consistency — Task 1 Step 6: 4 new tests; Task 2 Step 3: 4 new tests; 2 existing tests updated. Verification: "8 new, 2 changed" — consistent throughout.
- [x] 5. Deleted-class caller check — no symbols deleted; n/a
- [x] 6. Mirror-reference verification — no Mirror instructions; n/a
- [x] 7. Convention contradictions across tasks — `_ListingAnalysisWire` / `to_analysis()` contract is consistently applied across Steps 2, 3, 5, 6 (Task 1) and the JSON-fallback (Step 3). No old-contract shape survives.
- [x] 8. Reachability — all task edges legal

| task | lands in | must call | edge legal? |
|---|---|---|---|
| Task 1 | `backend/app/analysis/extractor.py` | `pydantic.BaseModel`, `pydantic.ValidationError`, `app.analysis.vocabulary` | Yes |
| Task 2 | `backend/app/scraper/parser.py` | `urllib.parse.urljoin`, `logging` (module-level logger at line 13) | Yes |
| Task 3 | `frontend/src/components/FilterPanel.tsx` | Tailwind CSS class change only | Yes |
| Task 4 | GitHub Actions + VPS containers | `ghcr.io` registry, `deploy.yml`, SSH to VPS | Yes |
| Task 5 | Production DB via SSH | `rcn-scout-db-1` psql | Yes |
| Task 6 | Production container + paid API | `app.analysis.backfill`, `openrouter.ai/api/v1` | Yes |

Pass-0 gate: **8/8 pass** — all checks clear.

---

### Structural Checklist (Pass 1.A)

- [x] Required sections present (Context & Goal, Breaking Changes, Tasks 1–6, Verification)
- [x] Step status markers — all tasks carry `[ ]`
- [x] Step granularity — Tasks 1–3 are code tasks within context limits; Tasks 4–6 are operational steps, each self-contained
- [x] Test files named per step — `test_extractor.py` (Task 1 Steps 5–6), `test_parser.py` (Task 2 Step 3)
- [x] Breaking changes marked — "No" with rationale
- [x] BREAK markers — one BREAK before Task 5; justification covers Tasks 5 and 6 (irreversible data + paid API)

---

### Cycle 2 Blocking Finding — Fix Verification

**Cycle-2 Blocking 1 (race: reset before deploy):** Fully resolved. New ordering is Task 4 = Deploy (confirmed green via `gh run watch`) → Task 5 = Reset → Task 6 = Backfill. After Task 4 completes, the new code is live in both containers. Any analysis the recurring job runs from that point forward uses the fixed schema, so the reset in Task 5 cannot hand rows to the broken extractor. Race eliminated.

---

### Race-Free Analysis (Pass 1.B — specific cycle-3 mandate)

The new ordering is race-free for the cycle-2 defect. The only residual timing interaction is between Task 5 Step 1 (reset) and Task 5 Step 2 (verify count = 0): if the recurring job fires in the ~2-minute window between the two SQL calls, it will re-analyze some reset rows with the **correct** new code and mark them `llm_analyzed = true` again. The "Expected: 0" in Step 2 then becomes unreachable. This is documented under Non-Blocking 1 below.

---

### Task 4 Step 3 vs. Task 5 Reset (Pass 1.C — specific cycle-3 mandate)

Task 4 Step 3 runs 20 listings with the new correct code as a structured-output gate. Task 5 then resets all active-and-analyzed rows — including those 20 — using a blanket WHERE clause. The plan acknowledges this explicitly: "This covers … the 20 from Task 4 Step 3." The double-spend cost is ~$0.005, trivial. The rationale (blanket reset is simpler and more complete than excluding specific IDs) is valid. No contradiction exists in the description; the design intent is documented and clear.

---

### 🔴 Blocking

None.

---

### 🟡 Non-Blocking

**1. [Agent] — Task 5 Step 2 — "Expected: 0" is timing-dependent after the reordering**

After Task 5 Step 1 resets all active-and-analyzed rows, the recurring job (every 2 minutes, now using the new correct code) will begin re-analyzing rows from the reset pool and marking them `llm_analyzed = true`. If the recurring job fires before Task 5 Step 2's `SELECT COUNT(*)` runs, the count will be nonzero. A coder agent instructed to expect `0` may interpret a nonzero count as a reset failure and repeat the operation unnecessarily. The plan should add a note: "A nonzero result here means the recurring job has re-analyzed rows using the fixed schema — that is correct behavior, not a failure; proceed."

**2. [AI-Review] — Verification — Automated test gate not required before Task 4 deploy**

The Verification section's `pytest` and `vitest` commands are positioned "after all tasks are [IMPLEMENTED]", which includes Task 4 (deploy), Task 5 (reset), and Task 6 (backfill). These tests cover only Tasks 1–3's code changes. If a coder implements Task 1 or Task 2 with a test failure and proceeds to Task 4 without running the suites, broken code ships to production. The plan should add an explicit gate: "Both suites must pass before Task 4 is started." Provider: `[AI-Review]`.

**3. [AI-Review] — Task 4 Step 3 — Paid, persisting API call occurs before the BREAK**

The 20-listing trial in Task 4 Step 3 calls the paid API and persists results to the production DB, before the BREAK that guards "irreversible production writes and API spending." The cost is ~$0.005 and the rows are subsequently reset in Task 5 Step 1, so the practical impact is trivial. However, it is architecturally inconsistent: the BREAK text claims to guard all paid API spending, but Task 4 Step 3 precedes it. A non-persisting smoke test (e.g., a single call that discards the result) would satisfy the gate without mutating the DB. Accepted as non-blocking given the negligible cost, but worth noting. Provider: `[AI-Review]`.

**4. [AI-Review] — Task 6 Step 1 — `/tmp/backfill.rc` and `/tmp/backfill.log` not cleared before launch (cycle-2 NB6, unaddressed)**

A stale `/tmp/backfill.rc` from a prior trial or aborted run would make the polling command immediately report a completed exit code while the new run is still active. The launch command should prepend `rm -f /tmp/backfill.rc /tmp/backfill.log` or use a run-specific filename. Provider: `[AI-Review]`.

**5. [AI-Review] — Task 1 Step 6 — `test_wire_schema_has_no_open_ended_map` does not verify strict-mode completeness (cycle-2 NB5, unaddressed)**

The test asserts only `schema["properties"]["attributes"]["type"] == "array"`. OpenAI strict mode additionally requires every property to appear in `required` and `additionalProperties: false` at each object level. Pydantic v2 does not emit these by default without `model_config = ConfigDict(extra="forbid")`. The API could still reject the schema while this test passes. Consider asserting `required` completeness or adding `model_config`. Provider: `[AI-Review]`.

**6. [Agent/AI-Review] — Task 6 Step 1 — `backfill.py` `--limit 2200` relies on an undocumented ordering assumption (cycle-2 NB2, unaddressed)**

`_fetch_batch` queries `WHERE llm_analyzed = false ORDER BY scraped_at DESC` with no `is_sold` or `is_outdated` filter. The plan assumes all 2,079 active unanalyzed listings fall within the first 2,200 of 6,522 total unanalyzed rows because active listings were scraped most recently. This is plausible but undocumented. The plan should add a one-line note acknowledging the ordering dependency.

---

### Verdict

APPROVED — the cycle-2 blocker (reset-before-deploy race) is fully resolved by the task reordering. All six cycle-3 findings are non-blocking. Zero new blocking issues introduced by the restructuring. Plan is ready for Human approval.
