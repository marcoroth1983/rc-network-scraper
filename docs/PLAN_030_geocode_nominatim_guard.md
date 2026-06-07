# Geocoding Nominatim Numeric-Query Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Stop the geocoder from sending a bare numeric "city" (e.g. `"2450"`) to Nominatim, which silently resolves it to an arbitrary country (observed: Austria PLZ 2450 → Coffs Harbour, Australia → 16230.9 km).

**Architecture:** `_geo_lookup` in `orchestrator.py` has a 5-step fallback chain. Steps 1–4 use local geodata tables; Step 5 falls back to the Nominatim OSM geocoder. Step 5 currently fires whenever a `city` string exists — including when that string is only digits, which carries no country context. The fix adds a single guard: Nominatim is only queried when the place string contains at least one alphabetic character. No schema, endpoint, or API changes.

**Tech Stack:** Python 3.12, SQLAlchemy async, pytest / pytest-asyncio, PostgreSQL 16.

**Breaking Changes:** No. A non-resolvable bare-PLZ listing now stores `NULL` coordinates (→ no distance shown) instead of wrong coordinates. Pre-existing listings with wrong coordinates are explicitly **out of scope** (Human decision: do not migrate old data).

**Out of scope (explicit):**
- Backfilling / correcting already-scraped listings that hold wrong coordinates.
- Changing the parser's 5-digit German PLZ regex (`parser.py:14`). 4-digit AT/CH PLZ continue to flow through the `city` field and Step 3.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-06-07 |
| Human | approved | 2026-06-07 |

---

## Context

**Root cause (verified by reading code + distance computation):**

1. Listing location raw `"2450"` → `parser._parse_location` (`backend/app/scraper/parser.py:84-115`). `_PLZ_RE = ^\d{5}$` (`parser.py:14`) requires exactly 5 digits, so `"2450"` is not a PLZ → returns `(plz=None, city="2450")`.
2. `_geo_lookup(plz=None, city="2450")` (`backend/app/scraper/orchestrator.py:200-270`):
   - Step 1 / Step 2 skipped (`norm_plz` is `None`).
   - Step 3 (`orchestrator.py:230-244`) extracts `"2450"` from the city string and queries `intl_geodata` for AT then CH. **Returns nothing when `intl_geodata` lacks AT 2450** (see Seed Note below).
   - Step 4 (`orchestrator.py:246-258`) strips the leading PLZ from the city → empty string → skipped.
   - Step 5 (`orchestrator.py:260-268`) sets `query = city.strip() = "2450"` and calls Nominatim. Nominatim has no country bias param → resolves `"2450"` to Coffs Harbour, AU (-30.3, 153.1). Distance from Diepholz (49356 ≈ 52.6 N, 8.4 E) = **16231.7 km**, matching the reported 16230.9 km.

**Computation cross-check:** AT 2450 (Mannersdorf, 48.0 N / 16.6 E) → ~774 km. AU 2450 → ~16232 km. Only the Australian coordinates fit the reported value. lat/lon swap and `(0,0)` default were ruled out (would give ~5283/10411/5901 km).

**Canonical reference — function under change:** `backend/app/scraper/orchestrator.py:260-268` (Step 5 block). Full current code:

```python
    # Step 5: Nominatim fallback — only when a city name is available.
    # Bare PLZ numbers without country context would resolve to any country (e.g. "2450" → Australia).
    query = city.strip() if city else None
    if query:
        await asyncio.sleep(1.0)  # respect Nominatim 1 req/sec ToS
        coords = await _nominatim_geocode(query)
        if coords:
            logger.info("Nominatim resolved %r / %r → %.4f, %.4f", plz, city, coords[0], coords[1])
            return coords[0], coords[1], plz

    return None, None, plz
```

The comment already documents the danger; the guard implementing it is missing. This is the only code defect.

**`intl_geodata` model** (`backend/app/models.py:72-79`): columns `country` (String(2), PK), `plz` (String(10), PK), `city`, `lat` (Float), `lon` (Float). Lookup SQL `_INTL_GEO_LOOKUP_SQL` (`orchestrator.py:134-139`): `SELECT lat, lon FROM intl_geodata WHERE country = :country AND plz = :plz LIMIT 1`.

**Seed Note (VERIFIED on dev 2026-06-07):** `intl_geodata` is seeded (AT 2217, CH 3362 distinct PLZ). The original "table empty" hypothesis was **wrong**: the table is populated, but **PLZ 2450 is genuinely absent from the GeoNames AT export** (neighbours 2444/2451/2452 exist, 2450 is a gap). So Step 3 missed for a data-source reason, not a seeding reason, and Step 5 then sent "2450" to Nominatim → Australia. After the guard, such GeoNames gaps resolve to NULL (no distance) instead of a wrong country. `seed_intl.py` is a manual one-time script; staging/prod seed state was not checked from the planning host. Residual limitation: AT/CH PLZ missing from GeoNames show no distance — candidate for `docs/limitations.md` (pending Human confirmation).

**Test conventions (mirror references):**
- Async DB integration tests use the `db_session` fixture and insert rows via `text(...)`. Canonical reference: `backend/tests/test_orchestrator_phases.py:20-60` (`@pytest.mark.asyncio` + `@pytest.mark.integration`, `db_session`, `patch(...)` for network).
- `clean_listings` (`backend/tests/conftest.py:161-172`) truncates `listings`, `users`, `plz_geodata` but **NOT `intl_geodata`** — the new test must `DELETE FROM intl_geodata` itself and insert the rows it needs.
- Network is mocked by patching the module-level function, e.g. `patch("app.scraper.orchestrator._nominatim_geocode", new=AsyncMock(...))`.

---

