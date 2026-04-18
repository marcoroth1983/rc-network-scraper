"""eBay scrape orchestration — normalize, geo-lookup, upsert, sold-recheck."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings, EBAY_CATEGORY_MAP
from app.db import AsyncSessionLocal
from app.models import Listing
from app.scraper.ebay_client import get_item, search_items
from app.scraper.orchestrator import _geo_lookup

logger = logging.getLogger(__name__)

MAX_PAGES = 5
PAGE_SIZE = 200

_CONDITION_MAP = {
    "New":                       "neu",
    "Like New":                  "neuwertig",
    "Very Good - Refurbished":   "neuwertig",
    "Good - Refurbished":        "gebraucht",
    "Seller Refurbished":        "gebraucht",
    "Used":                      "gebraucht",
    "For parts or not working":  "defekt",
}

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
        price         = EXCLUDED.price,
        price_numeric = EXCLUDED.price_numeric,
        scraped_at    = NOW()
    RETURNING (xmax = 0) AS inserted
""")


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
    condition = _CONDITION_MAP.get(condition_raw)  # unknown strings → None, not raw English

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
        "images": json.dumps(images),
        "tags": json.dumps([]),
        "category": category_slug,
        "source": "ebay",
        "shipping": shipping,
    }


async def _all_known(session: AsyncSession, external_ids: list[str]) -> bool:
    """Return True if every external_id in the list already exists in the DB."""
    if not external_ids:
        return True
    result = await session.execute(
        select(Listing.external_id).where(Listing.external_id.in_(external_ids))
    )
    known = {row[0] for row in result}
    return known.issuperset(external_ids)


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
                        lat, lon, _resolved_plz = await _geo_lookup(session, plz_raw, city_raw)

                        row = _normalize_item(item, category_slug, lat, lon)
                        result = await session.execute(_UPSERT_SQL, row)
                        inserted = result.scalar()
                        if inserted:
                            total_new += 1
                        else:
                            total_updated += 1

                    await session.commit()

    logger.info(
        "eBay fetch done: new=%d updated=%d skipped=%d",
        total_new, total_updated, total_skipped,
    )
    return {"total_new": total_new, "total_updated": total_updated, "total_skipped": total_skipped}


async def recheck_ebay_sold(session_factory: async_sessionmaker = AsyncSessionLocal) -> int:
    """
    Check 250 oldest non-sold eBay listings and mark as sold if no longer on eBay.
    Returns the number of listings marked as sold.
    """
    if not settings.ebay_client_id:
        return 0

    async with session_factory() as session:
        stmt = (
            select(Listing.id, Listing.external_id)
            .where(Listing.source == "ebay", Listing.is_sold == False)  # noqa: E712
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
                else:
                    # Update scraped_at so this listing moves to the back of the recheck queue
                    await session.execute(
                        update(Listing).where(Listing.id == row.id).values(scraped_at=func.now())
                    )
                await asyncio.sleep(0.2)
        await session.commit()
    return sold_count
