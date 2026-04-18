# PLAN 020 — Similarity Ranking (weg vom starren Median-Indikator)

> **For Claude:** REQUIRED SUB-SKILL: Use `dglabs.executing-plans` to implement this plan task-by-task.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved (after revise) | 2026-04-18 |
| Human | approved | 2026-04-18 |

---

## Context & Goal

Der heutige Preisindikator gruppiert Listings starr nach `manufacturer + model_name` (L1, ≥5) oder Fallback `model_type + model_subtype + completeness` (L2, ≥5). Die L2-Gruppen sind größenblind und produzieren irreführende Mediane.

**Gemessene Beweise auf Staging (2026-04-18, 3555 aktive Listings):**
- Gruppe `airplane/warbird/RTF`: 15 Inserate, Preisspanne 120 € … 6500 €, Median 1025 €. Aufgesplittet nach Spannweiten-Bucket: Median geht von 120 € (<1 m) bis 2325 € (≥2.5 m) — **20× Spanne**, die der heutige Median glattwäscht.
- Jets nach Hersteller: CARF Median 5500 €, Freewing 283 €, Arrows 75 € — **60× Spanne** innerhalb derselben L2-Gruppe.
- Datenqualität: `manufacturer` 59 %, `model_name` 80 %, `wingspan_mm` (aus `attributes` JSON) nur 24 % und mit 50 Garbage-Werten (`"weight_g"`, `"unbekannt"`, `"2000+"` etc.). Raw-Format-Prüfung zeigt: LLM liefert entweder reine Dezimalstring oder Garbage — keine Einheiten-Suffixe wie `"1800 mm"`.

**Ziel:** Der Preisvergleich wird vom starren Gruppen-Matching auf ein **attribut-gewichtetes Similarity-Ranking** umgestellt. Statt eines einzelnen Mediansatzes bekommt der User eine nach Ähnlichkeit sortierte Liste der Top-N vergleichbaren Listings. Der Median-Indikator bleibt als UI-Scan-Hilfe, wird aber aus den Top-N abgeleitet und **nur angezeigt, wenn das Cluster homogen genug ist** — sonst kein Band, ehrlicher leerer Zustand.

**Nicht-Ziele (explizit out of scope — gehört zu `docs/backlog.md` PRICE-02):**
- Neue DB-Spalte `wingspan_mm` (Integer-Typisierung).
- LLM-Extractor ändern, Modellkatalog aufbauen, Websuche.
- Embedding-basiertes Matching.

## Breaking Changes

**Ja — wörtlich (schemas) und semantisch.**

- `ComparablesResponse` wechselt Semantik: `group_label` und `group_level` werden obsolet, ersetzt durch `match_quality` (siehe Step 1). Frontend wird im selben Commit angepasst.
- `price_indicator` wird in der SQL-Analyse-Pipeline **nicht mehr aus starrem L1/L2-Median gesetzt**. Stattdessen wird der Indikator aus Similarity-Top-N abgeleitet und nur bei homogenem Cluster gesetzt. Listings, die das bisher durch L2 bekommen haben, verlieren ihren Indikator ggf. dauerhaft.
- Side-effect für Telegram-Notifications: `fav_indicator`-Trigger (PLAN_019, `backend/app/telegram/fav_sweep.py:60`) feuert nach dem Umbau seltener und bei anderen Listings. Kein Code-Bruch, aber verändertes Verhalten.
- **Einmal-Migration beim Deploy**: Ein One-shot-SQL leert `price_indicator`, `price_indicator_median`, `price_indicator_count` auf allen Listings, bevor der neue Scheduler-Job zum ersten Mal läuft. Sonst bleiben Alt-Werte unbegrenzt stehen (siehe Reviewer-Finding CRITICAL-1). Details in Step 4b.

Keine DB-Schema-Migration (keine neuen Spalten, keine gelöschten Spalten). Keine Daten-Löschung außer dem genannten One-shot NULL-Sweep.

**Non-Breaking Addition:** `get_comparables` bekommt einen neuen optionalen Query-Parameter `limit: int = 20`. Bestehende Clients ohne `limit` funktionieren unverändert.

## Reference Patterns

