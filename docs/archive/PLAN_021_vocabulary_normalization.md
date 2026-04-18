# PLAN 021 — Controlled Vocabulary for LLM Extractor

> **For Claude:** REQUIRED SUB-SKILL: Use `dglabs.executing-plans` to implement this plan task-by-task.

**Goal:** Enforce a fixed, category-aware vocabulary for `model_type` and `model_subtype` in the LLM extractor, and clean existing dirty data with a one-shot SQL normalization.

**Architecture:** Two layers — (1) a central `vocabulary.py` module defines canonical values and a Pydantic model-validator that silently clamps unknown values to `None`; (2) the system prompt is rewritten to list exact allowed values per forum category so the LLM rarely produces garbage in the first place. Existing dirty data is cleaned by a one-shot UPDATE in `main.py` startup (same pattern as PLAN-020 NULL-sweep).

**Tech Stack:** Python, Pydantic V2 (`model_validator`), SQLAlchemy `text()`, pytest

**Breaking Changes:** No. `model_type` and `model_subtype` can already be `None`; clamping unknown values to `None` is semantically equivalent. No API schema changes. No new DB columns.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-18 |
| Human | approved | 2026-04-18 |

---

## Context

Measured on staging (2026-04-18, 3583 active listings):
- `model_subtype` has 393 distinct values — most are LLM inventions (`high-wing`, `high_wing`, `highwing`, `3D`, `aerobatic`, `acro`, etc.)
- `model_type` has junk values like `rc-elektronik`, `engine`, `battery` (forum categories that bled in)
- Root cause: prompt lists examples, not a strict enum; no validation on the Pydantic model

The forum `category` field is already sent to the LLM (`Kategorie: flugmodelle`), so the LLM has everything it needs to pick the right subtype — it just isn't constrained to do so.

## Canonical Vocabulary

```python
MODEL_TYPES = {"airplane", "helicopter", "multicopter", "glider", "boat", "car"}

MODEL_SUBTYPES: dict[str, set[str]] = {
    "airplane": {
        "jet", "warbird", "trainer", "scale", "3d", "nurflügler",
        "hochdecker", "tiefdecker", "mitteldecker", "delta", "biplane",
        "aerobatic", "kit", "hotliner", "funflyer", "speed", "pylon",
    },
    "helicopter": {"700", "580", "600", "550", "500", "450", "420", "380", "scale"},
    "glider": {
        "thermik", "hotliner", "f3b", "f3k", "f3j", "f5j", "f5b", "f5k",
        "f3f", "f3l", "hangflug", "dlg", "scale", "motorglider",
    },
    "multicopter": {"quadcopter", "hexacopter", "fpv"},
    "boat": {"rennboot", "segelboot", "schlepper", "submarine", "yacht"},
    "car": {"buggy", "monstertruck", "crawler", "tourenwagen", "truggy", "drift"},
}
```

## SQL Normalization Mappings

Existing dirty values → canonical (case-insensitive match):

**model_type** — set to `NULL` if not in `MODEL_TYPES`:
- `rc-elektronik`, `rc-electronics`, `rc_electronics`, `rc-elektronik`, `antriebstechnik`, `einzelteile`, `motor`, `engine`, `battery`, `servo`, `receiver`, `parts`, `single_part`, `accessories`, `accessory`, `book`, `magazine`, `tool`, `Unknown`, `other`, `cnc_machine` → `NULL`

**model_subtype airplane**:
- `3D` → `3d`
- `high-wing`, `high_wing`, `highwing` → `hochdecker`
- `low_wing` → `tiefdecker`
- `shoulder_decker` → `mitteldecker`
- `aerobatic`, `acro` → `aerobatic`
- `pylon_racer` → `pylon`
- `motor_glider`, `motorglider`, `motorsegler` → `NULL` for airplane (motorglider is a valid glider subtype but NOT a valid airplane subtype)
- `f3a`, `f3b`, `f3j` (when on airplane) → `NULL` (competition class belongs on glider)
- all other non-canonical values → `NULL`

**model_subtype glider**:
- `motorglider`, `motor-glider`, `motor_glider`, `motorsegler` → `motorglider`
- `thermal` → `thermik`
- `F3J`, `F5J`, `F5K`, `F3B` → lowercase equivalent
- all other non-canonical → `NULL`

**model_subtype helicopter** — already clean; only normalize case (e.g. `3GX`, `3D PRO` → `NULL`).

---

## Steps

### Task 1: Create `backend/app/analysis/vocabulary.py` [approved]

**Files:**
- Create: `backend/app/analysis/vocabulary.py`
- Test: `backend/tests/test_vocabulary.py` (new)

