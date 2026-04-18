# eBay Integration — Second Scraper Source

> **For Claude:** REQUIRED SUB-SKILL: Use `dglabs.executing-plans` to implement this plan task-by-task.

## Context & Goal

Add eBay.de as a second listing source alongside rc-network.de.  
eBay offers a **free, official Browse API** that returns structured JSON — no HTML scraping needed.  
The goal is to fetch used RC listings from eBay.de, store them in the same `listings` table (with a `source` column), and push them through the existing LLM analysis + price indicator pipeline without changing the core architecture.

Users see eBay listings alongside rcnetwork listings in the same UI, optionally filtered by source.  
A filter chip in `FilterPanel` is **out of scope** for this plan — add to backlog.

## Breaking Changes

**No breaking changes** for existing rc-network functionality.  
The `source` column added to `listings` has a `DEFAULT 'rcnetwork'` — all existing rows are automatically tagged.

## Approval Table

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-18 |
| Human | approved | 2026-04-18 |

---

## Assumptions & Risks

- **No "private seller only" filter in eBay Browse API.** eBay does not reliably expose `sellerAccountType` (Privatverkäufer vs. Gewerblich) in the Browse API `item_summary` response. Mitigation: filter by `conditionIds:3000` (Used) as a proxy. After first live run, inspect the actual `seller` object in API responses — if `sellerAccountType` is present, add a post-filter. Documented as `limitations.md` entry (Task 12).
- **eBay category IDs must be verified.** The IDs in `EBAY_CATEGORY_MAP` (see Task 2) are best-effort. The implementor MUST verify them against `GET /buy/browse/v1/category_tree/77` (eBay DE = tree 77) before going live.
- **eBay OAuth token TTL = 2 hours.** The client auto-refreshes 5 min before expiry.
- **eBay API quota.** Browse API default: 5,000 calls/day (verify at developer.ebay.com). Estimated usage: 4 distinct eBay categories × 5 pages × 48 runs/day = ~960 calls/day — well within limits. (Note: `antriebstechnik`, `rc-elektronik`, `einzelteile` share one eBay category and are deduped — see Task 2.)
- **`external_id` collision.** eBay item IDs are of the form `v1|123456789|0` (contains pipes). Prefix with `ebay_` (e.g., `ebay_v1|123456789|0`) — this guarantees uniqueness. Pipe characters are stored as-is in the DB; URL-encoded when used in API requests (see Task 3).
- **Sold detection.** eBay has no push webhook for sold status. Use the same hourly recheck approach as rcnetwork: fetch item by ID; if 404 → mark `is_sold = True`. (Task 9)
- **Location.** eBay returns `itemLocation.postalCode` (5-digit PLZ for Germany). The existing `_geo_lookup()` in `orchestrator.py` is called explicitly from the eBay normalizer (Task 4a).
- **LLM analysis quality.** eBay's `shortDescription` is often a single short headline (<200 chars), unlike rc-network's multi-paragraph forum posts. LLM analysis will run (same pipeline), but `model_type`/`model_subtype` extraction quality may be lower. eBay listings with failed analysis will have `llm_analyzed=False` and will not receive a `price_indicator`. They may be included in comparables pools with missing attributes — same behaviour as rcnetwork listings that fail analysis. Document as limitation; full-item fetch (`get_item()`) as a future improvement.
- **`PAGE_SIZE = 200`** is the Browse API maximum for `item_summary/search`. Documented in eBay Browse API spec.

---

## Reference Patterns

- Existing scraper: `backend/app/scraper/orchestrator.py`, `crawler.py`, `parser.py`
- Migration pattern: `backend/app/db.py` → `init_db()` (idempotent `ALTER TABLE IF NOT EXISTS`)
- DB upsert: `orchestrator.py` → raw SQL `INSERT … ON CONFLICT`
- Geo-lookup: `orchestrator.py` → `_geo_lookup(session, plz, city)` → returns `(lat, lon)` or `(None, None)`
- Scheduler: `backend/app/main.py` → APScheduler `add_job()` (jobs use `async with AsyncSessionLocal()` internally)
- API filter: `backend/app/api/routes.py` → `list_listings()`

---

## Overview of Changes