- Bestehende Route mit Two-Level-Grouping: `backend/app/api/routes.py:284` (`get_comparables`). Wird in Step 3 komplett ersetzt.
- SQL-Analysejob: `backend/app/analysis/job.py:89` (`recalculate_price_indicators`). Wird in Step 4 neu gebaut auf Basis des Similarity-Scorers.
- Scheduler-Setup für Jobs: `backend/app/main.py` (existierender APScheduler mit `update every 30min`, `recheck every 1h`, `analysis every 2min`, `llm_cascade_refresh every 12h`). Wir registrieren in Step 4a einen neuen **eigenständigen** `price_indicator_recalc` Job — er hängt nicht mehr an der LLM-Analyse.
- Modal-UI: `frontend/src/components/ComparablesModal.tsx`. Median-Darstellung bedingt machen (Step 5).
- Test-Stil Backend: `backend/tests/test_*.py`, fixtures in `conftest.py`. Frontend: Vitest-Globals **nicht** enabled → in jedem Testfile `import { describe, it, expect, vi } from 'vitest'` explizit.

## Test Files

- `backend/tests/test_similarity_scorer.py` — **neu**, Unit-Test des Scorers.
- `backend/tests/test_similarity_homogeneity.py` — **neu**, Unit-Test des Homogenitäts-Helpers.
- `backend/tests/test_comparables_route.py` — **neu**, End-to-End Test der Route.
- `backend/tests/test_analysis_job.py` — **erweitern**, neuer Test dass `price_indicator` nur bei homogenem Cluster gesetzt wird + Scheduler-Job-Trigger unabhängig von LLM-Batch.
- `frontend/src/components/__tests__/ComparablesModal.test.tsx` — **erweitern** oder neu, Fälle „Median sichtbar" / „Median unterdrückt" / „insufficient mit Restliste".

## Assumptions & Risks

- **Scorer-Performance im Analysejob**: Pro Lauf N × Gruppe. Mit Pre-Filter auf `model_type` typisch O(N · 1/10 · N) ≈ 1,2 M Vergleiche für 3500 Listings. Pro Lauf mehrere Sekunden CPU, aber ≤ Minuten. Akzeptabel im 15-min-Intervall.
- **NULL-base-model_type-Listings**: Würde Candidate-Pool auf volle Tabelle explodieren. Mitigation: Listings mit `model_type IS NULL` überspringen wir im Analysejob (setzen `price_indicator = NULL`). In der Route liefern wir trotzdem die Top-N zurück, weil der User ein konkretes Listing betrachtet — nur ohne Median.
- **Wingspan-Nutzung**: Nur ~24 % der Listings haben valide `wingspan_mm`. Scorer bewertet Wingspan-Diff nur wenn **beide** Seiten valide sind.
- **Gewichte & Schwellen sind initial**: Die Werte (Step 2 + 3) sind plausible Startpunkte, aber **nicht** durch Sensitivitätsanalyse belegt. Tuning-Checkpoint nach Step 7.1 (Dry-Run-Stichprobe) ist verpflichtend.
- **Indikator verschwindet für viele Listings** — gewollt. Stop-Signal: Wenn nach Tuning >80 % der aktiven Listings NULL-Indikator haben, Schwellen überdenken.
- **Telegram `fav_indicator`-Trigger**: feuert nach Umbau anders. Human-Bestätigung im BREAK vor Step 8.
- **Sold-Transition**: Wenn ein Listing auf `is_sold=true` wechselt, bleiben seine alten `price_indicator*`-Werte stehen. Akzeptiert — der Badge wird ohnehin nur auf aktiven Listings im Scan-UI gezeigt.

---

## Steps

### Step 1 — Backend: Schema-Anpassung `[approved]`

**Datei:** `backend/app/api/schemas.py`

Ersetze `ComparableListing` und `ComparablesResponse` (Suchbegriffe `class ComparableListing`, `class ComparablesResponse`):

```python
class ComparableListing(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    price: str | None = None
    price_numeric: float | None = None
    condition: str | None = None
    city: str | None = None
    posted_at: datetime | None = None
    is_favorite: bool = False
    similarity_score: float = 0.0  # absteigend sortiert; Default nötig weil ORM das Feld nicht hat


class ComparablesResponse(BaseModel):
    # Semantik-Wechsel: keine starre Gruppe mehr, sondern Top-N ranked by similarity.
    match_quality: Literal["homogeneous", "heterogeneous", "insufficient"]
    # homogeneous:     Top-N einander ähnlich genug → median gesetzt, UI zeigt ihn
    # heterogeneous:   Top-N streuen zu stark → median = None
    # insufficient:    < 4 scorbare Kandidaten → median = None, listings kann 1–3 partielle Treffer enthalten
    median: float | None
    count: int
    listings: list[ComparableListing]
```

