"""Post-scrape matching service: check new listings against all active saved searches."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Listing, SavedSearch, SearchNotification
from app.notifications.base import MatchResult
from app.notifications.registry import notification_registry
from app.services.listing_filter import build_text_filter, filter_by_distance

logger = logging.getLogger(__name__)


async def check_new_matches(
    session: AsyncSession,
    new_ids: list[int],
) -> int:
    """Check all active saved searches for new matches.

    Returns total number of new matches across all searches.
    """
    if not new_ids:
        return 0

    # Load all active saved searches
    searches_result = await session.execute(
        select(SavedSearch).where(SavedSearch.is_active.is_(True))
    )
    active_searches = list(searches_result.scalars().all())

    total_matches = 0

    for saved_search in active_searches:
        async with session.begin_nested():
            try:
                matched = await _match_search(session, saved_search, new_ids)
                total_matches += matched
            except Exception:
                logger.exception(
                    "Matcher failed for saved search id=%d — skipping",
                    saved_search.id,
                )
        # Commit after each search so successful ones are persisted even if a later one fails
        await session.commit()

    return total_matches


async def _match_search(
    session: AsyncSession,
    saved_search: SavedSearch,
    new_ids: list[int],
) -> int:
    """Process one saved search against the given new listing IDs.

    Returns the number of new notification rows inserted.
    """
    # Build SQL query: WHERE id IN (new_ids) + text filter clauses + optional category filter
    stmt = select(Listing).where(Listing.id.in_(new_ids))
    for clause in build_text_filter(saved_search.search):
        stmt = stmt.where(clause)
    if saved_search.category:
        stmt = stmt.where(Listing.category == saved_search.category)

    candidates_result = await session.execute(stmt)
    candidates = list(candidates_result.scalars().all())

    if not candidates:
        await _update_last_checked(session, saved_search)
        return 0

    # Apply distance filter if PLZ + max_distance are set
    if saved_search.plz and saved_search.max_distance is not None:
        pairs = await filter_by_distance(
            candidates, saved_search.plz, saved_search.max_distance, session
        )
        candidates = [listing for listing, _ in pairs]
    elif saved_search.plz:
        # PLZ without max_distance — no filtering, just pass all candidates through
        pass

    if not candidates:
        await _update_last_checked(session, saved_search)
        return 0

    # Exclude listing IDs already notified for this search
    candidate_ids = [c.id for c in candidates]
    already_result = await session.execute(
        select(SearchNotification.listing_id).where(
            SearchNotification.saved_search_id == saved_search.id,
            SearchNotification.listing_id.in_(candidate_ids),
        )
    )
    already_notified_ids = {row[0] for row in already_result.fetchall()}
    new_candidates = [c for c in candidates if c.id not in already_notified_ids]

    if not new_candidates:
        await _update_last_checked(session, saved_search)
        return 0

    # Insert new notifications (ON CONFLICT DO NOTHING for safety)
    rows = [
        {"saved_search_id": saved_search.id, "listing_id": c.id}
        for c in new_candidates
    ]
    await session.execute(
        pg_insert(SearchNotification)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_search_listing")
    )

    # Dispatch via notification registry
    match_result = MatchResult(
        saved_search_id=saved_search.id,
        search_name=saved_search.name or "Unbenannte Suche",
        user_id=saved_search.user_id,
        new_listing_ids=[c.id for c in new_candidates],
        new_listing_titles=[c.title for c in new_candidates],
        total_new=len(new_candidates),
    )
    await notification_registry.dispatch(match_result)

    await _update_last_checked(session, saved_search)
    return len(new_candidates)


async def _update_last_checked(session: AsyncSession, saved_search: SavedSearch) -> None:
    """Update last_checked_at to now for a saved search."""
    saved_search.last_checked_at = datetime.now(timezone.utc)
    session.add(saved_search)