| Layer | File | Change |
|---|---|---|
| DB | `backend/app/db.py` | Add `ALTER TABLE listings ADD COLUMN IF NOT EXISTS source …` to `init_db()` |
| Backend | `backend/app/models.py` | Add `source` column to `Listing` model |
| Backend | `backend/app/config.py` | Add `ebay_client_id`, `ebay_client_secret`, `EBAY_CATEGORY_MAP` |
| Backend | `backend/app/scraper/ebay_client.py` | **New** — OAuth2 token mgmt + Browse API fetch |
| Backend | `backend/app/scraper/ebay_orchestrator.py` | **New** — normalize + geo-lookup + upsert + recheck |
| Backend | `backend/app/main.py` | Add eBay scheduler job (30 min) |
| Backend | `backend/app/api/routes.py` | Add optional `source` query param to `list_listings` |
| Backend | `backend/app/api/schemas.py` | Add `source` field to `ListingSummary` + `ListingDetail` |
| Frontend | `frontend/src/types/api.ts` | Add `source` to `Listing` type + `ListingsQueryParams` |
| Frontend | `frontend/src/api/client.ts` | Pass `source` param in `getListings()` |
| Frontend | `frontend/src/components/ListingCard.tsx` | Add source badge |
| Frontend | `frontend/src/components/FavoriteCard.tsx` | Add source badge |
| Backend | `.env.example` | Add `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` |
| Backend | `backend/tests/test_ebay_client.py` | **New** — unit tests |
| Backend | `backend/tests/test_ebay_orchestrator.py` | **New** — normalization + orchestration tests |
| Backend | `backend/tests/fixtures/ebay_item_summary.json` | **New** — realistic eBay API response fixture |
| Docs | `docs/limitations.md` | Add eBay "private seller" limitation entry |

---

## eBay API Setup (Prerequisites — Human action required)

Before implementation, register a free eBay Developer account:

1. Go to https://developer.ebay.com → "Get Started"
2. Create a **Production** application (not sandbox)
3. Note: **App ID = Client ID**, **Cert ID = Client Secret**
4. No scope beyond `https://api.ebay.com/oauth/api_scope` needed (public data)
5. Verify the daily Browse API quota for the created app
6. Add to `.env`:
   ```
   EBAY_CLIENT_ID=YourApp-YourApp-PRD-...
   EBAY_CLIENT_SECRET=PRD-...
   ```

**Cost:** Free. Public item search requires no user authentication.

---

## Task 1: DB Migration — add `source` column [ ]

**Files:** `backend/app/db.py`, `backend/app/models.py`

### Step 1a: Add migration to `init_db()`

In `backend/app/db.py`, inside the `init_db()` function, after `Base.metadata.create_all(conn)`, add the idempotent column migration (same pattern as any prior incremental column additions in this file):

```python
await conn.execute(text(
    "ALTER TABLE listings ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'rcnetwork'"
))
await conn.execute(text(
    "CREATE INDEX IF NOT EXISTS ix_listings_source ON listings (source)"
))
```

This runs automatically on every container boot (dev + VPS), consistent with all prior plan migrations.

### Step 1b: Update `Listing` model

In `backend/app/models.py`, add after the `is_sold` column definition:

```python
source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="rcnetwork", index=True)
```

---

## Task 2: Config — eBay credentials + category map [ ]

**File:** `backend/app/config.py`

Add to the `Settings` class:

```python
ebay_client_id: str = ""
ebay_client_secret: str = ""
```

Add as a module-level constant (below the `Settings` class):

```python
# Maps our category slugs to eBay DE category IDs.
# IMPORTANT: verify IDs against GET /buy/browse/v1/category_tree/77 before going live.
# antriebstechnik / rc-elektronik / einzelteile intentionally share category 2577 to
# avoid triple-fetching the same eBay category. Category assignment per listing is
# derived from the LLM analysis, not the eBay category.
EBAY_CATEGORY_MAP: dict[str, int] = {
    "flugmodelle":    29332,  # RC Aircraft
    "schiffsmodelle": 29325,  # RC Boats & Watercraft
    "rc-cars":         2562,  # RC Cars, Trucks & Motorcycles
    "rc-teile":        2577,  # RC Accessories & Parts (covers antriebstechnik / rc-elektronik / einzelteile)
    # "verschenken" has no eBay equivalent — intentionally omitted
}
```