`group_label` und `group_level` entfallen ersatzlos. Default-Werte für alle optionalen Felder sind Pflicht — Pydantic-V2 behandelt sie sonst als required, was im Testpfad und bei ORM-Mapping bricht.

---

### Step 2 — Backend: Similarity-Scorer + Homogeneity-Helper `[approved]`

**Datei:** `backend/app/analysis/similarity.py` — **neu**

```python
"""Attribute-weighted similarity scoring between listings + homogeneity assessment.

Transparent, no ML. Weights are tuned by eye and adjustable in one place.
A score is only meaningful in relative terms (ranking), not as an absolute value.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any, Literal

_WINGSPAN_NUMERIC = re.compile(r"^\d+$")


def _parse_wingspan(attrs: dict[str, Any] | None) -> int | None:
    """Return numeric wingspan in mm or None. Filters out LLM garbage like 'weight_g'."""
    if not attrs:
        return None
    raw = attrs.get("wingspan_mm")
    if raw is None:
        return None
    s = str(raw).strip()
    if not _WINGSPAN_NUMERIC.match(s):
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    # plausibility bounds: 100 mm (tiny indoor) to 10 000 mm (large scale)
    return v if 100 <= v <= 10_000 else None


def _eq_ci(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.strip().casefold() == b.strip().casefold()


@dataclass(frozen=True)
class SimilarityWeights:
    model_name: float = 5.0
    manufacturer: float = 3.0
    model_subtype: float = 2.0
    completeness: float = 2.0
    model_type: float = 1.0
    wingspan_penalty_per_mm: float = 0.002  # 500 mm diff → -1.0


DEFAULT_WEIGHTS = SimilarityWeights()


def score(base: Any, candidate: Any, w: SimilarityWeights = DEFAULT_WEIGHTS) -> float:
    """Score similarity between two Listing-like objects (must expose the same attrs as Listing)."""
    s = 0.0
    if _eq_ci(base.model_name, candidate.model_name):
        s += w.model_name
    if _eq_ci(base.manufacturer, candidate.manufacturer):
        s += w.manufacturer
    if _eq_ci(base.model_subtype, candidate.model_subtype):
        s += w.model_subtype
    if _eq_ci(base.completeness, candidate.completeness):
        s += w.completeness
    if _eq_ci(base.model_type, candidate.model_type):
        s += w.model_type

    base_span = _parse_wingspan(base.attributes)
    cand_span = _parse_wingspan(candidate.attributes)
    if base_span is not None and cand_span is not None:
        s -= w.wingspan_penalty_per_mm * abs(base_span - cand_span)

    return s


# -------------------------------------------------------------------------
# Homogeneity assessment — shared between API route and analysis job.
# Centralised here to prevent drift.
# -------------------------------------------------------------------------

# Tunable thresholds
MIN_TOP_SIZE = 4                # < this many scorable candidates → insufficient
MIN_ATTR_AGREEMENT = 0.7        # ≥ this fraction of top must share the attribute with the base
MAX_PRICE_SPREAD = 4.0          # max/min ratio on the prices in top

Quality = Literal["homogeneous", "heterogeneous", "insufficient"]


def assess_homogeneity(base: Any, top: list[tuple[Any, float]]) -> tuple[Quality, float | None]:
    """Decide whether a top-N set is homogeneous and compute a median if so.

    Rules:
    - If |top| < MIN_TOP_SIZE → ('insufficient', None).
    - NULL base attributes are treated as 'not informative' (neutral): they do not
      force heterogeneous. If NONE of {manufacturer, model_subtype+completeness}
      are informative on the base → ('heterogeneous', None) — we cannot judge.
    - Otherwise require ≥ MIN_ATTR_AGREEMENT on each informative base attribute.
    - Price spread max/min (positive prices only) must be ≤ MAX_PRICE_SPREAD.
    """
    n = len(top)
    if n < MIN_TOP_SIZE:
        return ("insufficient", None)

    base_mfr = (base.manufacturer or "").strip().casefold()
    base_sub = (base.model_subtype or "").strip().casefold()
    base_cmp = (base.completeness or "").strip().casefold()

    mfr_informative = bool(base_mfr)
    sub_informative = bool(base_sub) and bool(base_cmp)

    if not mfr_informative and not sub_informative:
        return ("heterogeneous", None)

    if mfr_informative:
        mfr_hits = sum(
            1 for c, _ in top
            if (c.manufacturer or "").strip().casefold() == base_mfr
        )
        if mfr_hits / n < MIN_ATTR_AGREEMENT:
            return ("heterogeneous", None)

    if sub_informative:
        sub_hits = sum(
            1 for c, _ in top
            if (c.model_subtype or "").strip().casefold() == base_sub
            and (c.completeness or "").strip().casefold() == base_cmp
        )
        if sub_hits / n < MIN_ATTR_AGREEMENT:
            return ("heterogeneous", None)

    prices = [float(c.price_numeric) for c, _ in top
              if c.price_numeric is not None and c.price_numeric > 0]
    if not prices:
        return ("heterogeneous", None)
    if max(prices) / min(prices) > MAX_PRICE_SPREAD:
        return ("heterogeneous", None)

    return ("homogeneous", statistics.median(prices))
```

