# Auto-Scrape, Background Jobs & Favorites Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Replace blocking manual scrape with a background job + 4h cron, add sold-recheck rotation, listing cleanup, and a favorites/Merkliste feature.

**Architecture:** APScheduler runs a 4h cron inside the FastAPI process. `POST /api/scrape` now returns immediately and runs a background asyncio task; frontend polls `GET /api/scrape/status` every 3s. Scrape has three phases: (1) stop-early new-listing crawl (max 25 pages cap), (2) sold-recheck of 50 oldest non-sold listings, (3) cleanup of stale/sold records. Favorites stored as `is_favorite` boolean on `listings` — single user, no join overhead. A modal ("Merkliste") in the header shows all favorited listings with sold marking and remove button.

**Tech Stack:** Python/FastAPI, APScheduler 3.x (asyncio, already pinned `>=3.10`), SQLAlchemy async, React 19/TypeScript, Tailwind CSS

**Breaking Changes:** Yes — `POST /api/scrape` response shape changes from `ScrapeSummary` to `{status: "started"}`. Frontend ScrapeButton must be updated in the same deployment. Rolling back requires reverting both backend and frontend together.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-07 |
| Human | approved | 2026-04-07 |

---

## Reference Patterns

- Session factory: `app/db.py` — `AsyncSessionLocal`, `get_session`, `init_db` (already uses `ALTER TABLE … ADD COLUMN IF NOT EXISTS` pattern)
- Upsert pattern: `app/scraper/orchestrator.py` — `_upsert_listing`, `_geo_lookup`
- API route pattern: `app/api/routes.py`
- Schema pattern: `app/api/schemas.py`
- Test fixtures: `tests/conftest.py` — `api_client: AsyncClient`, `db_session: AsyncSession`, `load_fixture(name)`
- Test pattern: `tests/test_api.py` — `async def test_…(api_client, db_session)` with `_insert_listing` helper
- Frontend card: `frontend/src/components/ListingCard.tsx`
- Frontend API client: `frontend/src/api/client.ts`
- Frontend types: `frontend/src/types/api.ts`

---

## Assumptions & Risks

- **APScheduler first run:** The 4h interval job does NOT fire on startup — first auto-scrape happens 4h after process start. This is intentional; user can trigger manually via the button.
- **Phase 1 safety cap:** `MAX_PAGES = 25` prevents runaway crawling if the stop-early logic encounters a parser regression.
- **`scraped_at` dual meaning:** After this plan, `scraped_at` means "last time this listing was fetched and parsed" (either as new listing in phase1 OR as recheck in phase2). Downstream code only uses it as an index and display field — no behavioral dependency.
- **Listings without `posted_at`:** Phase 3 cleanup skips them (handled by `AND posted_at IS NOT NULL`). They live until manually deleted. Documented in limitations.md.

---

## Task 1: DB — Add `is_favorite` column [ ]

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`

**Step 1: Add column to ORM model**

In `backend/app/models.py`, add after the `is_sold` line:

```python
is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

**Step 2: Add migration in init_db**

In `backend/app/db.py`, inside `init_db()` after the existing `ALTER TABLE` for `is_sold`, add:

```python
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT FALSE"
))
```

**Step 3: Verify migration is idempotent**

```bash
docker compose exec backend python -c "
import asyncio
from app.db import init_db
asyncio.run(init_db())
print('OK')
"
```

Expected: `OK`. Run a second time — must not error.

**Step 4: Verify column exists in DB**

```bash
docker compose exec db psql -U rcscout -c "\d listings"
```

Expected: `is_favorite` column appears with type `boolean`, default `false`.

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/db.py
git commit -m "feat: add is_favorite column to listings table"
```

---

## Task 2: Crawler — Add `fetch_page` helper [ ]

**Files:**
- Modify: `backend/app/scraper/crawler.py`
- Modify: `backend/tests/test_crawler.py`

The orchestrator's phase1 needs to fetch one page at a time. Currently `fetch_listings` handles pagination internally and cannot stop mid-way. Add a `fetch_page` function that takes an existing httpx client and returns listings for a single page URL. No new test dependencies — use the existing `load_fixture` helper and call `_extract_listings` directly where possible.

**Step 1: Write failing tests**

In `backend/tests/test_crawler.py`, add these imports at the top if not already present:
```python
from tests.conftest import load_fixture
```

Then add:

```python
def test_fetch_page_skips_sticky_items_in_fixture():
    """_extract_listings (used by fetch_page) must skip sticky structItems."""
    html = load_fixture("overview_page.html")
    results = _extract_listings(html, "https://www.rc-network.de/forums/biete-flugmodelle.132/")
    # All results must have a numeric external_id — sticky items never have one
    for item in results:
        assert item["external_id"].isdigit(), f"Non-numeric external_id: {item['external_id']}"


