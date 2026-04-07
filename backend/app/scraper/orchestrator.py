"""Scrape orchestration — coordinates crawler, parser, and DB upsert."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.scraper.crawler import _build_page_url, fetch_listings, fetch_page
from app.scraper.parser import parse_detail

logger = logging.getLogger(__name__)

_USER_AGENT = "rc-markt-scout/0.1 (personal hobby project)"
_START_URL = "https://www.rc-network.de/forums/biete-flugmodelle.132/"

_UPSERT_SQL = text("""
    INSERT INTO listings (
        external_id, url, title, price, condition, shipping,
        description, images, tags, author, posted_at, posted_at_raw,
        plz, city, latitude, longitude, scraped_at, is_sold
    ) VALUES (
        :external_id, :url, :title, :price, :condition, :shipping,
        :description, :images, :tags, :author, :posted_at, :posted_at_raw,
        :plz, :city, :latitude, :longitude, :scraped_at, :is_sold
    )
    ON CONFLICT (external_id) DO UPDATE SET
        url          = EXCLUDED.url,
        title        = EXCLUDED.title,
        price        = EXCLUDED.price,
        condition    = EXCLUDED.condition,
        shipping     = EXCLUDED.shipping,
        description  = EXCLUDED.description,
        images       = EXCLUDED.images,
        tags         = EXCLUDED.tags,
        author       = EXCLUDED.author,
        posted_at    = EXCLUDED.posted_at,
        posted_at_raw = EXCLUDED.posted_at_raw,
        plz          = EXCLUDED.plz,
        city         = EXCLUDED.city,
        latitude     = EXCLUDED.latitude,
        longitude    = EXCLUDED.longitude,
        scraped_at   = EXCLUDED.scraped_at,
        is_sold      = EXCLUDED.is_sold OR listings.is_sold
    RETURNING (xmax = 0) AS is_insert
""")

MAX_PAGES = 25  # hard safety cap for phase1 stop-early crawl

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
    """Look up lat/lon by PLZ; fall back to city name. Returns (lat, lon, resolved_plz)."""
    if plz:
        result = await session.execute(_GEO_LOOKUP_SQL, {"plz": plz})
        row = result.fetchone()
        if row:
            return float(row[0]), float(row[1]), plz
    if city:
        result = await session.execute(_CITY_GEO_LOOKUP_SQL, {"city": city})
        row = result.fetchone()
        if row:
            return float(row[1]), float(row[2]), str(row[0])
    return None, None, plz


async def _upsert_listing(
    session: AsyncSession,
    external_id: str,
    url: str,
    parsed: dict,
    latitude: float | None,
    longitude: float | None,
    scraped_at: datetime,
) -> bool:
    """Upsert a listing and return True if it was a new insert, False if an update."""
    result = await session.execute(
        _UPSERT_SQL,
        {
            "external_id": external_id,
            "url": url,
            "title": parsed.get("title") or "",
            "price": parsed.get("price"),
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
        },
    )
    row = result.fetchone()
    return bool(row[0]) if row else False


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


async def run_scrape(session: AsyncSession, max_pages: int = 10, fresh_threshold_days: int = 7) -> dict:
    """Deprecated shim — superseded by scrape_runner.run_scrape_job. Removed in Task 7."""
    logger.warning("run_scrape shim called — consider using run_scrape_job directly")
    return {"pages_crawled": 0, "listings_found": 0, "new": 0, "updated": 0, "skipped": 0}