Update `.env.example`:
```
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
```

---

## Task 3: `ebay_client.py` — OAuth2 + Browse API [ ]

**File:** `backend/app/scraper/ebay_client.py` (new)

```python
import asyncio
import base64
import logging
import time
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1"
EBAY_MARKETPLACE = "EBAY_DE"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

_token: str = ""
_token_expires_at: float = 0.0


async def _get_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at - 300:
        return _token
    credentials = base64.b64encode(
        f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    ).decode()
    resp = await client.post(
        EBAY_OAUTH_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expires_at = time.time() + data["expires_in"]
    return _token


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
        "Accept-Language": "de-DE",
    }


async def search_items(
    client: httpx.AsyncClient,
    category_id: int,
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """Search eBay listings. Returns raw API response dict."""
    token = await _get_token(client)
    resp = await client.get(
        f"{EBAY_BROWSE_URL}/item_summary/search",
        headers=_headers(token),
        params={
            "category_ids": str(category_id),
            "filter": "conditionIds:{3000}",  # Used items only
            "sort": "newlyListed",
            "limit": str(limit),
            "offset": str(offset),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def get_item(client: httpx.AsyncClient, external_id: str) -> dict | None:
    """
    Fetch a single item for sold-recheck.
    external_id is our internal "ebay_v1|123|0" format.
    Returns None on 404 (sold/removed).
    """
    raw_id = external_id.removeprefix("ebay_")
    encoded_id = quote(raw_id, safe="")  # encode pipes: v1%7C123%7C0
    resp = await client.get(
        f"{EBAY_BROWSE_URL}/item/{encoded_id}",
        headers=_headers(await _get_token(client)),
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
```

---

## Task 4a: `ebay_orchestrator.py` — `_normalize_item()` + `_all_known()` [ ]

**File:** `backend/app/scraper/ebay_orchestrator.py` (new — create file with these functions first)

### Condition mapping

```python
_CONDITION_MAP = {
    "New":                    "neu",
    "Like New":               "neuwertig",
    "Very Good - Refurbished": "neuwertig",
    "Good - Refurbished":     "gebraucht",
    "Seller Refurbished":     "gebraucht",
    "Used":                   "gebraucht",
    "For parts or not working": "defekt",
}
```

### `_normalize_item(item, category_slug, geo_result)`

```python
from datetime import datetime, timezone
from app.config import settings

def _normalize_item(
    item: dict,
    category_slug: str,
    lat: float | None,
    lon: float | None,
) -> dict:
    """Map a raw eBay item_summary dict to a Listing-compatible insert dict."""
    item_id = item["itemId"]  # e.g. "v1|123456789|0"
    external_id = f"ebay_{item_id}"

    price_value = item.get("price", {}).get("value", "0")
    price_currency = item.get("price", {}).get("currency", "EUR")
    price_str = f"{price_value} {price_currency}"
    try:
        price_numeric = float(price_value)
    except (ValueError, TypeError):
        price_numeric = None

    location = item.get("itemLocation", {})
    plz_raw = (location.get("postalCode") or "")[:5]
    city = location.get("city") or ""

    condition_raw = item.get("condition", "")
    condition = _CONDITION_MAP.get(condition_raw, condition_raw.lower() or None)

    posted_at_raw = item.get("itemCreationDate", "")
    try:
        posted_at = datetime.fromisoformat(posted_at_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        posted_at = datetime.now(timezone.utc)

    images = []
    if primary := item.get("image", {}).get("imageUrl"):
        images.append(primary)
    for img in item.get("additionalImages", []):
        if url := img.get("imageUrl"):
            images.append(url)

    seller = item.get("seller", {})
    author = seller.get("username") or ""

    shipping_opts = item.get("shippingOptions", [])
    if shipping_opts:
        cost = shipping_opts[0].get("shippingCost", {})
        shipping = f"Versand {cost.get('value', '')} {cost.get('currency', '')}".strip()
    else:
        shipping = None

    return {
        "external_id": external_id,
        "url": item.get("itemWebUrl", ""),
        "title": item.get("title", ""),
        "price": price_str,
        "price_numeric": price_numeric,
        "condition": condition,
        "posted_at": posted_at,
        "posted_at_raw": posted_at_raw,
        "author": author,
        "plz": plz_raw or None,
        "city": city or None,
        "latitude": lat,
        "longitude": lon,
        "description": item.get("shortDescription") or "",
        "images": images,
        "tags": [],
        "category": category_slug,
        "source": "ebay",
        "shipping": shipping,
    }
```

