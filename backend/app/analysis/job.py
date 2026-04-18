"""Scheduled analysis job: extract structured product data from unanalyzed listings."""

import asyncio
import logging
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy import text

from app.analysis.extractor import analyze_listing
from app.analysis.similarity import (
    score as similarity_score,
    assess_homogeneity,
)
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


async def recalculate_price_indicators() -> None:
    """Set price indicator only when the per-listing similarity cluster is homogeneous.

    For each active priced listing with a non-NULL model_type:
      - Build candidate pool from same model_type.
      - Score + rank.
      - Assess homogeneity of top-20.
      - Set deal/fair/expensive only when homogeneous; otherwise NULL.
    Listings without model_type get price_indicator = NULL (unscorable).
    """
    async with AsyncSessionLocal() as session:
        all_rows = (await session.execute(
            select(Listing).where(
                Listing.is_sold == False,       # noqa: E712
                Listing.price_numeric.is_not(None),
            )
        )).scalars().all()

    by_type: dict[str | None, list[Listing]] = defaultdict(list)
    for r in all_rows:
        by_type[r.model_type].append(r)

    updates: list[tuple[int, str | None, float | None, int]] = []

    for base in all_rows:
        if not base.model_type:
            updates.append((base.id, None, None, 0))
            continue

        candidates = [c for c in by_type[base.model_type] if c.id != base.id]
        scored = [(c, similarity_score(base, c)) for c in candidates]
        scored = [(c, s) for c, s in scored if s > 0.0]
        scored.sort(key=lambda t: (-t[1], float(t[0].price_numeric or 0)))
        top = scored[:20]

        quality, median_val = assess_homogeneity(base, top)

        if quality != "homogeneous" or median_val is None:
            updates.append((base.id, None, None, len(top)))
            continue

        base_p = float(base.price_numeric)
        if base_p <= median_val * 0.75:
            ind = "deal"
        elif base_p >= median_val * 1.25:
            ind = "expensive"
        else:
            ind = "fair"
        updates.append((base.id, ind, median_val, len(top)))

    # Bulk update in chunks via executemany-style loop. 3500 rows × ~1 ms round-trip
    # is acceptable for a 15-min job.
    async with AsyncSessionLocal() as session:
        for lid, ind, med, cnt in updates:
            await session.execute(
                text("""
                    UPDATE listings SET
                        price_indicator = :ind,
                        price_indicator_median = :med,
                        price_indicator_count = :cnt
                    WHERE id = :lid
                """),
                {"lid": lid, "ind": ind, "med": med, "cnt": cnt},
            )
        await session.commit()

    logger.info(
        "price_indicator recalc: processed %d listings, %d homogeneous",
        len(updates),
        sum(1 for _, ind, _, _ in updates if ind is not None),
    )
