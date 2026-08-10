# LLM-Schema, Scraper-Robustheit und Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Restore the model-type filter by making structured outputs work with OpenAI-family models, harden the scraper against malformed image URLs, fix the sticky-header z-index, and backfill ~2.079 unanalyzed listings.

**Architecture:** `ListingAnalysis` keeps its dict-shaped public contract (consumed by `routes.py:331` and `job.py:61`), but the LLM now sees a strict-mode-compatible sibling schema in which the free-form `attributes` dict is expressed as a list of key/value pairs. The scraper's image extraction stops trusting `urljoin` on attacker-shaped `src` values. The backfill then runs once against `openai/gpt-5.6-luna` on production.

**Tech Stack:** Python 3.12, Pydantic v2, `openai` AsyncOpenAI SDK (OpenRouter base URL), pytest; React 18 + Tailwind for the z-index fix.

**Breaking Changes:** No. `ListingAnalysis.attributes` stays `dict[str, str]`; the pair-list exists only on the wire.

**Review log:** [`REVIEW_038_llm_schema_scraper_fixes.md`](REVIEW_038_llm_schema_scraper_fixes.md)

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-08-10 |
| Human | approved | 2026-08-10 |

_Plan review closed 2026-08-10 (cycle 1): 2 blocking + 6 non-blocking, all addressed._
_Plan review closed 2026-08-10 (cycle 2): 1 blocking (reset-before-deploy race) + 6 non-blocking, blocking fixed by task reordering._
_Plan review closed 2026-08-10 (cycle 3): APPROVED, 0 blocking. 4 of 6 non-blocking incorporated; 2 left to the backlog. See REVIEW_038._

---

## Context — verified facts

Everything below was verified against the running system on 2026-08-10, not recalled.

**Already done, outside this plan (deployed 2026-08-10):** `OPENROUTER_API_KEY` and `OPENROUTER_BATCH_MODEL` were missing from the `backend` service's `environment:` block in `docker-compose.prod.yml`. They are now present (`OPENROUTER_BATCH_MODEL` defaults to `openai/gpt-5.6-luna`), the backend container was recreated, and the analysis job no longer logs `OPENROUTER_API_KEY not set — skipping`. The repo copy and the VPS copy at `/opt/rcn-scout/docker-compose.prod.yml` are in sync; the previous VPS file is backed up as `docker-compose.prod.yml.bak-preLuna`.

**Production data state (2026-08-10):**

| Metric | Value |
|---|---|
| Active listings (`is_sold=false AND is_outdated=false`) | 2.079 |
| …of those with `model_type` | 16 (from the trial run) |
| `llm_analyzed = false` overall | 6.522 |
| Newest analyzed listing before the trial | 2026-05-31 |

**Measured trial cost (20 listings, `openai/gpt-5.6-luna`):** OpenRouter usage went from `$0.6137808` to `$0.61873845` = **$0.00496**, i.e. `$0.000248` per listing. Extrapolated full run ≈ **$0.51**. Account limit is `$5.00` with `$4.39` remaining and `is_free_tier: false`.

**The structured-output defect.** Every call to `client.beta.chat.completions.parse(..., response_format=ListingAnalysis)` (`extractor.py:140-148`) returns HTTP 400 from both the OpenAI and Azure providers:

```
Invalid schema for response_format 'ListingAnalysis':
'required' is required to be supplied and to be an array including every key
in properties. Extra required key 'attributes' supplied.
```

Cause: `attributes: dict[str, str]` (`extractor.py:90`) becomes a free-form object in the generated JSON schema. OpenAI strict mode does not support open-ended maps, so the field is dropped from `properties` while remaining in `required`, producing an internally inconsistent schema. Gemini Flash-Lite accepted it, which is why this never surfaced before.

The `except Exception` at `extractor.py:155` swallows the 400 and falls through to the JSON fallback (`extractor.py:160-179`), which succeeds. Consequences: two requests per listing instead of one, and measurably weaker extraction — in the 20-listing trial exactly one `manufacturer` was populated across 16 rows, despite ESM, CARF and KAVAN appearing verbatim in the titles.

