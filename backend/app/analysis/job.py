"""Scheduled analysis job: extract structured product data from unanalyzed listings."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.extractor import ListingAnalysis, analyze_listing
from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_FREE_MODEL_DELAY_S = 3.0   # 20 req/min cap → 3s between requests
_PAID_MODEL_DELAY_S = 0.1   # paid model, no strict rate limit
_MAX_RETRIES = 3


async def _fetch_unanalyzed(session: AsyncSession) -> list[dict]:
    """Fetch up to _BATCH_SIZE listings that have not yet been analyzed."""
    result = await session.execute(
        text("""
            SELECT id, title, description, price, condition, category
            FROM listings
            WHERE analyzed_at IS NULL
              AND analysis_retries < :max_retries
            ORDER BY scraped_at DESC
            LIMIT :limit
        """),
        {"max_retries": _MAX_RETRIES, "limit": _BATCH_SIZE},
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def _update_listing_analysis(
    session: AsyncSession,
    listing_id: int,
    analysis: ListingAnalysis,
) -> None:
    """Persist extracted analysis fields and mark analyzed_at."""
    await session.execute(
        text("""
            UPDATE listings SET
                manufacturer    = :manufacturer,
                model_name      = :model_name,
                drive_type      = :drive_type,
                model_type      = :model_type,
                model_subtype   = :model_subtype,
                completeness    = :completeness,
                attributes      = :attributes,
                analyzed_at     = :analyzed_at,
                analysis_retries = 0
            WHERE id = :id
        """),
        {
            "id": listing_id,
            "manufacturer": analysis.manufacturer,
            "model_name": analysis.model_name,
            "drive_type": analysis.drive_type,
            "model_type": analysis.model_type,
            "model_subtype": analysis.model_subtype,
            "completeness": analysis.completeness,
            "attributes": json.dumps(analysis.attributes),
            "analyzed_at": datetime.now(timezone.utc),
        },
    )
    await session.commit()


async def _increment_retries(session: AsyncSession, listing_id: int) -> None:
    """Increment analysis_retries counter so failing listings eventually get skipped."""
    await session.execute(
        text("UPDATE listings SET analysis_retries = analysis_retries + 1 WHERE id = :id"),
        {"id": listing_id},
    )
    await session.commit()


async def run_analysis_job() -> None:
    """Analyze unprocessed listings. Called on schedule by APScheduler.

    Uses the free OpenRouter model with a 3-second delay between requests.
    Falls back to the paid model once per listing if the free model fails.
    Listings that fail both attempts have their analysis_retries counter
    incremented; they are skipped after _MAX_RETRIES failures.
    """
    if not settings.OPENROUTER_API_KEY:
        logger.info("Analysis job: OPENROUTER_API_KEY not set — skipping")
        return

    async with AsyncSessionLocal() as session:
        listings = await _fetch_unanalyzed(session)

    if not listings:
        logger.info("Analysis job: no unanalyzed listings found")
        return

    logger.info("Analysis job: starting batch of %d listings", len(listings))

    analyzed = 0
    failed = 0

    for listing in listings:
        listing_id: int = listing["id"]
        title: str = listing["title"]
        description: str = listing["description"] or ""
        price: str | None = listing["price"]
        condition: str | None = listing["condition"]
        category: str = listing["category"]

        # Attempt 1: free model
        analysis: ListingAnalysis | None = None
        try:
            result = await analyze_listing(
                title=title,
                description=description,
                price=price,
                condition=condition,
                category=category,
                model=settings.OPENROUTER_MODEL,
            )
            # An all-None result (empty analysis) from a non-empty response is treated as failure
            if result.manufacturer is not None or result.model_name is not None or result.model_type is not None:
                analysis = result
        except Exception as exc:
            logger.warning(
                "Analysis job: free model failed for listing %d (%s)", listing_id, exc
            )

        if analysis is None:
            # Attempt 2: paid fallback model
            await asyncio.sleep(_PAID_MODEL_DELAY_S)
            try:
                result = await analyze_listing(
                    title=title,
                    description=description,
                    price=price,
                    condition=condition,
                    category=category,
                    model=settings.OPENROUTER_BATCH_MODEL,
                )
                if result.manufacturer is not None or result.model_name is not None or result.model_type is not None:
                    analysis = result
            except Exception as exc:
                logger.warning(
                    "Analysis job: paid fallback also failed for listing %d (%s)",
                    listing_id,
                    exc,
                )

        try:
            async with AsyncSessionLocal() as session:
                if analysis is not None:
                    await _update_listing_analysis(session, listing_id, analysis)
                    analyzed += 1
                else:
                    await _increment_retries(session, listing_id)
                    failed += 1
        except Exception as exc:
            logger.error("Analysis job: DB error for listing %d: %s", listing_id, exc)
            failed += 1

        await asyncio.sleep(_FREE_MODEL_DELAY_S)

    logger.info("Analysis job: analyzed=%d, failed=%d", analyzed, failed)
