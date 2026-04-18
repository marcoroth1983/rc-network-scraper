"""Scrape orchestration — coordinates crawler, parser, and DB upsert."""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import CATEGORIES, Category, settings
from app.scraper.crawler import _build_page_url, fetch_listings, fetch_page
from app.scraper.parser import parse_detail

logger = logging.getLogger(__name__)


def _parse_price_numeric(price: str | None) -> float | None:
    """Parse a raw price string to a float.

    Handles formats like:
    - "1300,-€" → 1300.0
    - "275,00 Euro" → 275.0
    - "1 300,00 €" → 1300.0  (space as thousands separator)
    - "700€" → 700.0
    - "120" → 120.0
    - "VB" or None → None
    """
    if not price:
        return None
    cleaned = price.replace('\u00a0', ' ')  # non-breaking space
    cleaned = re.sub(r'(?i)\b(euro|eur|vb)\b', '', cleaned)
    cleaned = cleaned.replace('€', '').replace(',-', '')
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace(' ', '')
    # Strip leading non-digit garbage left by keyword removal (e.g. "." from "VB. 4500")
    cleaned = re.sub(r'^[^\d]+', '', cleaned)
    if ',' in cleaned and '.' in cleaned:
        # Both separators: assume dot=thousands, comma=decimal (e.g. "1.300,00")
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif ',' in cleaned:
        # Only comma: assume comma=decimal (e.g. "275,00")
        cleaned = cleaned.replace(',', '.')
    elif '.' in cleaned:
        # Only dot: if all parts after dots are exactly 3 digits → thousands separator
        # e.g. "10.000" → 10000, but "10.5" → 10.5
        parts = cleaned.split('.')
        if all(len(p) == 3 for p in parts[1:]):
            cleaned = cleaned.replace('.', '')
    # Extract first numeric token only — avoids concatenating multiple prices,
    # e.g. "275leeroder375mitAntrieb" → "275" instead of "275375".
    m = re.search(r'[\d.]+', cleaned)
    if not m:
        return None
    cleaned = m.group(0)
    if cleaned.count('.') > 1:
        return None
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


_USER_AGENT = "rc-markt-scout/0.1 (personal hobby project)"

_UPSERT_SQL = text("""
    INSERT INTO listings (
        external_id, url, title, price, price_numeric, condition, shipping,
        description, images, tags, author, posted_at, posted_at_raw,
        plz, city, latitude, longitude, scraped_at, is_sold, category, created_at
    ) VALUES (
        :external_id, :url, :title, :price, :price_numeric, :condition, :shipping,
        :description, :images, :tags, :author, :posted_at, :posted_at_raw,
        :plz, :city, :latitude, :longitude, :scraped_at, :is_sold, :category, :created_at
    )
    ON CONFLICT (external_id) DO UPDATE SET
        url           = EXCLUDED.url,
        title         = EXCLUDED.title,
        price         = EXCLUDED.price,
        price_numeric = EXCLUDED.price_numeric,
        condition     = EXCLUDED.condition,
        shipping      = EXCLUDED.shipping,
        description   = EXCLUDED.description,
        images        = EXCLUDED.images,
        tags          = EXCLUDED.tags,
        author        = EXCLUDED.author,
        posted_at     = EXCLUDED.posted_at,
        posted_at_raw = EXCLUDED.posted_at_raw,
        plz           = EXCLUDED.plz,
        city          = EXCLUDED.city,
        latitude      = EXCLUDED.latitude,
        longitude     = EXCLUDED.longitude,
        scraped_at    = EXCLUDED.scraped_at,
        is_sold       = EXCLUDED.is_sold OR listings.is_sold,
        sold_at       = CASE
                          WHEN (EXCLUDED.is_sold OR listings.is_sold) AND listings.sold_at IS NULL
                          THEN EXCLUDED.scraped_at
                          ELSE listings.sold_at
                        END,
        category      = EXCLUDED.category
        -- created_at intentionally omitted — never overwritten on conflict
    RETURNING id, (xmax = 0) AS is_insert
""")

MAX_PAGES = 40  # hard safety cap for phase1 stop-early crawl

_EXISTING_IDS_SQL = text("""
    SELECT external_id FROM listings WHERE external_id = ANY(:ids)
""")

_GEO_LOOKUP_SQL = text("""
    SELECT lat, lon
    FROM plz_geodata
    WHERE plz = :plz
    LIMIT 1
""")