**Trial-run classification quality was good.** `model_type` was correct on all 8 genuine models (ESM T28, Yak 54, Piper, Laser Arrow, Carbon Cup, BAE Hawk → `airplane`; Speed Astir, KAVAN Pulse → `glider`). The 8 rows without `model_type` are accessories (battery, ballast set, propellers, trailer, landing gear, turbine) for which `null` is the documented correct answer per `_SYSTEM_PROMPT` (`extractor.py:24`). The `failed=12` counter in the trial log is a counting artifact of `backfill.py:129-135`, not a quality signal.

**The scraper crash.** `_extract_images` calls `urljoin(page_url, src)` at **both** `parser.py:196` and `parser.py:201`. A `src` containing an unmatched `[` makes `urlsplit` raise `ValueError: Invalid IPv6 URL`. The exception propagates through `parse_detail` → `_phase1_category` → `_phase1_new_listings` and aborts the **entire** Phase-1 update run, so every category after the failing listing is skipped. Observed in production on listing `12131203` ("[V] OMP M2 V2").

**The z-index defect.** `FilterPanel.tsx:361` (sticky search header) and `ListingCard.tsx:127` (favourite star button) both carry `z-20` in the same root stacking context — the card's `<article>` has `relative` but no `z-index`, so it creates no stacking context of its own. Equal z-index means DOM order decides, and cards come after the header, so the star renders above the sticky bar. The filter sheet uses `z-50` and its backdrop `z-40` (`FilterPanel.tsx:69,82`), leaving `z-30` free.

**Downstream contract for `attributes`** — verified consumers, both dict-shaped:
- `backend/app/api/routes.py:331` — `(base.attributes or {}).get("wingspan_mm")`
- `backend/app/analysis/job.py:61` — `"attributes": result.attributes`
- `backend/app/analysis/backfill.py:77` — `json.dumps(analysis.attributes)`

**Test commands** (verified against `backend/pytest.ini` and `frontend/package.json`):
- Backend: `docker compose exec backend pytest tests/ -v`
- Frontend: `npm test` in `frontend/` (script `test` → `vitest`)

---

## Task 1: Strict-mode-compatible LLM schema [ ]

**Files:**
- Modify: `backend/app/analysis/extractor.py:69-71` (prompt), `:81-99` (models), `:138-152` (parse call)
- Test: `backend/tests/test_extractor.py`

**Reuse check:** No existing pattern found — this is the only structured-output callsite in the codebase (verified: `grep -rn "response_format" backend/app` returns only `extractor.py`). New convention introduced by this plan.

**Step 1: Add the wire-level schema and keep the public one dict-shaped**

Insert after the `_DRIVE_TYPES` definition (`extractor.py:78`), before `class ListingAnalysis`:

```python
class _AttributePair(BaseModel):
    """One extra technical attribute.

    OpenAI strict structured outputs reject open-ended maps, so `attributes`
    travels over the wire as a list of pairs and is folded into a dict on the
    public model. See PLAN-038.
    """

    key: str
    value: str


class _ListingAnalysisWire(BaseModel):
    """Wire schema handed to the LLM. Every field is required and nullable,
    which is what OpenAI strict mode demands."""

    manufacturer: str | None = None
    model_name: str | None = None
    drive_type: str | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    completeness: str | None = None
    price_euros: float | None = None
    shipping_available: bool | None = None
    attributes: list[_AttributePair] = Field(default_factory=list)

    def to_analysis(self) -> "ListingAnalysis":
        return ListingAnalysis(
            manufacturer=self.manufacturer,
            model_name=self.model_name,
            drive_type=self.drive_type,
            model_type=self.model_type,
            model_subtype=self.model_subtype,
            completeness=self.completeness,
            price_euros=self.price_euros,
            shipping_available=self.shipping_available,
            attributes={p.key: p.value for p in self.attributes if p.key},
        )
```

`ListingAnalysis` itself is **unchanged** — `attributes` stays `dict[str, str]` because `routes.py:331`, `job.py:61` and `backfill.py:77` all consume it as a dict.

**Step 2: Use the wire schema for structured output**