### `_all_known(session, external_ids)`

```python
from sqlalchemy import select, text
from app.models import Listing

async def _all_known(session, external_ids: list[str]) -> bool:
    """Return True if every external_id in the list already exists in the DB."""
    if not external_ids:
        return True
    result = await session.execute(
        select(Listing.external_id).where(Listing.external_id.in_(external_ids))
    )
    known = {row[0] for row in result}
    return known.issuperset(external_ids)
```

---

## Task 4b: `ebay_orchestrator.py` — `run_ebay_fetch()` + upsert [ ]

**File:** `backend/app/scraper/ebay_orchestrator.py` (extend Task 4a file)

```python
import asyncio
import logging
from datetime import timezone, datetime

import httpx
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings, EBAY_CATEGORY_MAP
from app.db import AsyncSessionLocal
from app.models import Listing
from app.scraper.ebay_client import search_items, get_item
from app.scraper.orchestrator import _geo_lookup  # reuse existing geo-lookup

logger = logging.getLogger(__name__)

MAX_PAGES = 5
PAGE_SIZE = 200

_UPSERT_SQL = text("""
    INSERT INTO listings (
        external_id, url, title, price, price_numeric, condition,
        posted_at, posted_at_raw, author, plz, city, latitude, longitude,
        description, images, tags, category, source, shipping, scraped_at
    ) VALUES (
        :external_id, :url, :title, :price, :price_numeric, :condition,
        :posted_at, :posted_at_raw, :author, :plz, :city, :latitude, :longitude,
        :description, :images::jsonb, :tags::jsonb, :category, :source, :shipping, NOW()
    )
    ON CONFLICT (external_id) DO UPDATE SET
        price        = EXCLUDED.price,
        price_numeric = EXCLUDED.price_numeric,
        scraped_at   = NOW()
    RETURNING (xmax = 0) AS inserted
""")


async def run_ebay_fetch(session_factory: async_sessionmaker = AsyncSessionLocal) -> dict:
    """
    Fetch eBay listings for all mapped categories and upsert to DB.
    No-op if credentials are not configured.
    Returns {total_new, total_updated, total_skipped}.
    """
    if not settings.ebay_client_id:
        logger.warning("eBay credentials not configured — skipping fetch")
        return {"total_new": 0, "total_updated": 0, "total_skipped": 0}

    total_new = total_updated = total_skipped = 0

    async with httpx.AsyncClient() as http_client:
        async with session_factory() as session:
            for category_slug, ebay_cat_id in EBAY_CATEGORY_MAP.items():
                for page in range(MAX_PAGES):
                    offset = page * PAGE_SIZE
                    try:
                        response = await search_items(http_client, ebay_cat_id, offset=offset, limit=PAGE_SIZE)
                    except httpx.HTTPError as exc:
                        logger.error("eBay fetch error cat=%s page=%d: %s", category_slug, page, exc)
                        break

                    items = response.get("itemSummaries", [])
                    if not items:
                        break

                    external_ids = [f"ebay_{item['itemId']}" for item in items]
                    if await _all_known(session, external_ids):
                        total_skipped += len(items)
                        break

                    for item in items:
                        plz_raw = (item.get("itemLocation", {}).get("postalCode") or "")[:5]
                        city_raw = item.get("itemLocation", {}).get("city") or ""
                        lat, lon = await _geo_lookup(session, plz_raw, city_raw)

                        row = _normalize_item(item, category_slug, lat, lon)
                        result = await session.execute(_UPSERT_SQL, row)
                        inserted = result.scalar()
                        if inserted:
                            total_new += 1
                        else:
                            total_updated += 1

                    await session.commit()

    logger.info("eBay fetch done: new=%d updated=%d skipped=%d", total_new, total_updated, total_skipped)
    return {"total_new": total_new, "total_updated": total_updated, "total_skipped": total_skipped}
```

---

## Task 5: Scheduler — eBay fetch job [ ]

**File:** `backend/app/main.py`

### Step 5a: Add import (if not already present)