**Test: `backend/tests/test_similarity_scorer.py` — neu.** Cases:
- Identische Attribute → Summe aller Einzelgewichte.
- Nur `manufacturer` gleich → nur `w.manufacturer`.
- Wingspan-Diff 500 mm → Score um `1.0` reduziert.
- Wingspan-Wert `"weight_g"` (Garbage) → kein Einfluss.
- Casing-Unterschied (`CARF` vs `Carf`) → zählt als gleich.
- Listing mit komplett NULL-Attributen → Score 0.0.

**Test: `backend/tests/test_similarity_homogeneity.py` — neu.** Cases:
- 3 Treffer → `("insufficient", None)`.
- 6 Treffer mit 100 % Mfr-Agreement, 100 % Sub-Agreement, Preis 100–300 (3× Spread) → `("homogeneous", median=200)`.
- 6 Treffer mit 50 % Mfr-Agreement → `("heterogeneous", None)`.
- 6 Treffer mit 100 % Agreement aber Preis 100–500 (5× Spread) → `("heterogeneous", None)`.
- Base ohne Manufacturer, aber mit Subtype+Completeness 100 % agreement + Preis ok → `("homogeneous", …)`.
- Base ohne jede informative Attribute → `("heterogeneous", None)`.

---

### Step 3 — Backend: Route `/listings/{id}/comparables` `[approved]`

**Datei:** `backend/app/api/routes.py` — ersetze `get_comparables`-Funktion (ab `@router.get("/listings/{listing_id}/comparables"`).

```python
from app.analysis.similarity import (
    score as similarity_score,
    assess_homogeneity,
)

@router.get("/listings/{listing_id}/comparables", response_model=ComparablesResponse)
async def get_comparables(
    listing_id: int,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ComparablesResponse:
    """Return the top-N most similar listings, ranked by attribute similarity."""
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    fav_ids = await _get_favorite_listing_ids(current_user.id, session)

    base_q = (
        select(Listing)
        .where(Listing.is_sold == False)  # noqa: E712
        .where(Listing.price_numeric.is_not(None))
        .where(Listing.id != listing_id)
    )
    if listing.model_type:
        base_q = base_q.where(Listing.model_type == listing.model_type)

    candidates = list((await session.execute(base_q)).scalars().all())

    scored = [(c, similarity_score(listing, c)) for c in candidates]
    # Filter > 0.0: ohne jeden Attribut-Treffer ist Vergleich nicht aussagekräftig.
    # Negative Scores (reine Wingspan-Diff ohne Attribut-Treffer) bewusst verworfen —
    # bei Kandidatenmangel resultiert `insufficient`, was ehrlicher ist als schlechte Vergleiche.
    scored = [(c, s) for c, s in scored if s > 0.0]
    # Deterministic tie-break: score desc, price asc, id asc (stabil für Snapshot-Tests).
    scored.sort(key=lambda t: (-t[1], float(t[0].price_numeric or 0), t[0].id))
    top = scored[:limit]

    quality, median_val = assess_homogeneity(listing, top)

    return ComparablesResponse(
        match_quality=quality,
        median=median_val,
        count=len(top),
        listings=[_to_comparable(c, s, fav_ids) for c, s in top],
    )


def _to_comparable(row: Listing, score_val: float, fav_ids: set[int]) -> ComparableListing:
    # Construct via explicit kwargs — model_validate() would fail on similarity_score
    # which is not an ORM attribute.
    return ComparableListing(
        id=row.id,
        title=row.title,
        url=row.url,
        price=row.price,
        price_numeric=float(row.price_numeric) if row.price_numeric is not None else None,
        condition=row.condition,
        city=row.city,
        posted_at=row.posted_at,
        is_favorite=row.id in fav_ids,
        similarity_score=round(score_val, 2),
    )
```