**Step 1: Write failing tests**

```python
# backend/tests/test_vocabulary.py
import pytest
from app.analysis.vocabulary import MODEL_TYPES, MODEL_SUBTYPES, clamp_model_type, clamp_model_subtype


def test_model_types_are_expected_set():
    assert MODEL_TYPES == {"airplane", "helicopter", "multicopter", "glider", "boat", "car"}


def test_clamp_model_type_known_value():
    assert clamp_model_type("airplane") == "airplane"


def test_clamp_model_type_unknown_returns_none():
    assert clamp_model_type("rc-elektronik") is None
    assert clamp_model_type("engine") is None
    assert clamp_model_type("Unknown") is None


def test_clamp_model_type_none_returns_none():
    assert clamp_model_type(None) is None


def test_clamp_model_subtype_known():
    assert clamp_model_subtype("airplane", "jet") == "jet"
    assert clamp_model_subtype("glider", "thermik") == "thermik"
    assert clamp_model_subtype("helicopter", "700") == "700"


def test_clamp_model_subtype_case_insensitive():
    assert clamp_model_subtype("airplane", "JET") == "jet"
    assert clamp_model_subtype("glider", "F5J") == "f5j"


def test_clamp_model_subtype_unknown_returns_none():
    assert clamp_model_subtype("airplane", "high-wing") is None
    assert clamp_model_subtype("airplane", "high_wing") is None
    assert clamp_model_subtype("airplane", "aerobatic_plane") is None


def test_clamp_model_subtype_case_normalizes_to_canonical():
    # "3D" lowercases to "3d" which IS canonical — should return "3d", not None
    assert clamp_model_subtype("airplane", "3D") == "3d"
    assert clamp_model_subtype("glider", "F5J") == "f5j"


def test_clamp_model_subtype_none_model_type_returns_none():
    assert clamp_model_subtype(None, "jet") is None


def test_clamp_model_subtype_none_subtype_returns_none():
    assert clamp_model_subtype("airplane", None) is None


def test_model_subtypes_airplane_contains_required_values():
    airplane = MODEL_SUBTYPES["airplane"]
    for v in ("jet", "warbird", "trainer", "scale", "3d", "hochdecker", "tiefdecker"):
        assert v in airplane, f"Missing: {v}"
```

**Step 2: Run to confirm failure**

```bash
docker compose exec backend pytest tests/test_vocabulary.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.analysis.vocabulary'`

**Step 3: Implement `vocabulary.py`**

```python
"""Canonical vocabulary for LLM-extracted model classification fields.

All values are lowercase. clamp_* helpers normalise LLM output to canonical
values or None — they never raise.
"""
from __future__ import annotations

MODEL_TYPES: set[str] = {
    "airplane", "helicopter", "multicopter", "glider", "boat", "car",
}

MODEL_SUBTYPES: dict[str, set[str]] = {
    "airplane": {
        "jet", "warbird", "trainer", "scale", "3d", "nurflügler",
        "hochdecker", "tiefdecker", "mitteldecker", "delta", "biplane",
        "aerobatic", "kit", "hotliner", "funflyer", "speed", "pylon",
    },
    "helicopter": {"700", "580", "600", "550", "500", "450", "420", "380", "scale"},
    "glider": {
        "thermik", "hotliner", "f3b", "f3k", "f3j", "f5j", "f5b", "f5k",
        "f3f", "f3l", "hangflug", "dlg", "scale", "motorglider",
    },
    "multicopter": {"quadcopter", "hexacopter", "fpv"},
    "boat": {"rennboot", "segelboot", "schlepper", "submarine", "yacht"},
    "car": {"buggy", "monstertruck", "crawler", "tourenwagen", "truggy", "drift"},
}


def clamp_model_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    return v if v in MODEL_TYPES else None


def clamp_model_subtype(model_type: str | None, value: str | None) -> str | None:
    if not model_type or not value:
        return None
    allowed = MODEL_SUBTYPES.get(model_type, set())
    v = value.strip().lower()
    return v if v in allowed else None
```

**Step 4: Run tests**

```bash
docker compose exec backend pytest tests/test_vocabulary.py -v
```
Expected: all 10 tests pass.

**Step 5: Commit**

```bash
git add backend/app/analysis/vocabulary.py backend/tests/test_vocabulary.py
git commit -m "feat: add controlled vocabulary for model_type and model_subtype"
```

---

### Task 2: Wire vocabulary into `ListingAnalysis` Pydantic model [approved]

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/analysis/extractor.py`
- Modify: `backend/tests/test_extractor.py`

**Step 1: Add failing tests to `test_extractor.py`**

Add at the end of `backend/tests/test_extractor.py`:

```python
# --- Vocabulary clamping ---