Replace `response_format=ListingAnalysis` at `extractor.py:146` with `response_format=_ListingAnalysisWire`, and convert the result. The parsed branch (`extractor.py:149-152`) becomes:

```python
        parsed = response.choices[0].message.parsed
        if parsed is not None:
            logger.info("LLM [%s] structured-output: OK", model)
            return parsed.to_analysis(), None
```

**Step 3: Accept both shapes in the JSON fallback**

The fallback at `extractor.py:177` uses `ListingAnalysis.model_validate_json(content)`. Models sometimes answer with the pair-list shape now that the prompt asks for it, so parse leniently — replace that line with:

```python
        try:
            result = _ListingAnalysisWire.model_validate_json(content).to_analysis()
        except ValidationError:
            result = ListingAnalysis.model_validate_json(content)
```

Add `ValidationError` to the pydantic import at `extractor.py:7`.

**Step 4: Align the prompt with the pair-list shape**

Replace `extractor.py:69-71` with:

```
Für "attributes": extrahiere alle weiteren technischen Daten als Liste von
Objekten mit den Feldern "key" und "value"
(z.B. {"key": "wingspan_mm", "value": "2800"}).
Keys immer englisch, snake_case. Values immer als Strings.
Keine weiteren Daten → leere Liste.
```

**Step 5: Update the two existing tests that mock the parsed result**

`test_extractor.py:91` and `:239` build a `ListingAnalysis` and hand it to the mocked `parse` call. After Step 2 the code calls `.to_analysis()` on that object, which `ListingAnalysis` does not have — both tests would fail with `AttributeError`. Switch both mocks to the wire model; the assertions stay as they are, because `to_analysis()` reproduces the same values.

At `test_extractor.py:91`, replace the `expected = ListingAnalysis(...)` construction with the wire equivalent, moving the `attributes` dict to pair form:

```python
        expected = _ListingAnalysisWire(
            manufacturer="Black Horse",
            model_name="L-39 Albatros",
            drive_type="electric",
            model_type="airplane",
            model_subtype="jet",
            completeness="ARF",
            attributes=[
                _AttributePair(key="wingspan_mm", value="1700"),
                _AttributePair(key="weight_g", value="3500"),
            ],
        )
```

Keep the existing field values from the file — the block above shows the shape, not the values. Assertions that compare `result.attributes` to a dict remain correct.

At `test_extractor.py:239`, replace `ListingAnalysis(manufacturer="Robbe", model_name="Fokker DR.1")` with `_ListingAnalysisWire(manufacturer="Robbe", model_name="Fokker DR.1")`.

Extend the import at `test_extractor.py:14` to:

```python
from app.analysis.extractor import (
    ListingAnalysis,
    _AttributePair,
    _ListingAnalysisWire,
    analyze_listing,
)
```

The `ListingAnalysis` import stays — the clamping tests at `:266-300` construct it directly and are unaffected.

**Step 6: Write tests**

Add to `backend/tests/test_extractor.py`:

```python
def test_wire_schema_has_no_open_ended_map():
    """OpenAI strict mode rejects free-form dicts — attributes must be an array."""
    schema = _ListingAnalysisWire.model_json_schema()
    assert schema["properties"]["attributes"]["type"] == "array"


def test_wire_to_analysis_folds_pairs_into_dict():
    wire = _ListingAnalysisWire(
        model_type="airplane",
        attributes=[
            _AttributePair(key="wingspan_mm", value="2800"),
            _AttributePair(key="weight_g", value="4200"),
        ],
    )
    result = wire.to_analysis()
    assert result.attributes == {"wingspan_mm": "2800", "weight_g": "4200"}
    assert result.model_type == "airplane"


def test_wire_to_analysis_drops_empty_keys():
    wire = _ListingAnalysisWire(attributes=[_AttributePair(key="", value="x")])
    assert wire.to_analysis().attributes == {}


def test_wire_to_analysis_applies_vocabulary_clamp():
    """to_analysis() must route through ListingAnalysis so clamping still runs."""
    wire = _ListingAnalysisWire(model_type="Flugzeug")
    assert wire.to_analysis().model_type is None
```

**Step 7: Commit**