**Test: `backend/tests/test_comparables_route.py` — neu.** Cases:
- Response hat `match_quality ∈ {homogeneous, heterogeneous, insufficient}`.
- Homogenes Set → `median` gesetzt.
- Heterogenes Set → `median = None`, `listings` trotzdem befüllt.
- `similarity_score` absteigend sortiert, Tie-Break per Preis aufsteigend.
- Kein Self-Match in `listings` (explizite Assertion).
- Base-Listing ohne `model_type` → keine SQL-Filterung, liefert trotzdem sinnvoll.
- Base-Listing ohne Manufacturer & ohne Subtype → `heterogeneous`.

---

### Step 4 — Backend: Analysejob neu `[approved]`

**Datei:** `backend/app/analysis/job.py`

**4a) Neue Scheduler-Registrierung in `backend/app/main.py`:**

Der bestehende `run_analysis_job` ruft `recalculate_price_indicators()` nur nach erfolgreicher LLM-Batch-Verarbeitung auf (early-return bei leerer Queue, `job.py:38-40` + `job.py:85`). Für den neuen Indikator brauchen wir eine **unabhängige** Scheduling-Regel.

- **Entferne** den Aufruf `await recalculate_price_indicators()` aus `run_analysis_job` (Zeile 85).
- **Füge** in `main.py` im APScheduler-Setup einen neuen Job hinzu: `recalculate_price_indicators` alle **15 Minuten**.
- Logging analog zu den bestehenden Jobs. Konkret: den Scheduler-Log-String in `backend/app/main.py:103-106` (f-string-Liste der geplanten Jobs) um `price_indicator_recalc every 15min` erweitern.

**4b) One-shot NULL-Sweep bei Deploy:**

In `backend/app/main.py` in der Startup-Sequenz, **einmalig nach Migration-Deploy**, **vor `scheduler.start()`** (sonst kann der erste Recalc auf einer halb-gesweepten Tabelle laufen):

```python
# Migration marker — run once, then remove. Alembic would be overkill for a single statement.
async with AsyncSessionLocal() as session:
    await session.execute(text("""
        UPDATE listings SET
            price_indicator = NULL,
            price_indicator_median = NULL,
            price_indicator_count = NULL
        WHERE price_indicator IS NOT NULL
    """))
    await session.commit()
```

Dieser Block wird **mit dem Release entfernt**, das auf das PLAN-020-Release folgt (als Code-Kommentar markieren: `# PLAN-020 one-shot — remove in next release`). Rationale: nur so ist garantiert, dass ab Startup nur noch der neue Scheduler-Job Indikatoren setzt — sonst bleiben Alt-Werte je nach `manufacturer`/`model_type`-Kombination beliebig lange stehen.

**4c) `recalculate_price_indicators` neu:**