```python
from datetime import timedelta
from app.scraper.ebay_orchestrator import run_ebay_fetch
```

### Step 5b: Add job in `lifespan()` after the existing `auto_update` job

```python
scheduler.add_job(
    run_ebay_fetch,
    "interval",
    minutes=30,
    id="auto_ebay_fetch",
    next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3),
)
```

Note: `run_ebay_fetch` manages its own `AsyncSessionLocal` internally (no kwargs needed). It does not use the `scrape_runner` state machine — eBay fetches run silently in the background and do not appear in `/api/scrape/status`. This is intentional to keep the admin UI clean; document as a known difference.

---

## Task 6: API — `source` filter [ ]

**File:** `backend/app/api/routes.py`

In `list_listings()` function signature, add after `model_subtype`:

```python
source: str | None = Query(default=None),
```

In the WHERE clauses block:

```python
if source:
    stmt = stmt.where(Listing.source == source)
```

---

## Task 7: Schemas — add `source` field [ ]

**File:** `backend/app/api/schemas.py`

In both `ListingSummary` and `ListingDetail` Pydantic models, add:

```python
source: str = "rcnetwork"
```

Verify: the favorites API endpoint reuses `ListingSummary` — no additional changes needed for `FavoriteCard` to receive `source`.

---

## Task 8: Frontend — source badge [ ]

**Files:** `frontend/src/types/api.ts`, `frontend/src/api/client.ts`, `frontend/src/components/ListingCard.tsx`, `frontend/src/components/FavoriteCard.tsx`

### Step 8a: Types (`frontend/src/types/api.ts`)

Add `source` to the `Listing` interface:

```typescript
source: string;
```

Add to `ListingsQueryParams`:

```typescript
source?: string;
```

### Step 8b: API client (`frontend/src/api/client.ts`)

In `getListings()`, pass `source` param:

```typescript
if (params.source) query.source = params.source;
```

### Step 8c: Source badge (in both `ListingCard.tsx` and `FavoriteCard.tsx`)

Render a small badge only when `listing.source === 'ebay'`. Place next to the category chip:

```tsx
{listing.source === 'ebay' && (
  <span className="text-xs font-medium bg-yellow-100 text-yellow-800 px-1.5 py-0.5 rounded">
    eBay
  </span>
)}
```

---

## Task 9: eBay sold recheck [ ]

**File:** `backend/app/scraper/ebay_orchestrator.py` (extend)

```python
async def recheck_ebay_sold(session_factory: async_sessionmaker = AsyncSessionLocal) -> int:
    """
    Check 250 oldest non-sold eBay listings and mark as sold if no longer on eBay.
    Called from the existing auto_recheck scheduler job.
    """
    if not settings.ebay_client_id:
        return 0

    async with session_factory() as session:
        stmt = (
            select(Listing.id, Listing.external_id)
            .where(Listing.source == "ebay", Listing.is_sold == False)
            .order_by(Listing.scraped_at.asc())
            .limit(250)
        )
        rows = (await session.execute(stmt)).all()
        sold_count = 0
        async with httpx.AsyncClient() as http_client:
            for row in rows:
                item = await get_item(http_client, row.external_id)
                if item is None:
                    await session.execute(
                        update(Listing).where(Listing.id == row.id).values(is_sold=True)
                    )
                    sold_count += 1
                await asyncio.sleep(0.2)
        await session.commit()
    return sold_count
```

In `backend/app/main.py`, inside the existing `auto_recheck` job function, call `await recheck_ebay_sold()` alongside the rcnetwork recheck.

---

## Task 10: Tests — `test_ebay_client.py` [ ]

**File:** `backend/tests/test_ebay_client.py` (new)

All tests use `pytest` + `unittest.mock.AsyncMock` — no live API calls.

| Test | What it checks |
|---|---|
| `test_token_cached` | Second call reuses cached token (no extra HTTP call) |
| `test_token_refresh_on_expiry` | Expired token triggers new OAuth call |
| `test_search_items_passes_correct_params` | `conditionIds:{3000}`, correct `category_ids`, `offset` |
| `test_get_item_404_returns_none` | 404 response → `None` return |
| `test_get_item_url_encodes_pipes` | `v1|123|0` → `v1%7C123%7C0` in request URL |
| `test_no_op_without_credentials` | `run_ebay_fetch()` returns zeros if `ebay_client_id == ""` |