```bash
git add backend/app/analysis/extractor.py backend/tests/test_extractor.py
git commit -m "fix(analysis): strict-mode-compatible LLM schema for attributes (PLAN-038)"
```

---

## Task 2: Harden image URL resolution [ ]

**Files:**
- Modify: `backend/app/scraper/parser.py:188-205`
- Test: `backend/tests/test_parser.py`

**Reuse check:** No existing pattern found — `grep -rn "urljoin" backend/app` returns only `parser.py:196,201`. Both sites need the same guard.

**Step 1: Add a safe resolver**

Insert immediately above `_extract_images` (`parser.py:188`):

```python
def _safe_urljoin(page_url: str, src: str) -> str | None:
    """Resolve a possibly-malformed image src against the page URL.

    A src containing an unmatched '[' makes urlsplit raise
    "Invalid IPv6 URL". That used to abort the entire Phase-1 run
    (observed on listing 12131203). One bad image must cost one image,
    not the whole crawl. See PLAN-038.
    """
    if not page_url:
        return src
    try:
        return urljoin(page_url, src)
    except ValueError:
        logger.warning("Skipping malformed image src: %r", src)
        return None
```

**Step 2: Route both loops through it**

`parser.py:193-196` becomes:

```python
    for img in post.select(".attachment img[src], .attachmentList img[src]"):
        src: str = img.get("src", "").strip()
        if not src:
            continue
        resolved = _safe_urljoin(page_url, src)
        if resolved:
            urls.append(resolved)
```

`parser.py:199-203` becomes:

```python
    for img in post.select(".bbWrapper img[src]"):
        src = img.get("src", "").strip()
        if not src or "smilie" in src.lower():
            continue
        resolved = _safe_urljoin(page_url, src)
        if resolved and resolved not in urls:
            urls.append(resolved)
```

Confirm `parser.py` has a module-level `logger`; if not, add `logger = logging.getLogger(__name__)` and the `logging` import alongside the existing imports.

**Step 3: Write tests**

Extend the imports at the top of `backend/tests/test_parser.py` — the file currently imports only `parse_detail`:

```python
from bs4 import BeautifulSoup

from app.scraper.parser import _extract_images, parse_detail
```

The malformed `src` must place the unmatched bracket in the **netloc**, not the path. Verified on 2026-08-10 with Python 3.12:

| `src` | `urljoin` result |
|---|---|
| `https://example.com/[V] broken.jpg` | resolves fine — no exception |
| `/attachments/[V] x.jpg` | resolves fine — no exception |
| `//[V] OMP broken.jpg` | **raises `ValueError: Invalid IPv6 URL`** |

A path-bracket fixture would pass with or without the guard and prove nothing. Add:

```python
def test_extract_images_skips_malformed_src_without_raising():
    """A protocol-relative src with an unmatched '[' hits the IPv6 branch of
    urlsplit. Before PLAN-038 this aborted the whole phase-1 run."""
    html = (
        '<div class="bbWrapper">'
        '<img src="//[V] OMP broken.jpg">'
        '<img src="/attachments/good.jpg">'
        "</div>"
    )
    post = BeautifulSoup(html, "html.parser")
    urls = _extract_images(post, page_url="https://rc-network.de/threads/1/")
    assert urls == ["https://rc-network.de/attachments/good.jpg"]


def test_malformed_src_really_raises_without_the_guard():
    """Guards the fixture itself: if this stops raising, the test above is vacuous."""
    with pytest.raises(ValueError):
        urljoin("https://rc-network.de/threads/1/", "//[V] OMP broken.jpg")


def test_extract_images_still_skips_smilies():
    html = '<div class="bbWrapper"><img src="/img/smilies/happy.png"></div>'
    post = BeautifulSoup(html, "html.parser")
    assert _extract_images(post, page_url="https://rc-network.de/t/1/") == []


def test_extract_images_without_page_url_returns_raw_src():
    html = '<div class="attachment"><img src="/attachments/x.jpg"></div>'
    post = BeautifulSoup(html, "html.parser")
    assert _extract_images(post) == ["/attachments/x.jpg"]
```

