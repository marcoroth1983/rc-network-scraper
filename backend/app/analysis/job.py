"""Scheduled analysis job: extract structured product data from unanalyzed listings."""

import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy import text

from app.analysis.extractor import analyze_listing
from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Listing

logger = logging.getLogger(__name__)

BATCH_SIZE = 3
DELAY_SECONDS = 3.0  # respects ~20 req/min free tier limit


async def run_analysis_job() -> None:
    """Pick up to BATCH_SIZE unanalyzed listings, run LLM, update DB."""
    if not settings.OPENROUTER_API_KEY:
        logger.info("Analysis job: OPENROUTER_API_KEY not set — skipping")
        return

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Listing)
            .where(Listing.llm_analyzed == False)  # noqa: E712
            .order_by(Listing.scraped_at.desc())
            .limit(BATCH_SIZE)
        )
        listings = rows.scalars().all()

    if not listings:
        logger.info("Analysis job: no unanalyzed listings")
        return

    logger.info("Analysis job: processing %d listings", len(listings))

    for listing in listings:
        result = await analyze_listing(
            title=listing.title,
            description=listing.description or "",
            price=listing.price,
            condition=listing.condition,
            category=listing.category or "",
        )
        update_vals: dict = {
            "llm_analyzed": True,
            "manufacturer": result.manufacturer,
            "model_name": result.model_name,
            "drive_type": result.drive_type,
            "model_type": result.model_type,
            "model_subtype": result.model_subtype,
            "completeness": result.completeness,
            "attributes": result.attributes,
            "shipping_available": result.shipping_available,
        }
        if result.price_euros is not None:
            update_vals["price_numeric"] = result.price_euros

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Listing).where(Listing.id == listing.id).values(**update_vals)
            )
            await session.commit()

        await asyncio.sleep(DELAY_SECONDS)

    await recalculate_price_indicators()
    logger.info("Analysis job: price indicators recalculated")


async def recalculate_price_indicators() -> None:
    """Assign price bands to active non-sold listings using two-level grouping.

    Level 1: manufacturer + model_name (min 5 listings)
    Level 2: model_type + model_subtype + completeness (min 5 listings)
    Bands: deal < median*0.75 <= fair <= median*1.25 < expensive
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            WITH medians_l1 AS (
                SELECT manufacturer, model_name,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median
                FROM listings
                WHERE price_numeric IS NOT NULL
                  AND is_sold = false
                  AND manufacturer IS NOT NULL
                  AND model_name IS NOT NULL
                GROUP BY manufacturer, model_name
                HAVING COUNT(*) >= 5
            ),
            medians_l2 AS (
                SELECT model_type, model_subtype, completeness,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY price_numeric) AS median
                FROM listings
                WHERE price_numeric IS NOT NULL
                  AND is_sold = false
                  AND model_type IS NOT NULL
                  AND model_subtype IS NOT NULL
                  AND completeness IS NOT NULL
                GROUP BY model_type, model_subtype, completeness
                HAVING COUNT(*) >= 5
            ),
            new_indicators AS (
                SELECT
                    l.id,
                    CASE
                        WHEN m1.median IS NOT NULL AND l.price_numeric <= m1.median * 0.75 THEN 'deal'
                        WHEN m1.median IS NOT NULL AND l.price_numeric >= m1.median * 1.25 THEN 'expensive'
                        WHEN m1.median IS NOT NULL THEN 'fair'
                        WHEN m2.median IS NOT NULL AND l.price_numeric <= m2.median * 0.75 THEN 'deal'
                        WHEN m2.median IS NOT NULL AND l.price_numeric >= m2.median * 1.25 THEN 'expensive'
                        WHEN m2.median IS NOT NULL THEN 'fair'
                        ELSE NULL
                    END AS indicator
                FROM listings l
                LEFT JOIN medians_l1 m1
                    ON m1.manufacturer = l.manufacturer AND m1.model_name = l.model_name
                LEFT JOIN medians_l2 m2
                    ON m2.model_type = l.model_type
                   AND m2.model_subtype = l.model_subtype
                   AND m2.completeness = l.completeness
                WHERE l.price_numeric IS NOT NULL AND l.is_sold = false
            )
            UPDATE listings
            SET price_indicator = ni.indicator
            FROM new_indicators ni
            WHERE listings.id = ni.id
        """))
        await session.commit()