_CITY_GEO_LOOKUP_SQL = text("""
    SELECT plz, lat, lon
    FROM plz_geodata
    WHERE LOWER(city) = LOWER(:city)
    LIMIT 1
""")

_INTL_GEO_LOOKUP_SQL = text("""
    SELECT lat, lon
    FROM intl_geodata
    WHERE country = :country AND plz = :plz
    LIMIT 1
""")

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "rc-markt-scout/0.1 (personal hobby project)"}

# Match country prefix in PLZ field: "AT 6890", "CH-8600", "DE01067"
_COUNTRY_PREFIX_RE = re.compile(r'^(AT|CH|DE|LI|NL|BE|FR|LU)\s*[-]?\s*(\d+)', re.IGNORECASE)
# Extract PLZ from city string: "72581 Reutlingen, BW" or "Aue, 08280"
_PLZ_AT_START_RE = re.compile(r'^(\d{4,5})\b')
_PLZ_AT_END_RE = re.compile(r'\b(\d{4,5})\s*[,.]?\s*$')


def _parse_raw_plz(raw: str | None) -> tuple[str | None, str | None]:
    """Parse raw PLZ string → (digits_only, country_2letter | None)."""
    if not raw:
        return None, None
    m = _COUNTRY_PREFIX_RE.match(raw.strip())
    if m:
        return m.group(2), m.group(1).upper()
    digits = re.sub(r'[^0-9]', '', raw.strip())
    return (digits or None), None


def _extract_plz_from_city(city: str) -> str | None:
    """Try to find a 4-5 digit PLZ inside a city string."""
    m = _PLZ_AT_START_RE.match(city.strip())
    if m:
        return m.group(1)
    m = _PLZ_AT_END_RE.search(city.strip())
    if m:
        return m.group(1)
    return None