```python
from collections import defaultdict
from app.analysis.similarity import (
    score as similarity_score,
    assess_homogeneity,
)


async def recalculate_price_indicators() -> None:
    """Set price indicator only when the per-listing similarity cluster is homogeneous.

    For each active priced listing with a non-NULL model_type:
      - Build candidate pool from same model_type.
      - Score + rank.
      - Assess homogeneity of top-20.
      - Set deal/fair/expensive only when homogeneous; otherwise NULL.
    Listings without model_type get price_indicator = NULL (unscorable).
    """
    async with AsyncSessionLocal() as session:
        all_rows = (await session.execute(
            select(Listing).where(
                Listing.is_sold == False,       # noqa: E712
                Listing.price_numeric.is_not(None),
            )
        )).scalars().all()

    by_type: dict[str | None, list[Listing]] = defaultdict(list)
    for r in all_rows:
        by_type[r.model_type].append(r)

    updates: list[tuple[int, str | None, float | None, int]] = []

    for base in all_rows:
        if not base.model_type:
            updates.append((base.id, None, None, 0))
            continue

        candidates = [c for c in by_type[base.model_type] if c.id != base.id]
        scored = [(c, similarity_score(base, c)) for c in candidates]
        scored = [(c, s) for c, s in scored if s > 0.0]
        scored.sort(key=lambda t: (-t[1], float(t[0].price_numeric or 0)))
        top = scored[:20]

        quality, median_val = assess_homogeneity(base, top)

        if quality != "homogeneous" or median_val is None:
            updates.append((base.id, None, None, len(top)))
            continue

        base_p = float(base.price_numeric)
        if base_p <= median_val * 0.75:
            ind = "deal"
        elif base_p >= median_val * 1.25:
            ind = "expensive"
        else:
            ind = "fair"
        updates.append((base.id, ind, median_val, len(top)))

    # Bulk update in chunks via executemany-style loop. 3500 rows × ~1 ms round-trip
    # is acceptable for a 15-min job.
    async with AsyncSessionLocal() as session:
        for lid, ind, med, cnt in updates:
            await session.execute(
                text("""
                    UPDATE listings SET
                        price_indicator = :ind,
                        price_indicator_median = :med,
                        price_indicator_count = :cnt
                    WHERE id = :lid
                """),
                {"lid": lid, "ind": ind, "med": med, "cnt": cnt},
            )
        await session.commit()

    logger.info(
        "price_indicator recalc: processed %d listings, %d homogeneous",
        len(updates),
        sum(1 for _, ind, _, _ in updates if ind is not None),
    )
```

**Test-Erweiterung:** `backend/tests/test_analysis_job.py`.
- Fixture mit 5 sehr ähnlichen Listings gleicher Marke/Größe → alle bekommen `price_indicator`.
- Fixture mit 5 Listings stark unterschiedlicher Größe → `price_indicator` bleibt NULL.
- Listing ohne `model_type` → `price_indicator = NULL`, kein Crash.
- Idempotenz: zweimal aufrufen → gleiches Ergebnis.
- Scheduler-Registrierung (smoke test in `test_main.py` sofern existent, sonst einfach manuell in Verification).

---

### Step 5 — Frontend: Types + Modal `[approved]`

**Datei:** `frontend/src/types/api.ts`

Passe an:
```typescript
export interface ComparableListing {
  id: number;
  title: string;
  url: string;
  price: string | null;
  price_numeric: number | null;
  condition: string | null;
  city: string | null;
  posted_at: string | null;
  is_favorite: boolean;
  similarity_score: number;
}

export type MatchQuality = "homogeneous" | "heterogeneous" | "insufficient";

export interface ComparablesResponse {
  match_quality: MatchQuality;
  median: number | null;
  count: number;
  listings: ComparableListing[];
}
```
`group_label` und `group_level` entfallen.

**`frontend/src/api/client.ts:158` (`getComparables`)** — keine Signaturänderung nötig (nur Typ-Reimport über `types/api.ts`). Explizit bestätigen im Coder-Pass.

**Datei:** `frontend/src/components/ComparablesModal.tsx`

- Kopfzeile je `match_quality`:
  - `"homogeneous"`: „{count} ähnliche Inserate · Median {median} €"
  - `"heterogeneous"`: „{count} ähnliche Inserate · Preisspanne zu groß für Median"
  - `"insufficient"`: „Zu wenige vergleichbare Inserate ({count})" — Liste wird trotzdem gezeigt, falls 1–3 Treffer da sind (als partielle Hilfe).
- Median-Linie im sortierten View nur wenn `median !== null`.
- Pro-Listing Similarity-Label (3 Stufen) statt roher Zahl. Boundaries: Index in sortierter Top-N:
  - `idx < count/3` → „sehr ähnlich"
  - `idx < 2*count/3` → „ähnlich"
  - sonst → „entfernt"
- Sortierung default `similarity_score` desc (Backend liefert schon so). Kein UI-Sort-Toggle in diesem Plan.

**Test-Datei:** `frontend/src/components/__tests__/ComparablesModal.test.tsx` (erweitern / neu).

Beachte: Vitest-Globals sind **nicht** enabled → jedes Testfile beginnt mit
```typescript
import { describe, it, expect, vi } from 'vitest';
```

Cases:
- `match_quality === "homogeneous"` → Median-Kopfzeile + Median-Linie sichtbar.
- `match_quality === "heterogeneous"` → „Preisspanne zu groß" Kopfzeile, keine Median-Linie.
- `match_quality === "insufficient"` mit 2 Listings → Kopfzeile „Zu wenige…", beide Listings werden gerendert.
- Similarity-Labels „sehr ähnlich" / „ähnlich" / „entfernt" korrekt verteilt auf 9 Listings (3/3/3).