@pytest.mark.asyncio
async def test_fetch_page_returns_empty_on_http_error():
    """fetch_page returns empty list on HTTP 404."""
    import httpx
    from unittest.mock import AsyncMock, patch

    mock_response = AsyncMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=AsyncMock(), response=AsyncMock(status_code=404)
    )

    with patch("app.scraper.crawler.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        async with httpx.AsyncClient() as real_client:
            # Use real client but override get
            real_client.get = mock_client.get
            results = await fetch_page(
                "https://www.rc-network.de/forums/biete-flugmodelle.132/page-999/",
                real_client,
            )

    assert results == []
```

Note: `_extract_listings` is already imported in `test_crawler.py`. Add `fetch_page` to the import line.

**Step 2: Run tests to verify they fail**

```bash
docker compose exec backend pytest tests/test_crawler.py::test_fetch_page_skips_sticky_items_in_fixture tests/test_crawler.py::test_fetch_page_returns_empty_on_http_error -v
```

Expected: FAIL — `cannot import name 'fetch_page'`

**Step 3: Implement `fetch_page` in crawler.py**

Add after `_extract_listings`:

```python
async def fetch_page(url: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch a single overview page and return its listings.

    Returns an empty list on HTTP errors or network failures.
    Uses the caller's httpx.AsyncClient (caller manages lifecycle).
    """
    logger.info("Fetching overview page: %s", url)
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s for %s — returning empty", exc.response.status_code, url)
        return []
    except httpx.RequestError as exc:
        logger.warning("Request error for %s: %s — returning empty", url, exc)
        return []
    return _extract_listings(response.text, url)
```

Also add `fetch_page` to the imports in the existing import line at the top of `test_crawler.py`:
```python
from app.scraper.crawler import _build_page_url, _extract_listings, fetch_listings, fetch_page
```

**Step 4: Run all crawler tests**

```bash
docker compose exec backend pytest tests/test_crawler.py -v
```

Expected: all PASS.

**Step 5: Commit**

```bash
git add backend/app/scraper/crawler.py backend/tests/test_crawler.py
git commit -m "feat: add fetch_page helper to crawler for stop-early page iteration"
```

---

## Task 3: Orchestrator — Phase 1 (stop-early new listing crawl) [ ]

**Depends on:** Task 2

**Files:**
- Modify: `backend/app/scraper/orchestrator.py`
- Create: `backend/tests/test_orchestrator_phases.py`

Replace the monolithic `run_scrape` with three phase functions. **Important:** `run_scrape` is still imported by `routes.py` — keep it as a no-op shim until Task 7 removes it. **Do NOT import `scrape_runner` in this shim** — that module does not exist until Task 5 and would cause an ImportError.

**Step 1: Write failing tests**

Create `backend/tests/test_orchestrator_phases.py`:

```python
"""Tests for orchestrator phase functions.

Uses integration-style tests with db_session where possible to avoid
brittle mock chains. Unit tests use targeted mocks only for network calls.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.scraper.orchestrator import _phase1_new_listings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_stops_when_page_fully_known(db_session: AsyncSession):
    """Phase 1 stops after page 1 when all IDs on that page already exist in DB."""
    from app.models import Listing
    from datetime import datetime, timezone

    # Pre-insert two listings so they're "known"
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('111', 'https://rc-network.de/t/111', 'Test 1', '', '[]', '[]', 'user', NOW(), FALSE),
               ('222', 'https://rc-network.de/t/222', 'Test 2', '', '[]', '[]', 'user', NOW(), FALSE)
    """))
    await db_session.commit()

    page1_listings = [
        {"external_id": "111", "url": "https://rc-network.de/threads/t.111/"},
        {"external_id": "222", "url": "https://rc-network.de/threads/t.222/"},
    ]
    fetch_calls = []

    async def mock_fetch_page(url, client):
        fetch_calls.append(url)
        return page1_listings  # always returns same page (would loop without stop-early)

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page):
        result = await _phase1_new_listings(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    # Must have stopped after exactly 1 page (all IDs known)
    assert len(fetch_calls) == 1
    assert result["new"] == 0
    assert result["updated"] == 0
    assert result["pages_crawled"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase1_respects_max_pages_cap(db_session: AsyncSession):
    """Phase 1 stops at MAX_PAGES even if new listings keep appearing."""
    from app.scraper.orchestrator import MAX_PAGES
    fetch_calls = []

    async def mock_fetch_page(url, client):
        fetch_calls.append(url)
        # Always return a "new" listing — would loop forever without cap
        page_num = len(fetch_calls)
        return [{"external_id": str(page_num * 100), "url": f"https://rc-network.de/t/{page_num * 100}/"}]

    with patch("app.scraper.orchestrator.fetch_page", side_effect=mock_fetch_page), \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls, \
         patch("app.scraper.orchestrator.parse_detail") as mock_parse:

        mock_parse.return_value = {
            "title": "X", "price": None, "condition": None, "shipping": None,
            "plz": None, "city": None, "description": "", "images": [], "tags": [],
            "author": "u", "posted_at": None, "posted_at_raw": None, "is_sold": False,
        }
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html></html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        result = await _phase1_new_listings(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    assert len(fetch_calls) == MAX_PAGES
    assert result["pages_crawled"] == MAX_PAGES
```

**Step 2: Run tests to verify they fail**

```bash
docker compose exec backend pytest tests/test_orchestrator_phases.py -v
```

Expected: FAIL — `cannot import name '_phase1_new_listings'`

**Step 3: Implement phase1 in orchestrator.py**

Add the following to the imports at the top of `orchestrator.py`:

```python
from sqlalchemy import select, update as sa_update
from app.scraper.crawler import fetch_page, _build_page_url
```

Add the constant and replace `_fetch_fresh_ids` / `_FRESH_IDS_SQL` with:

```python
MAX_PAGES = 25  # hard safety cap for phase1 stop-early crawl

_EXISTING_IDS_SQL = text("""
    SELECT external_id FROM listings WHERE external_id = ANY(:ids)
""")


async def _fetch_existing_ids(
    session: AsyncSession,
    external_ids: list[str],
) -> set[str]:
    """Return the subset of external_ids already in the DB."""
    if not external_ids:
        return set()
    result = await session.execute(_EXISTING_IDS_SQL, {"ids": external_ids})
    return {row[0] for row in result.fetchall()}
```

Add `_phase1_new_listings`:

```python
async def _phase1_new_listings(
    session: AsyncSession,
    update_progress: callable,
    delay: float,
) -> dict:
    """Phase 1: crawl overview pages and upsert new/changed listings.

    Stops pagination when a full page contains no new external_ids
    (rc-network.de overview is ordered newest-first).
    Hard cap at MAX_PAGES as a safety net against parser regressions.

    Returns: {pages_crawled, new, updated}
    """
    new_count = 0
    updated_count = 0
    scraped_at = datetime.now(timezone.utc)

    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            update_progress(f"Seite {page} scannen…")
            url = _build_page_url(_START_URL, page)
            page_listings = await fetch_page(url, client)

            if not page_listings:
                logger.info("Phase 1: empty page %d — stopping", page)
                return {"pages_crawled": page, "new": new_count, "updated": updated_count}

            ids = [item["external_id"] for item in page_listings]
            existing_ids = await _fetch_existing_ids(session, ids)
            new_on_page = [item for item in page_listings if item["external_id"] not in existing_ids]

            if not new_on_page:
                logger.info(
                    "Phase 1: page %d fully known — stopping after %d pages", page, page
                )
                return {"pages_crawled": page, "new": new_count, "updated": updated_count}

            logger.info("Phase 1: page %d has %d new listings", page, len(new_on_page))

            for idx, item in enumerate(new_on_page):
                update_progress(f"Seite {page}: {idx + 1}/{len(new_on_page)} neue Inserate")
                external_id: str = item["external_id"]
                url_detail: str = item["url"]

                try:
                    response = await client.get(url_detail)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "Phase 1: HTTP %s for %s — skipping",
                        exc.response.status_code, external_id,
                    )
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        "Phase 1: request error for %s: %s — skipping", external_id, exc
                    )
                    continue

                parsed = parse_detail(response.text, page_url=url_detail)
                latitude, longitude, resolved_plz = await _geo_lookup(
                    session, parsed.get("plz"), parsed.get("city")
                )
                parsed["plz"] = resolved_plz

                is_new = await _upsert_listing(
                    session=session,
                    external_id=external_id,
                    url=url_detail,
                    parsed=parsed,
                    latitude=latitude,
                    longitude=longitude,
                    scraped_at=scraped_at,
                )
                await session.commit()

                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

                if idx < len(new_on_page) - 1:
                    await asyncio.sleep(delay)

            if page < MAX_PAGES:
                await asyncio.sleep(delay)

    logger.warning("Phase 1: reached MAX_PAGES cap (%d)", MAX_PAGES)
    return {"pages_crawled": MAX_PAGES, "new": new_count, "updated": updated_count}
```

Also add the `run_scrape` shim at the bottom (keeps `routes.py` import working until Task 7):

```python
async def run_scrape(session, max_pages: int = 10, fresh_threshold_days: int = 7) -> dict:
    """Deprecated shim — superseded by scrape_runner.run_scrape_job. Removed in Task 7."""
    logger.warning("run_scrape shim called — consider using run_scrape_job directly")
    return {"pages_crawled": 0, "listings_found": 0, "new": 0, "updated": 0, "skipped": 0}
```

**Step 4: Run tests**

```bash
docker compose exec backend pytest tests/test_orchestrator_phases.py -v
```

Expected: all PASS.

**Step 5: Run full test suite to catch any regressions**

```bash
docker compose exec backend pytest tests/ -v
```

Expected: all PASS.

**Step 6: Commit**

```bash
git add backend/app/scraper/orchestrator.py backend/tests/test_orchestrator_phases.py
git commit -m "feat: orchestrator phase1 stop-early new listing crawl with MAX_PAGES cap"
```

---

## Task 4: Orchestrator — Phase 2 (sold recheck) + Phase 3 (cleanup) [ ]

**Depends on:** Task 1, Task 3

**Files:**
- Modify: `backend/app/scraper/orchestrator.py`
- Modify: `backend/tests/test_orchestrator_phases.py`

**Step 1: Write failing tests**

Append to `backend/tests/test_orchestrator_phases.py`:

```python
from app.scraper.orchestrator import _phase2_sold_recheck, _phase3_cleanup


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_marks_sold_listing(db_session: AsyncSession):
    """Phase 2 sets is_sold=True when parser detects sold status."""
    # Insert a non-sold listing
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('sold-test', 'https://rc-network.de/t/999/', 'Selling item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:

        mock_parse.return_value = {"is_sold": True}

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html>verkauft</html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        result = await _phase2_sold_recheck(
            db_session,
            update_progress=lambda p: None,
            delay=0.0,
        )

    assert result["rechecked"] == 1
    assert result["sold_found"] == 1

    # Verify DB was updated
    row = await db_session.execute(
        text("SELECT is_sold FROM listings WHERE external_id = 'sold-test'")
    )
    assert row.fetchone()[0] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_rotates_scraped_at(db_session: AsyncSession):
    """Phase 2 updates scraped_at so listings cycle to end of recheck queue."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author, scraped_at, is_sold)
        VALUES ('rotate-test', 'https://rc-network.de/t/888/', 'Item', '', '[]', '[]', 'user',
                '2026-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    with patch("app.scraper.orchestrator.parse_detail") as mock_parse, \
         patch("app.scraper.orchestrator.httpx.AsyncClient") as mock_client_cls:

        mock_parse.return_value = {"is_sold": False}
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = "<html></html>"
        mock_http.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value = mock_http

        await _phase2_sold_recheck(db_session, lambda p: None, delay=0.0)

    row = await db_session.execute(
        text("SELECT scraped_at FROM listings WHERE external_id = 'rotate-test'")
    )
    scraped_at = row.fetchone()[0]
    # scraped_at must be recent (within last 5 seconds)
    from datetime import datetime, timezone, timedelta
    assert scraped_at > datetime.now(timezone.utc) - timedelta(seconds=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase3_deletes_old_sold_listings(db_session: AsyncSession):
    """Phase 3 deletes sold listings older than 2 months."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author,
                              scraped_at, posted_at, is_sold)
        VALUES
            -- Old sold: should be deleted
            ('old-sold', 'https://rc-network.de/t/1/', 'Old sold', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00', TRUE),
            -- Recent sold: should NOT be deleted (only 1 day old)
            ('new-sold', 'https://rc-network.de/t/2/', 'New sold', '', '[]', '[]', 'u',
             NOW(), NOW(), TRUE),
            -- Old not-sold: should NOT be deleted by this rule
            ('old-active', 'https://rc-network.de/t/3/', 'Old active', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00', FALSE)
    """))
    await db_session.commit()

    result = await _phase3_cleanup(db_session)

    assert result["deleted_sold"] == 1

    remaining = await db_session.execute(
        text("SELECT external_id FROM listings ORDER BY external_id")
    )
    ids = {r[0] for r in remaining.fetchall()}
    assert "old-sold" not in ids
    assert "new-sold" in ids
    assert "old-active" in ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase3_deletes_stale_listings(db_session: AsyncSession):
    """Phase 3 deletes non-sold listings with posted_at older than 8 weeks."""
    await db_session.execute(text("""
        INSERT INTO listings (external_id, url, title, description, images, tags, author,
                              scraped_at, posted_at, is_sold)
        VALUES
            -- Old: should be deleted
            ('stale', 'https://rc-network.de/t/10/', 'Stale', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00', FALSE),
            -- Recent: should NOT be deleted
            ('fresh', 'https://rc-network.de/t/11/', 'Fresh', '', '[]', '[]', 'u',
             NOW(), NOW(), FALSE),
            -- NULL posted_at: should NOT be deleted
            ('nodate', 'https://rc-network.de/t/12/', 'No date', '', '[]', '[]', 'u',
             '2025-01-01 00:00:00+00', NULL, FALSE)
    """))
    await db_session.commit()

    result = await _phase3_cleanup(db_session)

    assert result["deleted_stale"] == 1
    remaining = await db_session.execute(
        text("SELECT external_id FROM listings ORDER BY external_id")
    )
    ids = {r[0] for r in remaining.fetchall()}
    assert "stale" not in ids
    assert "fresh" in ids
    assert "nodate" in ids
```

**Step 2: Run tests to verify they fail**

```bash
docker compose exec backend pytest tests/test_orchestrator_phases.py::test_phase2_marks_sold_listing -v
```

Expected: FAIL — `cannot import name '_phase2_sold_recheck'`

**Step 3: Implement `_phase2_sold_recheck` in orchestrator.py**

```python
_RECHECK_SQL = text("""
    SELECT id, url, external_id
    FROM listings
    WHERE is_sold = FALSE
    ORDER BY scraped_at ASC
    LIMIT :limit
""")


async def _phase2_sold_recheck(
    session: AsyncSession,
    update_progress: callable,
    delay: float,
    batch_size: int = 50,
) -> dict:
    """Phase 2: re-fetch oldest non-sold listings to detect sold status.

    Processes up to batch_size listings ordered by scraped_at ASC (oldest first).
    Always updates scraped_at so items cycle to end of the recheck queue on next run.

    Returns: {rechecked, sold_found}
    """
    result = await session.execute(_RECHECK_SQL, {"limit": batch_size})
    listings = result.fetchall()  # [(id, url, external_id), ...]

    now = datetime.now(timezone.utc)
    rechecked = 0
    sold_found = 0

    if not listings:
        return {"rechecked": 0, "sold_found": 0}

    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for idx, (listing_id, url, external_id) in enumerate(listings):
            update_progress(f"Sold-Check {idx + 1}/{len(listings)}: {external_id}")
            logger.info(
                "Phase 2: rechecking %s (%d/%d)", external_id, idx + 1, len(listings)
            )

            try:
                response = await client.get(url)
                response.raise_for_status()
                parsed = parse_detail(response.text, page_url=url)
                is_sold = parsed.get("is_sold", False)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning(
                    "Phase 2: failed to fetch %s: %s — bumping scraped_at only",
                    external_id, exc,
                )
                await session.execute(
                    text("UPDATE listings SET scraped_at = :now WHERE id = :id"),
                    {"now": now, "id": listing_id},
                )
                await session.commit()
                continue

            await session.execute(
                text("UPDATE listings SET is_sold = :is_sold, scraped_at = :now WHERE id = :id"),
                {"is_sold": is_sold, "now": now, "id": listing_id},
            )
            await session.commit()

            rechecked += 1
            if is_sold:
                sold_found += 1
                logger.info("Phase 2: %s marked as SOLD", external_id)

            if idx < len(listings) - 1:
                await asyncio.sleep(delay)

    return {"rechecked": rechecked, "sold_found": sold_found}
```

**Step 4: Implement `_phase3_cleanup` in orchestrator.py**

```python
async def _phase3_cleanup(session: AsyncSession) -> dict:
    """Phase 3: delete stale and sold listings per retention policy.

    Retention rules:
    - Sold listings with scraped_at older than 2 months: delete
    - Non-sold listings with posted_at older than 8 weeks: delete
      (listings with NULL posted_at are excluded and kept indefinitely)

    Returns: {deleted_sold, deleted_stale}
    """
    now = datetime.now(timezone.utc)
    two_months_ago = now - timedelta(days=60)
    eight_weeks_ago = now - timedelta(weeks=8)

    sold_result = await session.execute(
        text("""
            DELETE FROM listings
            WHERE is_sold = TRUE AND scraped_at < :cutoff
            RETURNING id
        """),
        {"cutoff": two_months_ago},
    )
    deleted_sold = len(sold_result.fetchall())

    stale_result = await session.execute(
        text("""
            DELETE FROM listings
            WHERE is_sold = FALSE
              AND posted_at < :cutoff
              AND posted_at IS NOT NULL
            RETURNING id
        """),
        {"cutoff": eight_weeks_ago},
    )
    deleted_stale = len(stale_result.fetchall())

    await session.commit()

    logger.info(
        "Phase 3: deleted %d sold + %d stale listings", deleted_sold, deleted_stale
    )
    return {"deleted_sold": deleted_sold, "deleted_stale": deleted_stale}
```

**Step 5: Run all orchestrator phase tests**

```bash
docker compose exec backend pytest tests/test_orchestrator_phases.py -v
```

Expected: all PASS.

**Step 6: Commit**

```bash
git add backend/app/scraper/orchestrator.py backend/tests/test_orchestrator_phases.py
git commit -m "feat: orchestrator phase2 sold-recheck and phase3 cleanup"
```

---

## Task 5: Scrape runner — global state + background job [ ]

**Depends on:** Task 4

**Files:**
- Create: `backend/app/scrape_runner.py`
- Create: `backend/tests/test_scrape_runner.py`

The runner owns the in-memory job state and the `run_scrape_job()` coroutine. A module-level dict is safe because FastAPI/uvicorn is single-process (single user). The `asyncio.create_task` caller must hold a reference to prevent GC cancellation — use a module-level task set.

**Step 1: Write failing tests**

Create `backend/tests/test_scrape_runner.py`:

```python
"""Tests for scrape_runner state machine."""
import pytest
from unittest.mock import patch, AsyncMock
from app.scrape_runner import get_state, run_scrape_job, reset_state


@pytest.mark.asyncio
async def test_run_scrape_job_transitions_to_done():
    """run_scrape_job transitions: idle → running → done."""
    reset_state()
    assert get_state()["status"] == "idle"

    p1 = {"pages_crawled": 1, "new": 2, "updated": 0}
    p2 = {"rechecked": 10, "sold_found": 1}
    p3 = {"deleted_sold": 0, "deleted_stale": 1}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock, return_value=p1), \
         patch("app.scrape_runner._phase2_sold_recheck", new_callable=AsyncMock, return_value=p2), \
         patch("app.scrape_runner._phase3_cleanup", new_callable=AsyncMock, return_value=p3), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=mock_session):

        await run_scrape_job()

    state = get_state()
    assert state["status"] == "done"
    assert state["summary"]["new"] == 2
    assert state["summary"]["sold_found"] == 1
    assert state["summary"]["deleted_stale"] == 1
    assert state["started_at"] is not None
    assert state["finished_at"] is not None


