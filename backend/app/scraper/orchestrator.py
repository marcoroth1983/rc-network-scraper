"""Scrape orchestration — coordinates crawler, parser, and DB upsert."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.scraper.crawler import fetch_listings
from app.scraper.parser import parse_detail

logger = logging.getLogger(__name__)

_USER_AGENT = "rc-markt-scout/0.1 (personal hobby project)"
_START_URL = "https://www.rc-network.de/forums/biete-flugmodelle.132/"

_UPSERT_SQL = text("""
    INSERT INTO listings (
        external_id, url, title, price, condition, shipping,
        description, images, author, posted_at, posted_at_raw,
        plz, city, latitude, longitude, scraped_at, is_sold
    ) VALUES (
        :external_id, :url, :title, :price, :condition, :shipping,
        :description, :images, :author, :posted_at, :posted_at_raw,
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

_FRESH_IDS_SQL = text("""
    SELECT external_id
    FROM listings
    WHERE external_id = ANY(:ids)
      AND scraped_at > :threshold
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


async def _fetch_fresh_ids(
    session: AsyncSession,
    external_ids: list[str],
    threshold: datetime,
) -> set[str]:
    """Return the subset of external_ids that are already fresh in the DB."""
    if not external_ids:
        return set()
    result = await session.execute(
        _FRESH_IDS_SQL,
        {"ids": external_ids, "threshold": threshold},
    )
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


async def run_scrape(
    session: AsyncSession,
    max_pages: int = 10,
    fresh_threshold_days: int = 7,
) -> dict:
    """Run a full scrape cycle and return a summary dict.

    Args:
        session: Async SQLAlchemy session.
        max_pages: Maximum number of overview pages to crawl.
        fresh_threshold_days: Listings scraped within this many days are skipped.

    Returns:
        Dict with keys: pages_crawled, listings_found, new, updated, skipped.
    """
    delay: float = settings.SCRAPE_DELAY

    # Step 1: Crawl overview pages
    logger.info("Starting scrape — max_pages=%d, fresh_threshold_days=%d", max_pages, fresh_threshold_days)
    all_listings = await fetch_listings(_START_URL, max_pages=max_pages, delay=delay)

    pages_crawled = max_pages  # fetch_listings stops early on empty page, but we report requested
    listings_found = len(all_listings)
    logger.info("Crawler returned %d listings across up to %d pages", listings_found, max_pages)

    if not all_listings:
        return {
            "pages_crawled": pages_crawled,
            "listings_found": 0,
            "new": 0,
            "updated": 0,
            "skipped": 0,
        }

    # Step 2: Determine fresh IDs to skip
    fresh_threshold = datetime.now(timezone.utc) - timedelta(days=fresh_threshold_days)
    all_ids = [item["external_id"] for item in all_listings]
    fresh_ids = await _fetch_fresh_ids(session, all_ids, fresh_threshold)

    to_process = [item for item in all_listings if item["external_id"] not in fresh_ids]
    skipped = len(fresh_ids)
    logger.info(
        "Fresh (skipped): %d  |  To process (new + stale): %d",
        skipped,
        len(to_process),
    )

    # Step 3: Fetch, parse, enrich, and upsert each non-fresh listing
    new_count = 0
    updated_count = 0
    scraped_at = datetime.now(timezone.utc)

    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for idx, item in enumerate(to_process):
            external_id: str = item["external_id"]
            url: str = item["url"]

            logger.info(
                "[%d/%d] Fetching detail: %s",
                idx + 1,
                len(to_process),
                url,
            )

            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "HTTP %s for listing %s — skipping",
                    exc.response.status_code,
                    external_id,
                )
                skipped += 1
                continue
            except httpx.RequestError as exc:
                logger.warning("Request error for listing %s: %s — skipping", external_id, exc)
                skipped += 1
                continue

            parsed = parse_detail(response.text, page_url=url)

            # Geo enrichment — falls back to city name when PLZ is missing
            latitude, longitude, resolved_plz = await _geo_lookup(
                session, parsed.get("plz"), parsed.get("city")
            )
            parsed["plz"] = resolved_plz  # store resolved PLZ (may come from city lookup)

            is_new = await _upsert_listing(
                session=session,
                external_id=external_id,
                url=url,
                parsed=parsed,
                latitude=latitude,
                longitude=longitude,
                scraped_at=scraped_at,
            )
            await session.commit()

            if is_new:
                new_count += 1
                logger.debug("Inserted new listing %s", external_id)
            else:
                updated_count += 1
                logger.debug("Updated existing listing %s", external_id)

            # Respect rate limit between requests (skip delay after last item)
            if idx < len(to_process) - 1:
                await asyncio.sleep(delay)

    summary = {
        "pages_crawled": pages_crawled,
        "listings_found": listings_found,
        "new": new_count,
        "updated": updated_count,
        "skipped": skipped,
    }
    logger.info("Scrape complete: %s", summary)
    return summary