---

### Step 6 — Frontend: Scan-UI (Grid/Cards) unverändert `[approved]`

Keine Änderung am `PriceIndicatorBadge` selbst. Die Badges zeigen weiterhin `deal`/`fair`/`expensive` — aber weil der Analysejob jetzt strenger setzt, werden nach dem ersten Lauf viele Listings **keinen Badge mehr** haben. Gewolltes Verhalten, kein Code-Change.

---

### BREAK — Human-Bestätigung

Vor Step 7 (Verification) bestätigt Human:
1. Das veränderte Feuerverhalten der `fav_indicator`-Telegram-Benachrichtigungen (seltener, andere Trigger) ist akzeptiert.
2. Der one-shot NULL-Sweep zum Deploy ist akzeptiert (alle aktuellen Badges verschwinden bis der neue Job durchläuft, ~15 Min).

---

### Step 7 — Verification `[approved]`

**7.1 Tests & Typecheck lokal:**
```bash
docker compose up -d
docker compose exec backend pytest tests/test_similarity_scorer.py tests/test_similarity_homogeneity.py tests/test_comparables_route.py tests/test_analysis_job.py -v
cd frontend && npm run test -- ComparablesModal
cd frontend && npm run typecheck
```

**7.2 Dry-Run gegen Staging-Dump (bereits lokal eingespielt, 3555 aktive Listings):**
```bash
# Wall-clock messen — O(N²) innerhalb model_type, bei ungleichen Buckets kann das entgleisen.
# Zielwert: < 60 s. Bei > 180 s Step-4c Performance nachbessern (z. B. model_type-Buckets vorsortieren).
time docker compose exec backend python -c "
import asyncio
from app.analysis.job import recalculate_price_indicators
asyncio.run(recalculate_price_indicators())
"
docker compose exec db psql -U rcscout -d rcscout -c "
  SELECT COALESCE(price_indicator, 'NULL') AS ind, COUNT(*)
  FROM listings WHERE is_sold=false AND price_numeric IS NOT NULL
  GROUP BY ind ORDER BY COUNT(*) DESC;
"
```

**Tuning-Checkpoint (verpflichtend):**
- Wenn `NULL`-Anteil ≤ 80 % und > 20 % der Listings einen Indikator haben → Schwellen akzeptieren, weiter zu 7.3.
- Wenn `NULL`-Anteil > 80 % → Schwellen zu streng. `MIN_ATTR_AGREEMENT` auf 0.6, oder `MAX_PRICE_SPREAD` auf 5.0 testen, neu messen.
- Wenn `NULL`-Anteil < 20 % → Schwellen zu lax. Nicht realistisch für diese Daten, wahrscheinlicher Bug in Homogeneity-Helper.

**7.3 Stichprobe am Problemfall:**
```bash
# Warbird-RTF Listing aus dem Screenshot (ID im Staging-Dump ermitteln)
curl -s -H "Cookie: <auth>" http://localhost:8000/api/listings/<ID>/comparables | jq '.match_quality, .median, (.listings | length)'
```
Erwartung: `heterogeneous`, `median = null`, Top-N merklich homogener als die heutige L2-Gruppe (manuelle Sichtkontrolle).

**7.4 Scheduler-Hook:**
- Backend neu starten.
- Log prüfen: `price_indicator recalc: processed N listings, M homogeneous` muss nach ~15 Min kommen **unabhängig** davon, ob LLM-Queue leer ist.

---

### Step 8 — Docs: architektur.md erweitern `[approved]`

**Datei:** `docs/architektur.md`

Neuer Abschnitt „Preisvergleich & Similarity-Ranking" am Ende. Inhalt:
- Entscheidung: attribut-gewichteter Scorer statt starrer L1/L2-Gruppen.
- Zentrale Module: `backend/app/analysis/similarity.py` (Scorer + `assess_homogeneity`), Verwendung in `routes.py::get_comparables` und `analysis/job.py::recalculate_price_indicators`.
- Scheduling: eigenständiger APScheduler-Job alle 15 min, unabhängig von LLM-Queue.
- Indikator wird nur bei homogenem Cluster gesetzt — bewusste Stille-by-default.
- Tunables an einer Stelle: `SimilarityWeights`, `MIN_TOP_SIZE`, `MIN_ATTR_AGREEMENT`, `MAX_PRICE_SPREAD`.