class TestListingAnalysisVocabularyClamping:
    def test_known_model_type_passes_through(self):
        a = ListingAnalysis(model_type="airplane", model_subtype="jet")
        assert a.model_type == "airplane"
        assert a.model_subtype == "jet"

    def test_unknown_model_type_clamped_to_none(self):
        a = ListingAnalysis(model_type="rc-elektronik", model_subtype="sender")
        assert a.model_type is None
        assert a.model_subtype is None  # subtype also cleared when type is invalid

    def test_unknown_model_subtype_clamped_to_none(self):
        a = ListingAnalysis(model_type="airplane", model_subtype="high-wing")
        assert a.model_type == "airplane"
        assert a.model_subtype is None

    def test_case_insensitive_normalization(self):
        a = ListingAnalysis(model_type="Airplane", model_subtype="JET")
        assert a.model_type == "airplane"
        assert a.model_subtype == "jet"

    def test_none_values_unchanged(self):
        a = ListingAnalysis(model_type=None, model_subtype=None)
        assert a.model_type is None
        assert a.model_subtype is None

    def test_valid_subtype_for_wrong_type_clamped(self):
        # "thermik" is valid for glider but not airplane
        a = ListingAnalysis(model_type="airplane", model_subtype="thermik")
        assert a.model_subtype is None

    def test_drive_type_unknown_clamped_to_none(self):
        a = ListingAnalysis(drive_type="brushless")
        assert a.drive_type is None

    def test_drive_type_known_passes_through(self):
        a = ListingAnalysis(drive_type="turbine")
        assert a.drive_type == "turbine"

    def test_drive_type_case_normalized(self):
        a = ListingAnalysis(drive_type="Electric")
        assert a.drive_type == "electric"
```

**Step 2: Run to confirm failure**

```bash
docker compose exec backend pytest tests/test_extractor.py::TestListingAnalysisVocabularyClamping -v
```
Expected: FAIL — no validator exists yet.

**Step 3: Update `extractor.py`**

Add import at top of `extractor.py`:
```python
from app.analysis.vocabulary import clamp_model_type, clamp_model_subtype
```

Add to existing imports:
```python
from pydantic import BaseModel, Field, model_validator
```

Replace the `ListingAnalysis` class:
```python
_DRIVE_TYPES = {"electric", "nitro", "gas", "turbine"}


class ListingAnalysis(BaseModel):
    manufacturer: str | None = None
    model_name: str | None = None
    drive_type: str | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    completeness: str | None = None
    price_euros: float | None = None
    shipping_available: bool | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def clamp_to_vocabulary(self) -> "ListingAnalysis":
        self.model_type = clamp_model_type(self.model_type)
        self.model_subtype = clamp_model_subtype(self.model_type, self.model_subtype)
        if self.drive_type is not None:
            v = self.drive_type.strip().lower()
            self.drive_type = v if v in _DRIVE_TYPES else None
        return self