async def _nominatim_geocode(query: str) -> tuple[float, float] | None:
    """Call Nominatim OSM geocoder. Rate-limit: caller must ensure ≥1s between calls."""
    try:
        async with httpx.AsyncClient(headers=_NOMINATIM_HEADERS, timeout=10.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as exc:
        logger.warning("Nominatim geocode failed for %r: %s", query, exc)
    return None


async def _fetch_existing_ids(
    session: AsyncSession,
    external_ids: list[str],
) -> set[str]:
    """Return the subset of external_ids already in the DB."""
    if not external_ids:
        return set()
    result = await session.execute(_EXISTING_IDS_SQL, {"ids": external_ids})
    return {row[0] for row in result.fetchall()}


async def _geo_lookup(
    session: AsyncSession,
    plz: str | None,
    city: str | None = None,
) -> tuple[float | None, float | None, str | None]:
    """Resolve coordinates from PLZ and/or city. Multi-step fallback chain:
    1. German PLZ lookup (5 digits)
    2. International PLZ lookup (AT/CH, 4 digits)
    3. PLZ extracted from city string
    4. City name lookup (German geodata)
    5. Nominatim OSM geocoder (rate-limited fallback)
    """
    norm_plz, country_hint = _parse_raw_plz(plz)

    # Step 1: German PLZ (5 digits)
    if norm_plz and len(norm_plz) == 5:
        result = await session.execute(_GEO_LOOKUP_SQL, {"plz": norm_plz})
        row = result.fetchone()
        if row:
            return float(row[0]), float(row[1]), norm_plz

    # Step 2: International PLZ (4 digits → AT/CH)
    if norm_plz and len(norm_plz) == 4:
        candidates = [country_hint] if country_hint in ("AT", "CH") else ["AT", "CH"]
        for country in candidates:
            result = await session.execute(_INTL_GEO_LOOKUP_SQL, {"country": country, "plz": norm_plz})
            row = result.fetchone()
            if row:
                return float(row[0]), float(row[1]), norm_plz

    # Step 3: PLZ embedded in city field (e.g. "72581 Reutlingen, BW")
    if city:
        extracted = _extract_plz_from_city(city)
        if extracted and extracted != norm_plz:
            if len(extracted) == 5:
                result = await session.execute(_GEO_LOOKUP_SQL, {"plz": extracted})
                row = result.fetchone()
                if row:
                    return float(row[0]), float(row[1]), extracted
            elif len(extracted) == 4:
                for country in ["AT", "CH"]:
                    result = await session.execute(_INTL_GEO_LOOKUP_SQL, {"country": country, "plz": extracted})
                    row = result.fetchone()
                    if row:
                        return float(row[0]), float(row[1]), extracted

    # Step 4: City name lookup (German geodata, strip PLZ prefix and country suffix)
    if city:
        clean = re.sub(r'^\d{4,5}\s*', '', city).strip()
        clean = re.sub(
            r',?\s*(Deutschland|Germany|Österreich|Austria|Schweiz|Switzerland)\b.*$',
            '', clean, flags=re.IGNORECASE,
        ).strip()
        clean = re.sub(r'\s{2,}', ' ', clean).strip(' ,')
        if clean:
            result = await session.execute(_CITY_GEO_LOOKUP_SQL, {"city": clean})
            row = result.fetchone()
            if row:
                return float(row[1]), float(row[2]), str(row[0])

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


async def _upsert_listing(
    session: AsyncSession,
    external_id: str,
    url: str,
    parsed: dict,
    latitude: float | None,
    longitude: float | None,
    scraped_at: datetime,
    category: str,
) -> tuple[bool, int]:
    """Upsert a listing and return (is_new, listing_id).

    is_new is True if the row was a new insert, False if it was an update.
    listing_id is the DB id of the upserted row.
    """
    result = await session.execute(
        _UPSERT_SQL,
        {
            "external_id": external_id,
            "url": url,
            "title": parsed.get("title") or "",
            "price": parsed.get("price"),
            "price_numeric": _parse_price_numeric(parsed.get("price")),
            "condition": parsed.get("condition"),
            "shipping": parsed.get("shipping"),
            "description": parsed.get("description") or "",
            "images": json.dumps(parsed.get("images") or []),
            "tags": json.dumps(parsed.get("tags") or []),
            "author": parsed.get("author") or "",
            "posted_at": parsed.get("posted_at"),
            "posted_at_raw": parsed.get("posted_at_raw"),
            "plz": parsed.get("plz"),
            "city": parsed.get("city"),
            "latitude": latitude,
            "longitude": longitude,
            "scraped_at": scraped_at,
            "is_sold": parsed.get("is_sold", False),
            "category": category,
            "created_at": scraped_at,
        },
    )
    row = result.fetchone()
    return (bool(row[1]), int(row[0])) if row else (False, 0)


async def _phase1_category(
    session: AsyncSession,
    cat: Category,
    update_progress: Callable[[str], None],
    delay: float,
) -> dict:
    """Phase 1 inner loop for a single category.

    Crawls overview pages for cat.url and upserts new/changed listings.
    Stops when a full page is fully known (ordered newest-first).
    Hard cap at MAX_PAGES as a safety net against parser regressions.

    Returns: {pages_crawled, new, updated, new_ids}
    """
    new_count = 0
    updated_count = 0
    new_ids: list[int] = []
    scraped_at = datetime.now(timezone.utc)

    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            update_progress(f"{cat.label}: Seite {page} scannen…")
            url = _build_page_url(cat.url, page)
            page_listings = await fetch_page(url, client)

            if not page_listings:
                logger.info("Phase 1 [%s]: empty page %d — stopping", cat.key, page)
                return {"pages_crawled": page, "new": new_count, "updated": updated_count, "new_ids": new_ids}

            ids = [item["external_id"] for item in page_listings]
            existing_ids = await _fetch_existing_ids(session, ids)
            new_on_page = [item for item in page_listings if item["external_id"] not in existing_ids]

            if not new_on_page:
                logger.info(
                    "Phase 1 [%s]: page %d fully known — stopping after %d pages",
                    cat.key, page, page,
                )
                return {"pages_crawled": page, "new": new_count, "updated": updated_count, "new_ids": new_ids}

            logger.info("Phase 1 [%s]: page %d has %d new listings", cat.key, page, len(new_on_page))

            for idx, item in enumerate(new_on_page):
                update_progress(f"{cat.label}: Seite {page}: {idx + 1}/{len(new_on_page)} neue Inserate")
                external_id: str = item["external_id"]
                url_detail: str = item["url"]

                try:
                    response = await client.get(url_detail)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "Phase 1 [%s]: HTTP %s for %s — skipping",
                        cat.key, exc.response.status_code, external_id,
                    )
                    continue
                except httpx.RequestError as exc:
                    logger.warning(
                        "Phase 1 [%s]: request error for %s: %s — skipping", cat.key, external_id, exc
                    )
                    continue

                parsed = parse_detail(response.text, page_url=url_detail)
                latitude, longitude, resolved_plz = await _geo_lookup(
                    session, parsed.get("plz"), parsed.get("city")
                )
                parsed["plz"] = resolved_plz

                is_new, listing_id = await _upsert_listing(
                    session=session,
                    external_id=external_id,
                    url=url_detail,
                    parsed=parsed,
                    latitude=latitude,
                    longitude=longitude,
                    scraped_at=scraped_at,
                    category=cat.key,
                )
                await session.commit()

                if is_new:
                    new_count += 1
                    new_ids.append(listing_id)
                    logger.info(
                        "Phase 1 [%s]: NEW   [%s] %s | %s",
                        cat.key,
                        external_id,
                        parsed.get("title", "—")[:60],
                        parsed.get("price", "—"),
                    )
                else:
                    updated_count += 1
                    logger.info(
                        "Phase 1 [%s]: UPD   [%s] %s",
                        cat.key,
                        external_id,
                        parsed.get("title", "—")[:60],
                    )

                if idx < len(new_on_page) - 1:
                    await asyncio.sleep(delay)

            if page < MAX_PAGES:
                await asyncio.sleep(delay)

    logger.warning("Phase 1 [%s]: reached MAX_PAGES cap (%d)", cat.key, MAX_PAGES)
    return {"pages_crawled": MAX_PAGES, "new": new_count, "updated": updated_count, "new_ids": new_ids}