@pytest.mark.asyncio
async def test_run_scrape_job_sets_error_on_failure():
    """run_scrape_job sets status=error if a phase raises."""
    reset_state()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scrape_runner._phase1_new_listings",
               new_callable=AsyncMock, side_effect=RuntimeError("DB gone")), \
         patch("app.scrape_runner.AsyncSessionLocal", return_value=mock_session):

        await run_scrape_job()

    state = get_state()
    assert state["status"] == "error"
    assert "DB gone" in state["error"]


@pytest.mark.asyncio
async def test_run_scrape_job_noop_when_already_running():
    """run_scrape_job returns immediately if status is already running.

    Note: The check-then-set is synchronous (no await between them), so this
    is safe in a single event loop without a lock.
    """
    reset_state()
    import app.scrape_runner as runner
    runner._state["status"] = "running"

    with patch("app.scrape_runner._phase1_new_listings", new_callable=AsyncMock) as mock_p1:
        await run_scrape_job()
        assert not mock_p1.called

    runner._state["status"] = "idle"  # restore
```

**Step 2: Run tests to verify they fail**

```bash
docker compose exec backend pytest tests/test_scrape_runner.py -v
```

Expected: FAIL — `No module named 'app.scrape_runner'`

**Step 3: Create `backend/app/scrape_runner.py`**

```python
"""Scrape job state machine and background job runner.

Single module-level dict tracks job status — safe for single-process uvicorn.
The check-and-set in run_scrape_job is synchronous (no await between the guard
and the state mutation), making it safe without a lock in asyncio's cooperative
multitasking model.

Task reference tracking: callers must store the asyncio.Task in _background_tasks
to prevent GC collection mid-execution (Python docs warning).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import AsyncSessionLocal
from app.scraper.orchestrator import (
    _phase1_new_listings,
    _phase2_sold_recheck,
    _phase3_cleanup,
)

logger = logging.getLogger(__name__)

# Module-level state — single-process, single-user
_state: dict[str, Any] = {
    "status": "idle",    # "idle" | "running" | "done" | "error"
    "started_at": None,  # ISO 8601 string
    "finished_at": None,
    "phase": None,       # "phase1" | "phase2" | "phase3"
    "progress": None,    # human-readable current step
    "summary": None,     # final result dict
    "error": None,
}

# Strong references to background tasks prevent GC cancellation
# (see https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)
_background_tasks: set[asyncio.Task] = set()


def get_state() -> dict[str, Any]:
    """Return a shallow copy of the current scrape state."""
    return dict(_state)


def reset_state() -> None:
    """Reset state to idle. Used in tests only."""
    _state.update({
        "status": "idle",
        "started_at": None,
        "finished_at": None,
        "phase": None,
        "progress": None,
        "summary": None,
        "error": None,
    })


def _update(**kwargs: Any) -> None:
    _state.update(kwargs)


def start_background_job() -> bool:
    """Create an asyncio.Task for run_scrape_job, keeping a strong reference.

    Returns True if the job was started, False if already running.
    """
    if _state["status"] == "running":
        return False
    task = asyncio.create_task(run_scrape_job())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


async def run_scrape_job() -> None:
    """Full scrape cycle: phase1 + phase2 + phase3.

    No-op if already running. Updates _state throughout so callers can poll.
    Creates its own DB sessions — not request-scoped.
    """
    # Guard: synchronous check-and-set (no await between them — safe in asyncio)
    if _state["status"] == "running":
        logger.info("Scrape already running — ignoring trigger")
        return

    _update(
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        phase="phase1",
        progress="Starte…",
        summary=None,
        error=None,
    )
    logger.info("Scrape job started")

    try:
        summary: dict[str, Any] = {}
        delay = settings.SCRAPE_DELAY

        _update(phase="phase1", progress="Übersichtsseiten scannen…")
        async with AsyncSessionLocal() as session:
            result = await _phase1_new_listings(
                session,
                update_progress=lambda p: _update(phase="phase1", progress=p),
                delay=delay,
            )
        summary.update(result)
        logger.info("Phase 1 done: %s", result)

        _update(phase="phase2", progress="Sold-Check…")
        async with AsyncSessionLocal() as session:
            result = await _phase2_sold_recheck(
                session,
                update_progress=lambda p: _update(phase="phase2", progress=p),
                delay=delay,
            )
        summary.update(result)
        logger.info("Phase 2 done: %s", result)

        _update(phase="phase3", progress="Aufräumen…")
        async with AsyncSessionLocal() as session:
            result = await _phase3_cleanup(session)
        summary.update(result)
        logger.info("Phase 3 done: %s", result)

        _update(
            status="done",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            summary=summary,
        )
        logger.info("Scrape job complete: %s", summary)

    except Exception as exc:
        logger.exception("Scrape job failed: %s", exc)
        _update(
            status="error",
            finished_at=datetime.now(timezone.utc).isoformat(),
            phase=None,
            progress=None,
            error=str(exc),
        )
```

**Step 4: Run tests**

```bash
docker compose exec backend pytest tests/test_scrape_runner.py -v
```

Expected: all PASS.

**Step 5: Commit**

```bash
git add backend/app/scrape_runner.py backend/tests/test_scrape_runner.py
git commit -m "feat: scrape runner with state machine, background job, and GC-safe task tracking"
```

---

## Task 6: APScheduler — 4h cron in lifespan [ ]

**Depends on:** Task 5

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/main.py`

**Step 1: Add APScheduler to requirements**

In `backend/requirements.txt`, add:

```
apscheduler>=3.10,<4
```

Pin to `<4` because APScheduler 4.x has a completely different API.

**Step 2: Rebuild Docker image**

```bash
docker compose build backend && docker compose up -d
```

**Step 3: Wire scheduler into lifespan in main.py**

Replace `backend/app/main.py` entirely:

```python
"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.routes import router
from app.scrape_runner import run_scrape_job

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic."""
    from app.db import init_db
    await init_db()
    logger.info("Database initialised")

    # First auto-scrape fires 4 hours after process start (not immediately on boot).
    # To trigger an immediate scrape, use the manual button in the UI.
    _scheduler.add_job(
        run_scrape_job,
        trigger="interval",
        hours=4,
        id="auto_scrape",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — auto-scrape every 4 hours (first run in 4h)")

    yield

    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(title="RC-Markt Scout", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
```

**Step 4: Verify scheduler starts**

```bash
docker compose logs backend --tail=20
```

Expected: log line containing `Scheduler started — auto-scrape every 4 hours`.

**Step 5: Verify health**

```bash
curl -s http://localhost:8002/health
```

Expected: `{"status":"ok"}`

**Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/main.py
git commit -m "feat: APScheduler 4h auto-scrape cron in FastAPI lifespan"
```

---

## Task 7: API layer — new endpoints + schemas [ ]

**Depends on:** Task 5

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`

**Step 1: Update schemas.py**

In `backend/app/api/schemas.py`:

1. Add `from typing import Literal` at the top.
2. Add `is_favorite: bool = False` to both `ListingSummary` and `ListingDetail`.
3. Replace `ScrapeSummary` and add `ScrapeStatus`:

```python
class ScrapeSummary(BaseModel):
    pages_crawled: int = 0
    new: int = 0
    updated: int = 0
    rechecked: int = 0
    sold_found: int = 0
    deleted_sold: int = 0
    deleted_stale: int = 0


class ScrapeStatus(BaseModel):
    status: Literal["idle", "running", "done", "error"]
    started_at: str | None = None
    finished_at: str | None = None
    phase: Literal["phase1", "phase2", "phase3"] | None = None
    progress: str | None = None
    summary: ScrapeSummary | None = None
    error: str | None = None
```

**Step 2: Update routes.py**

Make these changes to `backend/app/api/routes.py`:

1. Remove `from app.scraper.orchestrator import run_scrape` (replaced by scrape_runner).
2. Add new imports:
```python
import asyncio
from app.api.schemas import ScrapeStatus, ScrapeSummary
from app.scrape_runner import get_state, start_background_job
```

3. Replace the `POST /api/scrape` endpoint:
```python
@router.post("/scrape", status_code=202)
async def start_scrape() -> dict:
    """Trigger a background scrape job. Returns 409 if already running."""
    logger.info("POST /api/scrape — triggering background job")
    started = start_background_job()
    if not started:
        raise HTTPException(status_code=409, detail="Scrape already running")
    return {"status": "started"}
```

4. Add new endpoints (after the existing `/scrape` endpoint):
```python
@router.get("/scrape/status", response_model=ScrapeStatus)
async def scrape_status() -> ScrapeStatus:
    """Return current scrape job status for frontend polling."""
    state = get_state()
    summary_data = state.get("summary")
    summary = ScrapeSummary(**summary_data) if summary_data else None
    return ScrapeStatus(
        status=state["status"],
        started_at=state["started_at"],
        finished_at=state["finished_at"],
        phase=state["phase"],
        progress=state["progress"],
        summary=summary,
        error=state["error"],
    )


@router.patch("/listings/{listing_id}/favorite")
async def toggle_favorite(
    listing_id: int,
    is_favorite: bool,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Set or clear the is_favorite flag on a listing."""
    result = await session.execute(
        update(Listing)
        .where(Listing.id == listing_id)
        .values(is_favorite=is_favorite)
        .returning(Listing.id)
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    await session.commit()
    return {"id": listing_id, "is_favorite": is_favorite}


@router.get("/favorites", response_model=list[ListingSummary])
async def get_favorites(
    session: AsyncSession = Depends(get_session),
) -> list[ListingSummary]:
    """Return all favorited listings ordered by posted_at desc."""
    result = await session.execute(
        select(Listing)
        .where(Listing.is_favorite.is_(True))
        .order_by(Listing.posted_at.desc().nulls_last())
    )
    rows = result.scalars().all()
    return [ListingSummary.model_validate(row) for row in rows]
```

Note: `update` is already imported at the top of `routes.py` — do not add a duplicate import.

**Step 3: Write API tests**

Add a new test class to `backend/tests/test_api.py`. Follow the existing async pattern with `api_client` and `db_session`. Add a helper `_insert_listing_full` that includes `is_favorite`:

```python
async def _insert_listing_full(
    session: AsyncSession,
    *,
    external_id: str,
    title: str = "Test",
    is_favorite: bool = False,
    is_sold: bool = False,
    lat: float | None = None,
    lon: float | None = None,
) -> int:
    """Insert a listing and return its auto-incremented id."""
    result = await session.execute(
        text("""
            INSERT INTO listings (external_id, url, title, price, condition, shipping,
                description, images, tags, author, posted_at, posted_at_raw, plz, city,
                latitude, longitude, scraped_at, is_sold, is_favorite)
            VALUES (:eid, :url, :title, NULL, NULL, NULL,
                '', '[]', '[]', 'TestUser', NOW(), NULL, NULL, NULL,
                :lat, :lon, NOW(), :is_sold, :is_favorite)
            RETURNING id
        """),
        {
            "eid": external_id, "url": f"https://example.com/{external_id}",
            "title": title, "lat": lat, "lon": lon,
            "is_sold": is_sold, "is_favorite": is_favorite,
        },
    )
    await session.commit()
    return result.fetchone()[0]


@pytest.mark.asyncio
@pytest.mark.integration
class TestScrapeEndpoints:
    async def test_start_scrape_returns_202(self, api_client: AsyncClient) -> None:
        """POST /api/scrape starts background job and returns 202."""
        from unittest.mock import patch
        with patch("app.api.routes.start_background_job", return_value=True):
            resp = await api_client.post("/api/scrape")
        assert resp.status_code == 202
        assert resp.json()["status"] == "started"

    async def test_start_scrape_returns_409_when_running(
        self, api_client: AsyncClient
    ) -> None:
        """POST /api/scrape returns 409 if already running."""
        from unittest.mock import patch
        with patch("app.api.routes.start_background_job", return_value=False):
            resp = await api_client.post("/api/scrape")
        assert resp.status_code == 409

    async def test_scrape_status_returns_idle(self, api_client: AsyncClient) -> None:
        """GET /api/scrape/status returns current state."""
        from unittest.mock import patch
        idle = {
            "status": "idle", "started_at": None, "finished_at": None,
            "phase": None, "progress": None, "summary": None, "error": None,
        }
        with patch("app.api.routes.get_state", return_value=idle):
            resp = await api_client.get("/api/scrape/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"


@pytest.mark.asyncio
@pytest.mark.integration
class TestFavorites:
    async def test_toggle_favorite_sets_flag(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        listing_id = await _insert_listing_full(
            db_session, external_id="fav1", is_favorite=False
        )
        resp = await api_client.patch(
            f"/api/listings/{listing_id}/favorite?is_favorite=true"
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True

    async def test_toggle_favorite_404_for_unknown(
        self, api_client: AsyncClient
    ) -> None:
        resp = await api_client.patch("/api/listings/999999/favorite?is_favorite=true")
        assert resp.status_code == 404

    async def test_get_favorites_returns_only_favorited(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing_full(db_session, external_id="favA", is_favorite=True)
        await _insert_listing_full(db_session, external_id="favB", is_favorite=False)

        resp = await api_client.get("/api/favorites")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["external_id"] == "favA"

    async def test_get_favorites_includes_sold_status(
        self, api_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _insert_listing_full(
            db_session, external_id="favSold", is_favorite=True, is_sold=True
        )
        resp = await api_client.get("/api/favorites")
        assert resp.status_code == 200
        assert resp.json()[0]["is_sold"] is True
```

**Step 4: Run all tests**

```bash
docker compose exec backend pytest tests/ -v
```

Expected: all PASS (including the new favorites + scrape endpoint tests).

**Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat: scrape status + favorites API endpoints, is_favorite in schemas"
```

---

## Task 8: Frontend — update types and API client [ ]

**Depends on:** Task 7

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`

**Step 1: Update `types/api.ts`**

1. Add `is_favorite: boolean` to `ListingSummary` and `ListingDetail`.
2. Replace the existing `ScrapeSummary` interface and add `ScrapeStatus`:

```typescript
export interface ScrapeSummary {
  pages_crawled: number;
  new: number;
  updated: number;
  rechecked: number;
  sold_found: number;
  deleted_sold: number;
  deleted_stale: number;
}

export type ScrapeJobStatus = 'idle' | 'running' | 'done' | 'error';
export type ScrapePhase = 'phase1' | 'phase2' | 'phase3' | null;

export interface ScrapeStatus {
  status: ScrapeJobStatus;
  started_at: string | null;
  finished_at: string | null;
  phase: ScrapePhase;
  progress: string | null;
  summary: ScrapeSummary | null;
  error: string | null;
}
```

**Step 2: Update `api/client.ts`**

Replace `triggerScrape` and add new functions. Update imports to include `ScrapeStatus` and `ListingSummary`:

```typescript
import type {
  ListingsQueryParams,
  ListingDetail,
  ListingSummary,
  PaginatedResponse,
  PlzResponse,
  ScrapeStatus,
} from '../types/api';

// Replace old triggerScrape with:
export async function startScrape(): Promise<{ status: string }> {
  const res = await fetch('/api/scrape', { method: 'POST' });
  return handleResponse<{ status: string }>(res);
}

export async function getScrapeStatus(): Promise<ScrapeStatus> {
  const res = await fetch('/api/scrape/status');
  return handleResponse<ScrapeStatus>(res);
}

export async function toggleFavorite(id: number, isFavorite: boolean): Promise<void> {
  const res = await fetch(`/api/listings/${id}/favorite?is_favorite=${isFavorite}`, {
    method: 'PATCH',
  });
  return handleResponse<void>(res);
}

export async function getFavorites(): Promise<ListingSummary[]> {
  const res = await fetch('/api/favorites');
  return handleResponse<ListingSummary[]>(res);
}
```

Also remove the old `toggleSold` import of `ScrapeSummary` if present.

**Step 3: Check TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat: frontend types and API client for scrape status + favorites"
```

---

## Task 9: Frontend — ScrapeButton polling [ ]

**Depends on:** Task 8

**Files:**
- Modify: `frontend/src/components/ScrapeButton.tsx`
- Modify: `frontend/src/components/__tests__/ScrapeButton.test.tsx`

**Reuse check:** No existing polling pattern in codebase.

**Step 1: Write failing tests**

Replace `frontend/src/components/__tests__/ScrapeButton.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import ScrapeButton from '../ScrapeButton';
import * as client from '../../api/client';

vi.mock('../../api/client');

const idle = { status: 'idle' as const, started_at: null, finished_at: null, phase: null, progress: null, summary: null, error: null };
const running = { ...idle, status: 'running' as const, phase: 'phase1' as const, progress: 'Seite 1 scannen…' };
const done = {
  ...idle, status: 'done' as const,
  summary: { pages_crawled: 2, new: 5, updated: 1, rechecked: 10, sold_found: 0, deleted_sold: 0, deleted_stale: 0 },
};
const errored = { ...idle, status: 'error' as const, error: 'DB gone' };

describe('ScrapeButton', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows "Scrape starten" initially', () => {
    render(<ScrapeButton />);
    expect(screen.getByText('Scrape starten')).toBeTruthy();
  });

  it('polls and shows done summary after job completes', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'started' });
    vi.mocked(client.getScrapeStatus)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce(done);

    const onDone = vi.fn();
    render(<ScrapeButton onDone={onDone} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      // Immediate status fetch after click
      await vi.runAllTimersAsync();
    });

    await act(async () => {
      // Advance past first poll interval (3s)
      await vi.advanceTimersByTimeAsync(3100);
    });

    await waitFor(() => screen.getByText(/5 neu/));
    expect(onDone).toHaveBeenCalled();
  });

  it('shows error when startScrape fails', async () => {
    vi.mocked(client.startScrape).mockRejectedValue(new Error('Netzwerkfehler'));

    render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await vi.runAllTimersAsync();
    });

    await waitFor(() => screen.getByText(/Netzwerkfehler/));
  });

  it('disables button while running', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'started' });
    vi.mocked(client.getScrapeStatus).mockResolvedValue(running);

    render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await vi.runAllTimersAsync();
    });

    const btn = screen.getByRole('button');
    expect(btn).toHaveProperty('disabled', true);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/components/__tests__/ScrapeButton.test.tsx
```

Expected: FAIL.

**Step 3: Rewrite ScrapeButton.tsx**

```tsx
import { useEffect, useRef, useState } from 'react';
import { startScrape, getScrapeStatus } from '../api/client';
import type { ScrapeStatus } from '../types/api';

const POLL_INTERVAL_MS = 3000;

export default function ScrapeButton({ onDone }: { onDone?: () => void }) {
  const [status, setStatus] = useState<ScrapeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = status?.status === 'running';
  const isDone = status?.status === 'done';

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPolling() {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getScrapeStatus();
        setStatus(s);
        if (s.status === 'done' || s.status === 'error') {
          stopPolling();
          if (s.status === 'done') onDone?.();
        }
      } catch {
        stopPolling();
        setError('Verbindung unterbrochen');
      }
    }, POLL_INTERVAL_MS);
  }

  useEffect(() => () => stopPolling(), []);

  async function handleClick() {
    setError(null);
    setStatus(null);
    try {
      await startScrape();
      // Fetch status immediately so UI shows "running" without waiting 3s
      const s = await getScrapeStatus();
      setStatus(s);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    }
  }

  function phaseLabel(phase: string | null): string {
    if (phase === 'phase1') return 'Neue Inserate…';
    if (phase === 'phase2') return 'Sold-Check…';
    if (phase === 'phase3') return 'Aufräumen…';
    return 'Läuft…';
  }

  const hasError = status?.status === 'error' || !!error;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleClick}
        disabled={isRunning}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand text-white text-sm font-semibold hover:bg-brand-dark active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isRunning && (
          <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
        )}
        {isRunning ? phaseLabel(status?.phase ?? null) : 'Scrape starten'}
      </button>

      {isRunning && status?.progress && (
        <span className="text-xs text-gray-500 max-w-xs truncate">{status.progress}</span>
      )}

      {isDone && status?.summary && (
        <span className="text-xs text-gray-600">
          ✓ {status.summary.new} neu · {status.summary.rechecked} geprüft · {status.summary.sold_found} verkauft
        </span>
      )}

      {hasError && (
        <span className="text-xs text-red-500">
          Fehler: {error ?? status?.error}
        </span>
      )}
    </div>
  );
}
```

**Step 4: Run tests**

```bash
cd frontend && npx vitest run src/components/__tests__/ScrapeButton.test.tsx
```

Expected: all PASS.

**Step 5: Commit**

```bash
git add frontend/src/components/ScrapeButton.tsx frontend/src/components/__tests__/ScrapeButton.test.tsx
git commit -m "feat: ScrapeButton polling with phase/progress display"
```

---

## Task 10: Frontend — Star (favorite) button on ListingCard [ ]

**Depends on:** Task 8

**Files:**
- Modify: `frontend/src/components/ListingCard.tsx`
- Modify: `frontend/src/components/__tests__/ListingCard.test.tsx`

**Reuse check:** No existing favorite/star pattern found.

**Step 1: Write failing test**

Check existing `ListingCard.test.tsx` for the `baseListing` fixture definition and add:

```tsx
import { vi } from 'vitest';
import * as client from '../../api/client';
vi.mock('../../api/client');

// Assumes baseListing is already defined in the file as a const with all ListingSummary fields.
// If not, define it:
// const baseListing: ListingSummary = { id: 1, external_id: 'ext1', url: '...', title: 'Test',
//   price: '100 €', condition: 'gut', plz: '12345', city: 'Berlin', latitude: 52.5, longitude: 13.4,
//   author: 'seller', posted_at: '2026-01-01T00:00:00Z', scraped_at: '2026-04-01T00:00:00Z',
//   distance_km: null, images: [], is_sold: false, is_favorite: false };

it('renders star button, calls toggleFavorite on click, optimistic update', async () => {
  vi.mocked(client.toggleFavorite).mockResolvedValue(undefined);
  const listing = { ...baseListing, is_favorite: false };

  render(<MemoryRouter><ListingCard listing={listing} onFavoriteChange={vi.fn()} /></MemoryRouter>);
  const starBtn = screen.getByRole('button', { name: /merken/i });
  expect(starBtn).toBeTruthy();

  fireEvent.click(starBtn);
  await waitFor(() => expect(client.toggleFavorite).toHaveBeenCalledWith(listing.id, true));
});

it('shows filled star when is_favorite=true', () => {
  const listing = { ...baseListing, is_favorite: true };
  render(<MemoryRouter><ListingCard listing={listing} /></MemoryRouter>);
  const starBtn = screen.getByRole('button', { name: /entfernen/i });
  expect(starBtn.innerHTML).toContain('currentColor');
});
```

**Step 2: Add star button to ListingCard.tsx**

Add to the `Props` interface:
```tsx
onFavoriteChange?: (id: number, isFavorite: boolean) => void;
```

Add imports:
```tsx
import { useState } from 'react';
import { toggleFavorite } from '../api/client';
```

Add state and handler inside the component:
```tsx
const [favorite, setFavorite] = useState(listing.is_favorite);
const [favoriteLoading, setFavoriteLoading] = useState(false);

async function handleFavorite(e: React.MouseEvent) {
  e.preventDefault();
  e.stopPropagation();
  if (favoriteLoading) return;
  const next = !favorite;
  setFavorite(next); // optimistic
  setFavoriteLoading(true);
  try {
    await toggleFavorite(listing.id, next);
    onFavoriteChange?.(listing.id, next);
  } catch {
    setFavorite(!next); // revert on error
  } finally {
    setFavoriteLoading(false);
  }
}
```

Add star button inside the `<article>`, placed absolutely top-right (after the image div):

```tsx
<button
  onClick={handleFavorite}
  aria-label={favorite ? 'Von Merkliste entfernen' : 'Merken'}
  className="absolute top-2 right-2 z-20 p-1.5 rounded-full bg-white/80 backdrop-blur-sm shadow hover:bg-white transition"
>
  <svg
    className={`w-4 h-4 transition-colors ${favorite ? 'text-yellow-400' : 'text-gray-400'}`}
    viewBox="0 0 24 24"
    stroke="currentColor"
    strokeWidth={2}
    fill={favorite ? 'currentColor' : 'none'}
    aria-hidden="true"
  >
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
</button>
```

**Step 3: Run tests**

```bash
cd frontend && npx vitest run src/components/__tests__/ListingCard.test.tsx
```

Expected: all PASS.

**Step 4: Commit**

```bash
git add frontend/src/components/ListingCard.tsx frontend/src/components/__tests__/ListingCard.test.tsx
git commit -m "feat: favorite star button on ListingCard with optimistic update"
```

---

## Task 11: Frontend — FavoriteCard component [ ]

**Depends on:** Task 8

**Files:**
- Create: `frontend/src/components/FavoriteCard.tsx`
- Create: `frontend/src/components/__tests__/FavoriteCard.test.tsx`

**Reuse check:** No existing horizontal card pattern. ListingCard is vertical (grid layout) — FavoriteCard is horizontal (image left, content right) per screenshot.

**Step 1: Write failing tests**

Create `frontend/src/components/__tests__/FavoriteCard.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import FavoriteCard from '../FavoriteCard';
import * as client from '../../api/client';

vi.mock('../../api/client');

const baseListing = {
  id: 1, external_id: 'ext1', url: 'https://rc-network.de/t/1',
  title: 'Testflugzeug XY', price: '250 €', condition: 'gebraucht',
  plz: '49356', city: 'Diepholz', latitude: 52.6, longitude: 8.3,
  author: 'seller1', posted_at: '2026-03-01T10:00:00Z',
  scraped_at: '2026-04-01T10:00:00Z', distance_km: null,
  images: ['https://rc-network.de/img/test.jpg'], is_sold: false, is_favorite: true,
};

describe('FavoriteCard', () => {
  it('renders title, price, city and date', () => {
    render(<MemoryRouter><FavoriteCard listing={baseListing} onRemove={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText('Testflugzeug XY')).toBeTruthy();
    expect(screen.getByText('250 €')).toBeTruthy();
    expect(screen.getByText(/Diepholz/)).toBeTruthy();
    expect(screen.getByText('01.03.2026')).toBeTruthy();
  });

  it('shows VERKAUFT badge when is_sold', () => {
    render(<MemoryRouter>
      <FavoriteCard listing={{ ...baseListing, is_sold: true }} onRemove={vi.fn()} />
    </MemoryRouter>);
    expect(screen.getByText('VERKAUFT')).toBeTruthy();
  });

  it('calls onRemove with listing id when remove button clicked', async () => {
    vi.mocked(client.toggleFavorite).mockResolvedValue(undefined);
    const onRemove = vi.fn();
    render(<MemoryRouter><FavoriteCard listing={baseListing} onRemove={onRemove} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: /entfernen/i }));
    await waitFor(() => expect(client.toggleFavorite).toHaveBeenCalledWith(1, false));
    await waitFor(() => expect(onRemove).toHaveBeenCalledWith(1));
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/__tests__/FavoriteCard.test.tsx
```

Expected: FAIL — `Cannot find module '../FavoriteCard'`

**Step 3: Create FavoriteCard.tsx**

```tsx
import { Link } from 'react-router-dom';
import type { ListingSummary } from '../types/api';
import { toggleFavorite } from '../api/client';

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  });
}

interface Props {
  listing: ListingSummary;
  onRemove: (id: number) => void;
}

export default function FavoriteCard({ listing, onRemove }: Props) {
  const location = [listing.plz, listing.city].filter(Boolean).join(' ');

  async function handleRemove(e: React.MouseEvent) {
    e.preventDefault();
    await toggleFavorite(listing.id, false);
    onRemove(listing.id);
  }

  return (
    <article className={`flex gap-4 p-4 bg-white rounded-xl border border-gray-100 shadow-sm relative${listing.is_sold ? ' opacity-70' : ''}`}>
      {/* Thumbnail */}
      <div className="relative shrink-0 w-24 h-20 rounded-lg overflow-hidden bg-gray-100">
        {listing.images.length > 0 ? (
          <img
            src={listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0]}
            alt={listing.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full bg-gray-200" />
        )}
        {listing.images.length > 1 && (
          <span className="absolute bottom-1 right-1 bg-black/60 text-white text-[10px] px-1 rounded">
            {listing.images.length}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
          <span>{location || '–'}</span>
          <span>{formatDate(listing.posted_at)}</span>
        </div>

        <Link
          to={`/listings/${listing.id}`}
          className="block text-sm font-semibold text-gray-900 leading-snug line-clamp-2 hover:text-brand transition-colors mb-1.5 after:absolute after:inset-0"
        >
          {listing.title}
        </Link>

        {listing.condition && (
          <p className="text-xs text-gray-500 line-clamp-1">{listing.condition}</p>
        )}

        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-base font-bold text-gray-900">{listing.price ?? '–'}</span>
          {listing.is_sold && (
            <span className="bg-red-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
              VERKAUFT
            </span>
          )}
        </div>
      </div>

      {/* Remove button — z-10 to sit above the stretched link */}
      <button
        onClick={handleRemove}
        aria-label="Von Merkliste entfernen"
        className="relative z-10 shrink-0 self-center flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 text-xs text-gray-500 hover:border-red-300 hover:text-red-500 transition"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
          <path d="M10 11v6M14 11v6M9 6V4h6v2" />
        </svg>
        Von Merkliste entfernen
      </button>
    </article>
  );
}
```

**Step 4: Run tests**

```bash
cd frontend && npx vitest run src/components/__tests__/FavoriteCard.test.tsx
```

Expected: all PASS.

**Step 5: Commit**

```bash
git add frontend/src/components/FavoriteCard.tsx frontend/src/components/__tests__/FavoriteCard.test.tsx
git commit -m "feat: FavoriteCard horizontal component for Merkliste modal"
```

---

## Task 12: Frontend — FavoritesModal + header button [ ]

**Depends on:** Task 11, Task 10

**Files:**
- Create: `frontend/src/components/FavoritesModal.tsx`
- Modify: `frontend/src/App.tsx`

**Reuse check:** No existing modal pattern in codebase.

**Step 1: Create FavoritesModal.tsx**

```tsx
import { useEffect, useState, useCallback } from 'react';
import { getFavorites } from '../api/client';
import type { ListingSummary } from '../types/api';
import FavoriteCard from './FavoriteCard';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function FavoritesModal({ open, onClose }: Props) {
  const [favorites, setFavorites] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFavorites(await getFavorites());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  function handleRemove(id: number) {
    setFavorites((prev) => prev.filter((f) => f.id !== id));
  }

  // "Aufräumen" removes sold items from the local list view only.
  // Sold favorites will reappear on next modal open (re-fetched from API).
  // To permanently remove, use the individual "Von Merkliste entfernen" button.
  function handleCleanup() {
    setFavorites((prev) => prev.filter((f) => !f.is_sold));
  }

  if (!open) return null;

  const soldCount = favorites.filter((f) => f.is_sold).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm overflow-y-auto py-8 px-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-900">
            Meine Merkliste
            {favorites.length > 0 && (
              <span className="ml-2 text-sm font-normal text-gray-400">({favorites.length})</span>
            )}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition p-1"
            aria-label="Schließen"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          {loading && (
            <div className="flex justify-center py-8">
              <div className="animate-spin h-6 w-6 border-2 border-brand border-t-transparent rounded-full" />
            </div>
          )}
          {!loading && favorites.length === 0 && (
            <p className="text-center text-gray-500 py-8">Noch keine Inserate gemerkt.</p>
          )}
          {!loading && favorites.map((listing) => (
            <FavoriteCard key={listing.id} listing={listing} onRemove={handleRemove} />
          ))}
        </div>

        {/* Footer — Aufräumen hides sold items locally for current session */}
        {soldCount > 0 && (
          <div className="px-6 py-3 border-t border-gray-100 flex items-center gap-3">
            <button
              onClick={handleCleanup}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full bg-gray-900 text-white text-xs font-semibold hover:bg-gray-700 transition"
            >
              Aufräumen
            </button>
            <span className="text-xs text-gray-500">
              Nicht mehr verfügbare Anzeigen entfernen
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Update App.tsx**

Add imports at the top:
```tsx
import FavoritesModal from './components/FavoritesModal';
```

Add `favoritesOpen` state to `App`:
```tsx
const [favoritesOpen, setFavoritesOpen] = useState(false);
```

Update `Header` props and JSX:

```tsx
function Header({ onScrape, onOpenFavorites }: { onScrape: () => void; onOpenFavorites: () => void }) {
  return (
    <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-sm border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
        <Link to="/" className="flex items-center gap-2 text-brand font-bold text-lg tracking-tight">
          <PlaneIcon />
          RC-Network Scraper
        </Link>
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenFavorites}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-600 hover:border-brand hover:text-brand transition"
            aria-label="Merkliste öffnen"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} fill="none" aria-hidden="true">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
            Merkliste
          </button>
          <ScrapeButton onDone={onScrape} />
        </div>
      </div>
    </header>
  );
}
```

Update the `Header` usage in the JSX and add `FavoritesModal`:
```tsx
<Header
  onScrape={() => setScrapeKey((k) => k + 1)}
  onOpenFavorites={() => setFavoritesOpen(true)}
/>
{/* ... routes ... */}
<FavoritesModal open={favoritesOpen} onClose={() => setFavoritesOpen(false)} />
```

**Step 3: Check TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

**Step 4: Build frontend**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no errors.

**Step 5: Commit**

```bash
git add frontend/src/components/FavoritesModal.tsx frontend/src/App.tsx
git commit -m "feat: FavoritesModal with Merkliste button in header"
```

---

## Verification

After all tasks are `[DONE]`:

```bash
# 1. Backend tests
docker compose exec backend pytest tests/ -v
# Expected: all PASS

# 2. Frontend build
cd frontend && npm run build
# Expected: no errors

# 3. Smoke test
docker compose up -d

# Health
curl -s http://localhost:8002/health
# {"status":"ok"}

# Scheduler in logs
docker compose logs backend | grep -i scheduler
# INFO: Scheduler started — auto-scrape every 4 hours (first run in 4h)

# Start scrape (non-blocking — returns immediately)
curl -s -X POST http://localhost:8002/api/scrape
# {"status":"started"}

# Poll status
curl -s http://localhost:8002/api/scrape/status | python -m json.tool
# {"status":"running","phase":"phase1","progress":"Seite 1 scannen…",...}

# Try starting again while running — should 409
curl -s -X POST http://localhost:8002/api/scrape
# {"detail":"Scrape already running"}

# Wait for done, then poll again:
# {"status":"done","summary":{"pages_crawled":...,"new":...,"sold_found":...}}

# Toggle a favorite (use a real listing id from your DB)
curl -s -X PATCH "http://localhost:8002/api/listings/1/favorite?is_favorite=true"
# {"id":1,"is_favorite":true}

# Get favorites
curl -s http://localhost:8002/api/favorites | python -m json.tool
# [{...listing with is_favorite:true...}]
```

---

## Doc Updates (after verification)

1. `docs/limitations.md`: Remove entry `POST /api/scrape is synchronous (blocking)` — resolved.
2. `docs/architektur.md`: Add section describing the three-phase scrape cycle, APScheduler setup, and `scraped_at` dual-meaning note.

---

## Reviewer Section

Two review passes completed (2026-04-07).

**Pass 1 findings addressed:**
- `respx` dependency removed — tests use `unittest.mock` only
- `overview_html` fixture replaced with `load_fixture("overview_page.html")`
- `MAX_PAGES = 25` safety cap added to phase1
- `run_scrape` shim kept as no-op (no `scrape_runner` import) until Task 7
- `asyncio.create_task` GC issue fixed with `_background_tasks` set + `start_background_job()` helper
- API tests rewritten to async `api_client` pattern
- Frontend polling tests use `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync()`

**Pass 2 findings addressed:**
- All integration test INSERTs in Tasks 3 and 4 now include `tags, '[]'` (NOT NULL constraint)
- `_insert_listing_full` helper in Task 7 includes `tags, '[]'`
- Misleading `run_scrape` shim description block (with `scrape_runner` import) removed

**Non-blocking notes (accepted):** `mock_parse.return_value` partial dict in phase2 test; `started_at` typed as `str` instead of `datetime`; APScheduler new dependency requires Human approval per Hard Rule #9 (flagged in plan); `Aufräumen` is local-only filter (trade-off documented inline).
