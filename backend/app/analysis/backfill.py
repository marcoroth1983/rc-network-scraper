"""One-off backfill: analyze all un-analyzed listings with the paid model.

Usage:
    docker compose exec backend python -m app.analysis.backfill [--limit 2500]

Uses OPENROUTER_BATCH_MODEL exclusively (no free model, no daily limit).
Delay between requests: 100ms (paid model, no strict rate limit).
"""

import argparse
import asyncio
import json
import logging
import sys

from sqlalchemy import text

from app.analysis.extractor import ListingAnalysis, analyze_listing
from app.config import settings
from app.db import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BATCH_SIZE = 100
_REQUEST_DELAY_S = 0.1   # 100ms between paid model requests


async def _fetch_batch(offset: int, limit: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT id, title, description, price, condition, category
                FROM listings
                WHERE llm_analyzed = false
                ORDER BY scraped_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]


async def _count_unanalyzed() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM listings WHERE llm_analyzed = false")
        )
        return result.scalar_one()


async def _save_analysis(listing_id: int, analysis: ListingAnalysis) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                UPDATE listings SET
                    manufacturer       = :manufacturer,
                    model_name         = :model_name,
                    drive_type         = :drive_type,
                    model_type         = :model_type,
                    model_subtype      = :model_subtype,
                    completeness       = :completeness,
                    attributes         = :attributes,
                    shipping_available = :shipping_available,
                    llm_analyzed       = true
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
                "shipping_available": analysis.shipping_available,
            },
        )
        await session.commit()


async def _mark_analyzed(listing_id: int) -> None:
    """Mark a listing as analyzed (even on failure) to avoid infinite retry loops."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("UPDATE listings SET llm_analyzed = true WHERE id = :id"),
            {"id": listing_id},
        )
        await session.commit()


async def run_backfill(limit: int) -> None:
    """Run the backfill loop up to `limit` listings."""
    if not settings.OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY is not set — cannot run backfill")
        sys.exit(1)

    total_available = await _count_unanalyzed()
    total_to_process = min(limit, total_available)
    logger.info("Backfill: %d listings to analyze (limit=%d)", total_to_process, limit)

    analyzed = 0
    failed = 0

    while analyzed + failed < total_to_process:
        remaining = total_to_process - (analyzed + failed)
        batch_size = min(_BATCH_SIZE, remaining)
        # offset=0: successfully analyzed listings drop out of the WHERE filter,
        # so re-fetching from offset 0 naturally advances through the queue.
        batch = await _fetch_batch(offset=0, limit=batch_size)

        if not batch:
            logger.info("Backfill: no more listings to process")
            break

        for listing in batch:
            listing_id: int = listing["id"]
            try:
                result = await analyze_listing(
                    title=listing["title"],
                    description=listing["description"] or "",
                    price=listing["price"],
                    condition=listing["condition"],
                    category=listing["category"],
                    model=settings.OPENROUTER_BATCH_MODEL,
                )
                if result.manufacturer is not None or result.model_name is not None or result.model_type is not None:
                    await _save_analysis(listing_id, result)
                    analyzed += 1
                else:
                    logger.warning("Backfill: all-None result for listing %d — marking analyzed", listing_id)
                    await _mark_analyzed(listing_id)
                    failed += 1
            except Exception as exc:
                logger.warning("Backfill: failed for listing %d (%s)", listing_id, exc)
                await _mark_analyzed(listing_id)
                failed += 1

            total_done = analyzed + failed
            if total_done % 100 == 0 or total_done == total_to_process:
                logger.info(
                    "Backfill: %d/%d analyzed (failed=%d)",
                    analyzed,
                    total_to_process,
                    failed,
                )

            await asyncio.sleep(_REQUEST_DELAY_S)

    logger.info(
        "Backfill complete: analyzed=%d, failed=%d out of %d",
        analyzed,
        failed,
        total_to_process,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill listing analysis via OpenRouter")
    parser.add_argument(
        "--limit",
        type=int,
        default=2500,
        help="Maximum number of listings to analyze (default: 2500)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run_backfill(limit=args.limit))