`test_malformed_src_really_raises_without_the_guard` needs `import pytest` and `from urllib.parse import urljoin` at the top of the test file.

**Step 4: Commit**

```bash
git add backend/app/scraper/parser.py backend/tests/test_parser.py
git commit -m "fix(scraper): malformed image src no longer aborts the phase-1 run (PLAN-038)"
```

---

## Task 3: Sticky header above listing cards [ ]

**Files:**
- Modify: `frontend/src/components/FilterPanel.tsx:361`

**Reuse check:** Reuses the existing z-index ladder already established in the same file — backdrop `z-40` (`FilterPanel.tsx:69`), sheet `z-50` (`FilterPanel.tsx:82`). `z-30` is the unused rung between the cards' `z-20` and the backdrop.

**Step 1: Raise the sticky header**

At `FilterPanel.tsx:361`, change `z-20` to `z-30` in the sticky header's `className`. Leave every other class untouched, and do **not** change `ListingCard.tsx` — lowering the star button would put it behind its own card image on some breakpoints.

**Step 2: Tests**

No test. Vitest + jsdom does not compute stacking contexts, so any assertion here would restate the class string rather than the behaviour it is supposed to protect. Verified manually in the Verification section instead.

**Step 3: Commit**

```bash
git add frontend/src/components/FilterPanel.tsx
git commit -m "fix(ui): sticky search header above listing card star button (PLAN-038)"
```

---

## Task 4: Deploy Tasks 1–3 to production [ ]

**Depends on:** Task 1, Task 2, Task 3

**Files:** none — release operation.

**This must happen before any data operation.** The recurring analysis job runs every two minutes against whatever code the container holds. Resetting rows while the old code is still deployed hands them straight back to the broken extractor, which re-marks them `llm_analyzed = true` with degraded data and drops them out of the backfill queue again. Deploy first, then touch data.

**Step 1: Run both suites before releasing**

The `## Verification` section runs at end-of-plan, which is *after* this deploy. Publishing a release is what puts code on production, so the automated gate has to be pulled forward — do not release on unrun tests.

```bash
docker compose exec backend pytest tests/ -v
```

```bash
cd frontend && npm test
```

Both must be green. A failure here means returning to Task 1 or Task 2, not proceeding.

**Step 2: Publish a release**