Kurz halten (~30–50 Zeilen), Stil analog zu bestehenden Abschnitten.

---

## Definition of Done

- Alle Tests grün (backend + frontend).
- Typecheck sauber.
- Dry-Run im Staging-Dump zeigt plausible NULL-Verteilung (Schwelle siehe 7.2).
- Manueller Check im Modal mit 2–3 verschiedenen Listings zeigt erkennbar bessere Vergleichbarkeit.
- Scheduler-Job läuft unabhängig von LLM-Queue (7.4 bestätigt).
- `docs/architektur.md` erweitert um einen neuen Abschnitt „Preisvergleich & Similarity-Ranking" (dort gibt es bisher nichts dazu).
- Backlog PRICE-01 als erledigt markiert, PRICE-02 bleibt offen.
- One-shot NULL-Sweep-Code ist deploy-kommentiert (`# PLAN-020 one-shot — remove in next release`).

---

## Reviewer Findings (2026-04-18)

Reviewer: `dglabs.agent.review-plan` + (Codex: 401 auth error, nicht ausgeführt).

**Blocking — alle eingearbeitet:**

1. **CRITICAL-1** `recalculate_price_indicators` wird nicht alle 2 min gerufen (early-return in `run_analysis_job` bei leerer LLM-Queue). → **Fix**: eigener APScheduler-Job alle 15 min (Step 4a) + einmaliger NULL-Sweep beim Deploy (Step 4b).
2. **CRITICAL-2** `ComparableListing.model_validate(row)` schlägt fehl, weil `similarity_score` kein ORM-Feld ist und ohne Default required ist. → **Fix**: explizite kwargs in `_to_comparable` (Step 3) + Default `= 0.0` am Schema (Step 1).
3. **HIGH-1** Homogeneity-Helper muss konkret in Step 2 ausformuliert werden, nicht nur als Hinweis. → **Fix**: `assess_homogeneity` voll ausgeschrieben in Step 2, von Route und Job identisch verwendet.
4. **HIGH-4** `sub_hits` wurde 0 wenn `base.model_subtype` NULL → automatisch heterogeneous. → **Fix**: NULL-Base-Attribute werden als „not informative" behandelt, fallen aus der Prüfung raus. Wenn ALLE informative Attribute fehlen → heterogeneous (konsistent, da keine Basis für Homogenitätsurteil).

**Non-blocking — eingearbeitet:**

- **HIGH-3**: Tuning-Checkpoint nach Dry-Run in 7.2 verpflichtend.
- **MED-1**: Vitest-Globals-Hinweis in Step 5 eingefügt.
- **MED-2**: Schema-Kommentar + UI-Copy klargestellt: `insufficient` zeigt 1–3 partielle Listings.
- **MED-4**: Listings ohne `model_type` werden im Analysejob übersprungen (Indikator = NULL), Route liefert sie trotzdem aus.
- **LOW-1**: Staging-Messung bestätigt: LLM schreibt entweder reine Zahlen oder Garbage-Strings, keine Einheiten-Mischformate → Regex `^\d+$` ausreichend.
- **LOW-3**: Tie-Breaker explizit `price_numeric asc` bei gleichem Score.
- **LOW-4**: Similarity-Label-Boundaries (Top-1/3, Middle-1/3, Bottom-1/3) in Step 5 definiert.
- **SUGGESTION-2**: Upper-Bound 80 % NULL-Ratio als Stop-Signal im Tuning-Checkpoint.

**Nicht kritisch, offen gelassen:**
- **HIGH-2** (bulk update in einzelnen UPDATEs): bei 3500 Rows pro 15-min-Job akzeptabel, Optimierung später falls Performance ein Problem wird.
- **MED-3**: durch CRITICAL-1 Fix + One-shot-Sweep gelöst.
- **SUGGESTION-1**: Plan-Context referenziert jetzt explizit `docs/backlog.md PRICE-02`.
- **SUGGESTION-3**: DoD ruft explizit die **Neuanlage** eines Architektur-Abschnitts auf.

**Codex-Cross-Review ausständig**: CLI-Auth (`codex login`) bei nächster Gelegenheit erneuern, dann Re-Review für Second Opinion. Nicht blockierend — Agent-Pass hat alle Blocker abgedeckt.