### Task 1: Add numeric-only Nominatim guard [DONE]

**Files:**
- Modify: `backend/app/scraper/orchestrator.py:260-268`

**Step 1: Implement**

Replace the Step 5 block (`orchestrator.py:260-268`) with:

```python
    # Step 5: Nominatim fallback — only when a real place NAME is available.
    # A bare numeric token (e.g. "2450") carries no country context and Nominatim
    # resolves it to an arbitrary country (observed: "2450" → Coffs Harbour, Australia,
    # giving a ~16000 km distance). Require at least one alphabetic character so only
    # genuine place names reach the geocoder; pure-digit strings fall through to NULL.
    query = city.strip() if city else None
    if query and any(c.isalpha() for c in query):
        await asyncio.sleep(1.0)  # respect Nominatim 1 req/sec ToS
        coords = await _nominatim_geocode(query)
        if coords:
            logger.info("Nominatim resolved %r / %r → %.4f, %.4f", plz, city, coords[0], coords[1])
            return coords[0], coords[1], plz

    return None, None, plz
```

Only the guard condition (`and any(c.isalpha() for c in query)`) and the comment change. The `return None, None, plz` tail line is unchanged — keep it.

**Step 2: Commit**

```bash
git add backend/app/scraper/orchestrator.py
git commit -m "fix: guard Nominatim geocode against bare numeric queries (PLAN-030)"
```

---

### Task 2: Tests for the geo-lookup Nominatim guard [DONE]

**Depends on:** Task 1

**Files:**
- Create: `backend/tests/test_geo_lookup.py`
- Test: `backend/tests/test_geo_lookup.py`

**Reuse check:** No existing test covers `_geo_lookup`. Mirrors the async-integration setup at `test_orchestrator_phases.py:20-60` (`db_session` + `@pytest.mark.integration` + `patch`). New: a local `_clean_intl` helper because `clean_listings` does not truncate `intl_geodata` (`conftest.py:161-172`).

**Step 1: Write tests**

One behavior per test:

```python
"""Tests for orchestrator._geo_lookup fallback chain — Nominatim numeric guard."""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scraper.orchestrator import _geo_lookup


async def _reset_intl(session: AsyncSession) -> None:
    """intl_geodata is not cleaned by the autouse clean_listings fixture."""
    await session.execute(text("DELETE FROM intl_geodata"))
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bare_numeric_city_does_not_call_nominatim(db_session: AsyncSession):
    """A pure-digit 'city' (e.g. '2450') must NOT be sent to Nominatim and resolves to NULL."""
    await _reset_intl(db_session)
    mock_geocode = AsyncMock(return_value=(-30.3, 153.1))  # would be Australia if called
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="2450")
    mock_geocode.assert_not_awaited()
    assert lat is None
    assert lon is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_named_city_still_uses_nominatim_fallback(db_session: AsyncSession):
    """A real place name with no local match still reaches the Nominatim fallback."""
    await _reset_intl(db_session)
    mock_geocode = AsyncMock(return_value=(47.0, 15.4))
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode), \
         patch("app.scraper.orchestrator.asyncio.sleep", new=AsyncMock()):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="IrgendwoinÖsterreich")
    mock_geocode.assert_awaited_once()
    assert (lat, lon) == (47.0, 15.4)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_austrian_plz_resolves_from_intl_geodata(db_session: AsyncSession):
    """When intl_geodata holds AT 2450, the bare-PLZ city resolves locally without Nominatim."""
    await _reset_intl(db_session)
    await db_session.execute(text(
        "INSERT INTO intl_geodata (country, plz, city, lat, lon) "
        "VALUES ('AT', '2450', 'Mannersdorf', 48.0, 16.6)"
    ))
    await db_session.commit()
    mock_geocode = AsyncMock(return_value=(-30.3, 153.1))
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="2450")
    mock_geocode.assert_not_awaited()
    assert (lat, lon) == (48.0, 16.6)
    assert plz == "2450"
```

**Step 2: Commit**

```bash
git add backend/tests/test_geo_lookup.py
git commit -m "test: cover Nominatim numeric guard and AT intl_geodata resolution (PLAN-030)"
```

---

_Code review closed 2026-06-07 (python, cycle 1): CLEAN — 0 blocking, 3 suggestions (no action)._

## Verification

### A. Automated (run once, after all tasks)

From the backend container (per project `CLAUDE.md`):

```bash
docker compose exec backend pytest tests/test_geo_lookup.py tests/test_distance.py -v
```

Expect: all three new `test_geo_lookup` tests pass, existing `test_distance` tests still pass.

Full suite (regression):

```bash
docker compose exec backend pytest tests/ -q
```

### B. Operational — `intl_geodata` seed check (Human / deploy step, NOT a code task)

The code guard prevents *wrong* distances. For AT/CH listings to show a *correct* distance, `intl_geodata` must be seeded. Verify on each environment (dev, then staging VPS) via psql — is the table populated, and is AT 2450 present?

```bash
docker compose exec db psql -U rcscout -d rcscout -c \
  "SELECT country, count(*) FROM intl_geodata GROUP BY country;"
docker compose exec db psql -U rcscout -d rcscout -c \
  "SELECT * FROM intl_geodata WHERE plz = '2450';"
```

If the table is empty or AT 2450 is missing, seed it (one-time, downloads AT+CH from GeoNames, free):

```bash
docker compose exec backend python -m app.seed_intl
```

Do **not** pass `--backfill` (that would re-touch existing listings — out of scope per Human decision; and it only re-runs `latitude IS NULL` rows anyway, which the wrong-coordinate rows are not).

Report the seed counts back to the Human. Repeat on the staging VPS via the SSH/docker commands in project `CLAUDE.md`.