`.github/workflows/deploy.yml` triggers on `release: [published]` — **not** on push. It builds and pushes both the `backend` and the `nginx` image (the latter carries the frontend bundle, so Task 3's z-index fix ships only through this path), writes `IMAGE_TAG` into the VPS `.env`, recreates both containers, and fails the job if a container is still running a stale image.

A plain `git push` or a bare `git tag` deploys nothing.

```bash
git push origin main
gh release create v2.11.0 --title "v2.11.0" \
  --notes "PLAN-038: strict-mode LLM schema, scraper URL hardening, sticky-header z-index"
```

Confirm the tag does not already exist (`gh release list`) and bump the minor version if it does — the last release was v2.10.0.

**Step 3: Wait for the workflow and confirm it is green**

```bash
gh run watch $(gh run list --workflow=deploy.yml --limit=1 --json databaseId -q '.[0].databaseId')
```

The workflow's own staleness check (`deploy.yml:89-92`) is the gate — a green run means both containers are on the new tag. Do not proceed on a red or skipped run.

**Step 4: Confirm structured output actually works now**

Run the trial at small scale and read the log. This is the gate for everything that follows: if `structured-output: OK` does not appear, stop and return to Task 1 rather than spending money on a broken path.

This step does spend money — 20 listings ≈ `$0.005` at the measured rate — and it sits *before* the BREAK. That is deliberate: the BREAK asks the Human to approve a `$0.51` run, and that decision is worthless without evidence that the fix works. Half a cent buys the evidence. The rows it writes are reset again in Task 5, so nothing degraded survives.

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-backend-1 python -m app.analysis.backfill --limit 20 2>&1 | tail -20"
```

Expected: `LLM [openai/gpt-5.6-luna] structured-output: OK` lines and **no** `trying JSON fallback` lines.

---

## Task 5: Reset the degraded rows [ ]

**Depends on:** Task 4

**Files:** none — production data operation.

> **BREAK — Human approval required before this task and everything after it.**
>
> Justified under the BREAK policy: Tasks 5 and 6 both write irreversibly to production state, and Task 6 additionally spends money on an external API. Task 5 nullifies analysis columns; Task 6 sets `llm_analyzed = true` on ~2.079 rows, permanently removing them from the re-analysis queue. Neither is recoverable without a re-run that costs the same again.
>
> Present at the BREAK: the release tag from Task 4, the `structured-output: OK` evidence from Task 4 Step 3, the current `llm_analyzed = false` count, the measured per-listing cost, and the remaining OpenRouter credit.

Rows analyzed through the degraded JSON-fallback path carry `llm_analyzed = true`. Because both the recurring job (`job.py`) and the backfill select on `WHERE llm_analyzed = false`, they would never be revisited. Reset them so Task 6 re-analyzes them through the fixed schema.

This covers the 16 rows from the pre-plan trial **and** the 20 from Task 4 Step 3, plus anything the recurring job processed with the old code in the meantime — the `WHERE` clause below catches all of them without needing to know the exact count.

**Step 1: Reset**

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-db-1 psql -U rcscout -d rcscout -c \
   \"UPDATE listings SET llm_analyzed = false, manufacturer = NULL, model_name = NULL, \
     drive_type = NULL, model_type = NULL, model_subtype = NULL, completeness = NULL, \
     attributes = NULL, shipping_available = NULL \
     WHERE llm_analyzed = true AND is_sold = false AND is_outdated = false;\""
```

Expected: roughly `UPDATE 36` (16 from the pre-plan trial plus 20 from Task 4 Step 3), possibly more if the recurring job processed further rows before the deploy landed. Any count is acceptable here — note the actual number in the plan and continue. What matters is Step 2 reading zero.

**Step 2: Verify**

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-db-1 psql -U rcscout -d rcscout -c \
   \"SELECT COUNT(*) FROM listings WHERE llm_analyzed = true AND is_sold = false AND is_outdated = false;\""
```

Expected: `0`, or a small number if the 2-minute job analyzed a fresh listing between the two commands. Anything above zero is only acceptable when the rows are newly scraped ones the *fixed* code just processed — check `manufacturer`/`model_type` on them before continuing. A large count means the deploy did not land and Task 4 must be revisited.

---

## Task 6: Production backfill [ ]

**Depends on:** Task 5

**Files:** none — production operation against a paid API. Covered by the BREAK declared before Task 5.

**Step 1: Record usage, run the full backfill, record usage again**

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "cd /opt/rcn-scout && set -a && . ./.env && set +a && \
   curl -s --max-time 20 -H \"Authorization: Bearer \$OPENROUTER_API_KEY\" \
   https://openrouter.ai/api/v1/key | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"data\"][\"usage\"])'"
```

The run takes roughly 40–70 minutes at `_REQUEST_DELAY_S = 0.1` plus API latency, so run it detached and poll rather than holding the SSH session open:

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec -d rcn-scout-backend-1 sh -c \
   'rm -f /tmp/backfill.rc /tmp/backfill.log; \
    python -m app.analysis.backfill --limit 2200 > /tmp/backfill.log 2>&1; \
    echo \$? > /tmp/backfill.rc'"
```

The `rm -f` matters: a leftover `/tmp/backfill.rc` from an earlier attempt would read as "already finished" the moment polling starts.

`--limit 2200` covers the ~2.079 active rows with headroom; the script stops on its own when the queue drains (`backfill.py:114-116`).

Poll until `/tmp/backfill.rc` exists — a detached `docker exec` reports nothing back, so without the recorded exit code a crashed run is indistinguishable from a slow one:

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-backend-1 sh -c \
   'cat /tmp/backfill.rc 2>/dev/null || echo running; tail -3 /tmp/backfill.log'"
```

Expected: `/tmp/backfill.rc` contains `0`, and the log's final line reads `Backfill complete: analyzed=<n>, failed=<m> out of <total>`. A non-zero code means the run died partway — the already-analyzed rows are committed and safe, so a re-run simply resumes where it stopped.

`failed` counts all-None results, which for accessory listings is the correct outcome — do not read it as an error rate.

Capture usage a second time with the same command as above. The delta divided by the processed count is the actual per-listing cost; record it in the plan. The pre-plan trial measured `$0.000248`.

**Step 2: Verify the filter is fixed**

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-db-1 psql -U rcscout -d rcscout -c \
   \"SELECT model_type, COUNT(*) FROM listings \
     WHERE is_sold = false AND is_outdated = false GROUP BY model_type ORDER BY 2 DESC;\""
```

Expected: non-zero counts for `airplane`, `helicopter` and `glider` rather than a single all-NULL row.

---

## Verification

Run once, after all tasks are `[IMPLEMENTED]`.

**Automated:**

```bash
docker compose exec backend pytest tests/ -v
```

```bash
cd frontend && npm test
```

Both suites must pass with no new failures. Task 1 adds 4 backend tests and updates 2 existing ones (`test_extractor.py:91`, `:239`); Task 2 adds 4. Net: 8 new, 2 changed.

**Manual — extraction quality:** after Task 6, confirm the fixed schema actually improved extraction. Before the fix, exactly one `manufacturer` was populated across 16 rows.

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "docker exec rcn-scout-db-1 psql -U rcscout -d rcscout -c \
   \"SELECT COUNT(*) AS analysiert, COUNT(manufacturer) AS mit_hersteller, \
     COUNT(model_type) AS mit_typ FROM listings \
     WHERE llm_analyzed = true AND is_sold = false AND is_outdated = false;\""
```

Expected: `mit_hersteller` well above the pre-fix rate of ~6 %.

**Manual — z-index (Task 3):** only observable after the release from Task 4 Step 1, because the frontend bundle ships inside the `nginx` image. Open the app on a mobile viewport (≤ 640 px, the sticky header is `sm:hidden`), scroll the results list until a card's star button passes behind the search bar, and confirm the star disappears behind the header instead of floating above it. Confirm the filter button stays clickable at that scroll position.

**Manual — scraper (Task 2):** confirm a full Phase-1 run completes without the `Invalid IPv6 URL` abort:

```bash
ssh -i ~/.ssh/id_netcup_mro deploy@152.53.238.3 \
  "cd /opt/rcn-scout && docker compose -f docker-compose.prod.yml logs --since=2h backend \
   | grep -E 'Update job (complete|failed)'"
```

Expected: `Update job complete: {...}` with no `Update job failed: Invalid IPv6 URL`.

**Manual — filter end-to-end:** in the UI, select model type "Hubschrauber" and then "Flugzeuge" and confirm both return results.

---

## Out of scope — noted for the backlog

- `OPENROUTER_MODEL` is set in `.env` on the VPS and in `docker-compose.yml:40` but does not exist in `config.py`. Dead variable; removing it is a separate cleanup.
- The free cascade has no 429 handling and no backoff — HTTP 429 falls into the generic `except Exception` at `extractor.py:155` and counts toward the three-strike disable at `LLM_CASCADE_FAILURE_THRESHOLD`. Not triggered by this plan (the backfill pins a single paid model), but it remains a real weakness of the recurring job.
- The PLAN-021 one-shot normalization block at `main.py:108-182` is labelled "remove in next release" and still runs on every backend start.
- `backfill.py` counts all-None results as `failed`, which made a healthy trial look like a 60 % failure rate. A clearer counter (`analyzed` / `no_model_data` / `errored`) would avoid the next false alarm.
- Review cycle 3, non-blocking 5: `test_wire_schema_has_no_open_ended_map` asserts the `attributes` type but not full strict-mode conformance (every property in `required`, `additionalProperties: false`). A stricter assertion would catch a future field regressing the schema. Deferred — the live `structured-output: OK` gate in Task 4 Step 4 covers the actual risk for this plan.
- Review cycle 3, non-blocking 6: `backfill.py --limit 2200` assumes the unanalyzed queue is drained in an order that lets a single run finish. The script re-selects from offset 0 each batch, so this holds, but the assumption is undocumented in the script itself.
