"""Scheduled analysis job: extract structured product data from unanalyzed listings."""

import asyncio
import logging

from sqlalchemy import select, update

from app.analysis.extractor import analyze_listing
from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Listing

logger = logging.getLogger(__name__)

BATCH_SIZE = 3
DELAY_SECONDS = 3.0  # respects ~20 req/min free tier limit


async def run_analysis_job() -> None:
    """Pick up to BATCH_SIZE unanalyzed listings, run LLM, update DB."""
    if not settings.LLM_ANALYSIS_ENABLED:
        logger.info("Analysis job: LLM_ANALYSIS_ENABLED=false — skipping")
        return
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

    logger.info("Analysis job: processing %d listings [ids=%s]", len(listings), [l.id for l in listings])

    for listing in listings:
        logger.info("Analysis job: analyzing id=%d \"%s\"", listing.id, listing.title[:60])
        result = await analyze_listing(
            title=listing.title,
            description=listing.description or "",
            price=listing.price,
            condition=listing.condition,
            category=listing.category or "",
            listing_id=listing.id,
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

        any_data = any(v for v in [result.model_type, result.drive_type, result.completeness, result.manufacturer])
        if any_data:
            logger.info(
                "Analysis job: id=%d saved — type=%s drive=%s completeness=%s manufacturer=%s",
                listing.id, result.model_type, result.drive_type, result.completeness, result.manufacturer,
            )
        else:
            logger.warning("Analysis job: id=%d saved with EMPTY result (LLM returned no data)", listing.id)

        await asyncio.sleep(DELAY_SECONDS)