```

**Step 4: Run tests**

```bash
docker compose exec backend pytest tests/test_extractor.py -v
```
Expected: all tests pass (including existing ones).

**Step 5: Commit**

```bash
git add backend/app/analysis/extractor.py backend/tests/test_extractor.py
git commit -m "feat: clamp LLM output to controlled vocabulary in ListingAnalysis"
```

---

### Task 3: Rewrite system prompt with category-aware subtype lists [approved]

**Depends on:** Task 2

**Files:**
- Modify: `backend/app/analysis/extractor.py` (only `_SYSTEM_PROMPT`)

No new tests needed — the prompt is a string constant, already covered by integration behaviour. Manual spot-check in Verification (Step 7.3).

**Step 1: Replace `_SYSTEM_PROMPT`**

```python
_SYSTEM_PROMPT = """\
Du analysierst RC-Modell-Kleinanzeigen von rc-network.de.
Extrahiere aus Titel und Beschreibung die Produktdaten.
Gib nur Felder zurück die du sicher identifizieren kannst.
Verwende EXAKT die aufgelisteten Werte — keine Varianten, keine Übersetzungen.
Wenn kein passender Wert existiert: null.

model_type — NUR wenn es sich um ein RC-Modell handelt:
  "airplane", "helicopter", "multicopter", "glider", "boat", "car"
  Elektronik, Akkus, Sender, Regler, Motoren, Ersatzteile → model_type = null

model_subtype — wähle EXAKT einen der erlaubten Werte für den jeweiligen model_type:
  airplane:    jet | warbird | trainer | scale | 3d | nurflügler | hochdecker | tiefdecker | mitteldecker | delta | biplane | aerobatic | kit | hotliner | funflyer | speed | pylon
  helicopter:  700 | 580 | 600 | 550 | 500 | 450 | 420 | 380 | scale
  glider:      thermik | hotliner | f3b | f3k | f3j | f5j | f5b | f5k | f3f | f3l | hangflug | dlg | scale | motorglider
  multicopter: quadcopter | hexacopter | fpv
  boat:        rennboot | segelboot | schlepper | submarine | yacht
  car:         buggy | monstertruck | crawler | tourenwagen | truggy | drift

drive_type — EXAKT einen dieser Werte oder null:
  "electric" | "nitro" | "gas" | "turbine"
  (Segler ohne Motor = null)

completeness — EXAKT einen dieser Werte oder null:
  "RTF" | "ARF" | "BNF" | "PNP" | "kit" | "parts" | "set"

price_euros: Geforderter Preis in Euro als Zahl (nur Zahl, kein Symbol). null wenn kein Preis erkennbar.
shipping_available: true wenn Versand angeboten wird, false wenn explizit kein Versand ("nur Abholung", "kein Versand"), null wenn unklar.

Für "attributes": extrahiere alle weiteren technischen Daten als key-value Paare
(z.B. wingspan_mm, weight_g, battery, motor, scale, channels, servos_included).
Keys immer englisch, snake_case. Werte als Strings.
"""
```

**Step 2: Run full extractor test suite**

```bash
docker compose exec backend pytest tests/test_extractor.py -v
```
Expected: all pass.

**Step 3: Commit**

```bash
git add backend/app/analysis/extractor.py
git commit -m "feat: rewrite LLM prompt with category-aware subtype allowlists"
```

---

### Task 4: One-shot SQL normalization of existing data [approved]

**Files:**
- Modify: `backend/app/main.py` (startup block, same pattern as PLAN-020 NULL-sweep)

This cleans dirty values in existing listings. It runs once at startup, then must be removed in the next release (code comment marks it).

**Step 1: Add normalization block in `main.py` startup, BEFORE `scheduler.start()`**

Locate the PLAN-020 one-shot block. Add a second block immediately after it:

```python
# PLAN-021 one-shot — remove in next release
async with AsyncSessionLocal() as session:
    await session.execute(text("""
        -- Pre-pass: lowercase all existing values so CASE/IN comparisons work correctly
        UPDATE listings SET
            model_type    = LOWER(model_type)    WHERE model_type    IS NOT NULL;
        UPDATE listings SET
            model_subtype = LOWER(model_subtype) WHERE model_subtype IS NOT NULL;

        -- Clamp model_type: set unknown values to NULL
        UPDATE listings SET model_type = NULL
        WHERE model_type IS NOT NULL
          AND LOWER(model_type) NOT IN (
            'airplane','helicopter','multicopter','glider','boat','car'
          );

        -- Normalize airplane subtypes
        UPDATE listings SET model_subtype = CASE LOWER(model_subtype)
            WHEN '3d'            THEN '3d'
            WHEN 'high-wing'     THEN 'hochdecker'
            WHEN 'high_wing'     THEN 'hochdecker'
            WHEN 'highwing'      THEN 'hochdecker'
            WHEN 'low_wing'      THEN 'tiefdecker'
            WHEN 'shoulder_decker' THEN 'mitteldecker'
            WHEN 'aerobatic'     THEN 'aerobatic'
            WHEN 'acro'          THEN 'aerobatic'
            WHEN 'pylon_racer'   THEN 'pylon'
            WHEN 'motor_glider'  THEN NULL
            WHEN 'motorglider'   THEN NULL
            WHEN 'motorsegler'   THEN NULL
            ELSE NULL
        END
        WHERE model_type = 'airplane'
          AND LOWER(model_subtype) NOT IN (
            'jet','warbird','trainer','scale','3d','nurflügler',
            'hochdecker','tiefdecker','mitteldecker','delta','biplane',
            'aerobatic','kit','hotliner','funflyer','speed','pylon'
          );

        -- Normalize glider subtypes
        UPDATE listings SET model_subtype = CASE LOWER(model_subtype)
            WHEN 'thermal'       THEN 'thermik'
            WHEN 'motorglider'   THEN 'motorglider'
            WHEN 'motor_glider'  THEN 'motorglider'
            WHEN 'motor-glider'  THEN 'motorglider'
            WHEN 'motorsegler'   THEN 'motorglider'
            WHEN 'f3j'           THEN 'f3j'
            WHEN 'f5j'           THEN 'f5j'
            WHEN 'f5k'           THEN 'f5k'
            WHEN 'f3b'           THEN 'f3b'
            ELSE NULL
        END
        WHERE model_type = 'glider'
          AND LOWER(model_subtype) NOT IN (
            'thermik','hotliner','f3b','f3k','f3j','f5j','f5b','f5k',
            'f3f','f3l','hangflug','dlg','scale','motorglider'
          );

        -- For all other model_types: clamp unknown subtypes to NULL
        UPDATE listings SET model_subtype = NULL
        WHERE model_type IN ('helicopter','multicopter','boat','car')
          AND model_subtype IS NOT NULL
          AND LOWER(model_subtype) NOT IN (
            -- helicopter
            '700','580','600','550','500','450','420','380','scale',
            -- multicopter
            'quadcopter','hexacopter','fpv',
            -- boat
            'rennboot','segelboot','schlepper','submarine','yacht',
            -- car
            'buggy','monstertruck','crawler','tourenwagen','truggy','drift'
          );
    """))
    await session.commit()