async def _phase1_new_listings(
    session: AsyncSession,
    update_progress: Callable[[str], None],
    delay: float,
) -> dict:
    """Phase 1: crawl all categories sequentially and upsert new/changed listings.

    Iterates over all CATEGORIES in order. Each category runs its own stop-early
    pagination loop independently. No parallelism — intentional to avoid hammering
    the forum.

    Returns: {pages_crawled, new, updated, new_ids}
    """
    total: dict = {"pages_crawled": 0, "new": 0, "updated": 0, "new_ids": []}
    for cat in CATEGORIES:
        update_progress(f"Kategorie: {cat.label}…")
        stats = await _phase1_category(session, cat, update_progress, delay)
        total["pages_crawled"] += stats["pages_crawled"]
        total["new"] += stats["new"]
        total["updated"] += stats["updated"]
        total["new_ids"] += stats["new_ids"]
    return total


_RECHECK_SQL = text("""
    SELECT id, url, external_id
    FROM listings
    WHERE is_sold = FALSE
    ORDER BY scraped_at ASC
    LIMIT :limit
""")


async def _phase2_sold_recheck(
    session: AsyncSession,
    update_progress: Callable[[str], None],
    delay: float,
    batch_size: int = 100,
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
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404, 410):
                    logger.info(
                        "Phase 2: %s returned %d — marking as SOLD",
                        external_id, exc.response.status_code,
                    )
                    await session.execute(
                        text("""
                            UPDATE listings
                            SET is_sold = TRUE,
                                sold_at = CASE WHEN sold_at IS NULL THEN :now ELSE sold_at END,
                                scraped_at = :now
                            WHERE id = :id
                        """),
                        {"now": now, "id": listing_id},
                    )
                    await session.commit()
                    rechecked += 1
                    sold_found += 1
                else:
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
            except httpx.RequestError as exc:
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
                text("""
                    UPDATE listings
                    SET is_sold = :is_sold,
                        sold_at = CASE WHEN :is_sold AND sold_at IS NULL THEN :now ELSE sold_at END,
                        scraped_at = :now
                    WHERE id = :id
                """),
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


async def _phase3_cleanup(session: AsyncSession) -> dict:
    """Phase 3: clean up sold and stale listings per retention policy.

    Retention rules:
    - Sold listings with scraped_at older than 2 weeks: strip images (kept forever for seller history)
    - Non-sold listings with posted_at older than 8 weeks: delete
      (listings with NULL posted_at are excluded and kept indefinitely)

    Returns: {cleaned_sold, deleted_stale}
    """
    now = datetime.now(timezone.utc)
    two_weeks_ago = now - timedelta(weeks=2)
    eight_weeks_ago = now - timedelta(weeks=8)

    sold_result = await session.execute(
        text("""
            UPDATE listings SET images = '[]'::jsonb
            WHERE is_sold = TRUE AND scraped_at < :cutoff AND images != '[]'::jsonb
            RETURNING id
        """),
        {"cutoff": two_weeks_ago},
    )
    cleaned_sold = len(sold_result.fetchall())

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
        "Phase 3: cleaned images from %d sold + deleted %d stale listings", cleaned_sold, deleted_stale
    )
    return {"cleaned_sold": cleaned_sold, "deleted_stale": deleted_stale}