---

## Task 11: Tests — `test_ebay_orchestrator.py` + fixture [ ]

**Files:** `backend/tests/test_ebay_orchestrator.py` (new), `backend/tests/fixtures/ebay_item_summary.json` (new)

### Fixture `ebay_item_summary.json`

Create a realistic minimal eBay `item_summary` response:

```json
{
  "total": 1,
  "itemSummaries": [
    {
      "itemId": "v1|123456789|0",
      "title": "Robbe Funtana 125 RC Flugzeug gebraucht",
      "price": { "value": "149.00", "currency": "EUR" },
      "condition": "Used",
      "itemCreationDate": "2025-04-10T10:30:00.000Z",
      "itemWebUrl": "https://www.ebay.de/itm/123456789",
      "shortDescription": "Robbe Funtana 125 Verbrenner, gebraucht, flugbereit",
      "image": { "imageUrl": "https://i.ebayimg.com/images/g/abc/s-l500.jpg" },
      "additionalImages": [],
      "itemLocation": { "postalCode": "80331", "city": "München" },
      "seller": { "username": "rc_max_1983", "feedbackScore": 45 },
      "shippingOptions": [
        { "shippingServiceCode": "DHLPaket", "shippingCost": { "value": "6.99", "currency": "EUR" } }
      ]
    }
  ]
}
```

### Tests

| Test | What it checks |
|---|---|
| `test_normalize_item_all_fields` | All 18 fields mapped correctly from fixture |
| `test_normalize_item_external_id_prefix` | `external_id == "ebay_v1|123456789|0"` |
| `test_normalize_item_price_numeric` | `price_numeric == 149.0` (float) |
| `test_normalize_item_condition_mapping` | `"Used"` → `"gebraucht"` |
| `test_normalize_item_datetime_parsing` | `posted_at` is timezone-aware datetime |
| `test_normalize_item_tags_default` | `tags == []` (never None) |
| `test_normalize_item_missing_seller` | `author == ""` when seller object absent |
| `test_normalize_item_shipping_formatted` | `shipping == "Versand 6.99 EUR"` |
| `test_all_known_returns_true_when_all_exist` | Stop-early logic works for known IDs |
| `test_all_known_returns_false_for_new_ids` | Returns False when any ID is new |

---

## Task 12: Update `docs/limitations.md` [ ]

Append to `docs/limitations.md`:

```markdown
## eBay source: private seller filter not available

The eBay Browse API does not expose seller account type (Privatverkäufer vs.
Gewerblich). eBay listings are filtered to `conditionIds:3000` (Used) as a
best-effort proxy for private/used listings. After the first live run, inspect
the `seller` object in actual API responses — if `sellerAccountType` is
available, add a post-filter in `ebay_orchestrator._normalize_item()`.

## eBay source: LLM analysis quality

eBay `shortDescription` fields are typically short headlines (<200 chars),
unlike rc-network multi-paragraph posts. `model_type`/`model_subtype`
extraction quality may be lower for eBay listings. Mitigation: fetch the full
item via `get_item()` before analysis (future improvement).
```

---

## Verification

```bash
# 1. Schema migration applied
docker compose exec backend python -c "
from app.db import engine
import asyncio
from sqlalchemy import text
async def check():
    async with engine.connect() as c:
        r = await c.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='listings' AND column_name='source'\"))
        print('source column:', r.fetchone() is not None)
asyncio.run(check())
"

# 2. Unit tests
docker compose exec backend pytest tests/test_ebay_client.py tests/test_ebay_orchestrator.py -v

# 3. All existing tests still pass
docker compose exec backend pytest tests/ -v

# 4. Manual eBay fetch (requires credentials in .env)
docker compose exec backend python -c "
import asyncio
from app.scraper.ebay_orchestrator import run_ebay_fetch
print(asyncio.run(run_ebay_fetch()))
"

# 5. API source filter
curl -s "http://localhost:8002/api/listings?source=ebay&per_page=5" | python -m json.tool | grep -E '"source"|"total"'

# 6. No-op without credentials (remove EBAY_CLIENT_ID from env, restart backend)
#    run_ebay_fetch() should log "credentials not configured" and return zeros
```