```

**Step 2: Verify in DB after restart**

```bash
docker compose restart backend
docker compose exec db psql -U rcscout -d rcscout -c "
  SELECT model_type, model_subtype, COUNT(*)
  FROM listings WHERE is_sold=false AND model_type IS NOT NULL
  GROUP BY model_type, model_subtype ORDER BY model_type, COUNT(*) DESC
  LIMIT 40;
"
```

Expected: only canonical values visible. No `high-wing`, `3D`, `rc-elektronik` etc.

**Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "fix: one-shot SQL normalization of dirty model_type/subtype data (PLAN-021)"
```

---

## Verification [approved]

**7.1 Unit tests:**
```bash
docker compose exec backend pytest tests/test_vocabulary.py tests/test_extractor.py -v
```
Expected: all pass.

**7.2 DB spot-check after normalization:**
```bash
docker compose exec db psql -U rcscout -d rcscout -c "
  SELECT model_type, model_subtype, COUNT(*)
  FROM listings WHERE is_sold=false
  GROUP BY model_type, model_subtype
  ORDER BY model_type, COUNT(*) DESC;
"
```
Expected: no values outside canonical vocabulary visible for any model_type.

**7.3 Manual LLM spot-check (live):**
Trigger re-analysis of one listing per type via Admin-Panel or:
```bash
docker compose exec backend python -c "
import asyncio
from app.analysis.extractor import analyze_listing
result = asyncio.run(analyze_listing(
    title='Multiplex Easystar RTF mit Motor',
    description='Verkaufe meinen Easystar komplett flugbereit.',
    price='80', condition='gut', category='flugmodelle',
))
print(result)
"
```
Expected: `model_type='airplane'`, `model_subtype` in canonical set or `None`.

**7.4 Check existing tests still pass:**
```bash
docker compose exec backend pytest tests/ -v
```
Expected: all pass.

---

## Reviewer Findings (2026-04-18)

**Blocking — eingearbeitet:**
1. **BLOCKING-1** SQL-Normalisierung ließ Mixed-Case-Werte stehen (LOWER()-Vergleich in WHERE schließt bereits korrekte Werte aus, aber literal `3D` blieb als `3D`). Fix: Pre-pass `UPDATE ... SET model_type = LOWER(model_type)` vor allen anderen Statements.
2. **BLOCKING-2** Fehlende Reviewer-Sektion und Status-Felder. Eingearbeitet.

**Non-Blocking — eingearbeitet:**
- Test `test_clamp_model_subtype_unknown_returns_none` hatte falsche Assertion (`"3D"` → `None`). `"3D".lower() = "3d"` ist kanonisch → gibt `"3d"` zurück. Test korrigiert + separater Test für Case-Normalisierung hinzugefügt.
- Irreführender Kommentar `motorglider only valid for airplane, not glider` invertiert → korrigiert.
- Test für `drive_type` Case-Normalisierung (`"Electric"` → `"electric"`) hinzugefügt.
- Dead CASE-Branches (`WHEN '3d' THEN '3d'`) in SQL belassen (dokumentarisch, harmlos).
- Codex-Pass nicht ausgeführt (Auth-Problem). Non-blocking.

---

## Definition of Done

- `vocabulary.py` neu mit `clamp_model_type`, `clamp_model_subtype`
- `ListingAnalysis` klemmt unbekannte Werte via `model_validator` auf `None`
- Prompt listet Werte als exhaustive Allowlists, nicht als Beispiele
- `drive_type` ebenfalls geclampt
- One-shot SQL hat Bestandsdaten normalisiert
- Alle Tests grün
- One-shot Block als `# PLAN-021 one-shot — remove in next release` markiert
