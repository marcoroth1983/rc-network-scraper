"""REST API endpoints."""

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.similarity import (
    score as similarity_score,
    assess_homogeneity,
)
from app.api.admin import router as admin_router
from app.api.telegram import router as telegram_api_router
from app.api.deps import get_current_user
from app.api.schemas import (
    ComparableListing, ComparablesResponse,
    ListingDetail, ListingSummary, PaginatedResponse, PlzResponse,
    SavedSearchCreate, SavedSearchResponse, SavedSearchUpdate,
    ScrapeSummary, ScrapeStatus, ScrapeLogEntry,
)
from app.analysis.vocabulary import MODEL_TYPES
from app.config import CATEGORIES, CATEGORY_KEYS
from app.db import get_session
from app.models import Listing, PlzGeodata, SavedSearch, SearchNotification, User, UserFavorite
from app.scrape_runner import get_state, get_log, start_update_job
from app.services.listing_filter import build_text_filter, filter_by_distance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
router.include_router(admin_router)
router.include_router(telegram_api_router)


async def _get_favorite_listing_ids(user_id: int, session: AsyncSession) -> set[int]:
    """Return set of listing IDs favorited by the given user. One DB round-trip."""
    result = await session.execute(
        select(UserFavorite.listing_id).where(UserFavorite.user_id == user_id)
    )
    return {row for (row,) in result.all()}


@router.post("/scrape", status_code=202)
async def start_scrape(_: User = Depends(get_current_user)) -> dict:
    """Trigger a background update job (Phase 1). Returns 409 if already running."""
    logger.info("POST /api/scrape — triggering update job")
    started = await start_update_job()
    if not started:
        raise HTTPException(status_code=409, detail="Scrape already running")
    return {"status": "started"}


@router.get("/scrape/status", response_model=ScrapeStatus)
async def scrape_status(_: User = Depends(get_current_user)) -> ScrapeStatus:
    """Return current scrape job status for frontend polling."""
    state = get_state()
    summary_data = state.get("summary")
    summary = ScrapeSummary(**summary_data) if summary_data else None
    return ScrapeStatus(
        status=state["status"],
        job_type=state.get("job_type"),
        started_at=state["started_at"],
        finished_at=state["finished_at"],
        phase=state["phase"],
        progress=state["progress"],
        summary=summary,
        error=state["error"],
    )


@router.get("/scrape/log", response_model=list[ScrapeLogEntry])
async def scrape_log(_: User = Depends(get_current_user)) -> list[ScrapeLogEntry]:
    """Return in-memory scrape run history, newest first (max 50 entries)."""
    entries = get_log()
    result = []
    for entry in entries:
        summary_data = entry.get("summary")
        summary = ScrapeSummary(**summary_data) if summary_data else None
        result.append(ScrapeLogEntry(
            job_type=entry["job_type"],
            finished_at=entry["finished_at"],
            summary=summary,
            error=entry.get("error"),
        ))
    return result


@router.get("/geo/plz/{plz}", response_model=PlzResponse)
async def resolve_plz(
    plz: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> PlzResponse:
    """Resolve a German PLZ to coordinates. Returns 404 if PLZ not found."""
    result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PLZ not found")
    return PlzResponse.model_validate(row)


@router.get("/categories")
async def get_categories(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """Return all categories with their listing counts."""
    counts_result = await session.execute(
        select(Listing.category, func.count()).group_by(Listing.category)
    )
    count_map = dict(counts_result.all())
    return [
        {"key": c.key, "label": c.label, "count": count_map.get(c.key, 0)}
        for c in CATEGORIES
    ]


@router.get("/listings", response_model=PaginatedResponse)
async def list_listings(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    sort: Literal["date", "price", "distance"] = Query(default="date"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    plz: str | None = Query(default=None),
    max_distance: int | None = Query(default=None, ge=1),
    category: str | None = Query(default=None),
    price_min: float | None = Query(default=None, ge=0),
    price_max: float | None = Query(default=None, ge=0),
    drive_type: str | None = Query(default=None),
    completeness: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    model_subtype: str | None = Query(default=None),
    source: Literal["rcnetwork", "ebay"] | None = Query(default=None),
    shipping_available: bool | None = Query(default=None),
    price_indicator: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse:
    """Return a paginated, filterable, sortable list of listings."""
    # Validate parameter combinations
    if sort == "distance" and plz is None:
        raise HTTPException(status_code=400, detail="plz is required when sort=distance")
    if max_distance is not None and plz is None:
        raise HTTPException(status_code=400, detail="plz is required when max_distance is set")
    if category is not None and category != "all" and category not in CATEGORY_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown category: '{category}'")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(status_code=400, detail="price_min must be <= price_max")
    if model_type is not None and model_type not in MODEL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown model_type: '{model_type}'")

    fav_ids = await _get_favorite_listing_ids(current_user.id, session)

    offset = (page - 1) * per_page
    asc = sort_dir == "asc"

    # Base statement with optional search filter and optional category filter
    stmt = select(Listing)
    for clause in build_text_filter(search):
        stmt = stmt.where(clause)
    if category and category != "all":
        stmt = stmt.where(Listing.category == category)
    if price_min is not None or price_max is not None:
        stmt = stmt.where(Listing.price_numeric.is_not(None))
    if price_min is not None:
        stmt = stmt.where(Listing.price_numeric >= price_min)
    if price_max is not None:
        stmt = stmt.where(Listing.price_numeric <= price_max)
    if drive_type:
        stmt = stmt.where(Listing.drive_type == drive_type)
    if completeness:
        stmt = stmt.where(Listing.completeness == completeness)
    if model_type:
        stmt = stmt.where(Listing.model_type == model_type)
    if model_subtype:
        stmt = stmt.where(Listing.model_subtype == model_subtype)
    if source:
        stmt = stmt.where(Listing.source == source)
    if shipping_available is not None:
        stmt = stmt.where(Listing.shipping_available == shipping_available)
    if price_indicator:
        stmt = stmt.where(Listing.price_indicator == price_indicator)

    if sort == "date" and max_distance is None:
        # SQL-side sort and count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await session.execute(count_stmt)
        total: int = count_result.scalar_one()

        date_order = Listing.posted_at.asc().nulls_last() if asc else Listing.posted_at.desc().nulls_last()
        rows_result = await session.execute(
            stmt.order_by(date_order).limit(per_page).offset(offset)
        )
        rows = list(rows_result.scalars().all())

        # Compute distances for current page when PLZ is provided
        if plz is not None:
            # Validate PLZ exists before computing distances
            geo_check = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
            if geo_check.scalar_one_or_none() is None:
                raise HTTPException(status_code=400, detail=f"PLZ '{plz}' not found in geodata")
            page_pairs = await filter_by_distance(rows, plz, None, session)
            items = []
            for row, dist in page_pairs:
                summary = ListingSummary.model_validate(row)
                if row.id in fav_ids:
                    summary = summary.model_copy(update={"is_favorite": True})
                if dist is not None:
                    summary = summary.model_copy(update={"distance_km": dist})
                items.append(summary)
        else:
            items = []
            for row in rows:
                summary = ListingSummary.model_validate(row)
                if row.id in fav_ids:
                    summary = summary.model_copy(update={"is_favorite": True})
                items.append(summary)

        return PaginatedResponse(total=total, page=page, per_page=per_page, items=items)

    # For price/distance sort or max_distance filter: fetch all matching rows, sort/filter in Python
    all_rows_result = await session.execute(stmt)
    all_rows = list(all_rows_result.scalars().all())

    # Validate PLZ and build (row, distance_km) pairs
    if plz is not None:
        geo_check = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
        if geo_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail=f"PLZ '{plz}' not found in geodata")
        pairs = await filter_by_distance(all_rows, plz, max_distance, session)
    else:
        pairs = [(row, None) for row in all_rows]

    total = len(pairs)

    # Apply Python-side sort — nulls always last regardless of direction
    if sort == "price":
        if asc:
            pairs.sort(key=lambda p: (p[0].price_numeric is None, p[0].price_numeric or 0.0))
        else:
            pairs.sort(key=lambda p: (p[0].price_numeric is None, -(p[0].price_numeric or 0.0)))
    elif sort == "distance":
        if asc:
            pairs.sort(key=lambda p: (p[1] is None, p[1] if p[1] is not None else float("inf")))
        else:
            pairs.sort(key=lambda p: (p[1] is None, -(p[1] if p[1] is not None else 0.0)))
    else:
        # sort=date but max_distance was active — fall back to date sort in Python
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        pairs.sort(
            key=lambda p: p[0].posted_at if p[0].posted_at is not None else _epoch,
            reverse=not asc,
        )

    page_pairs = pairs[offset : offset + per_page]

    items = []
    for row, dist in page_pairs:
        summary = ListingSummary.model_validate(row)
        if row.id in fav_ids:
            summary = summary.model_copy(update={"is_favorite": True})
        summary = summary.model_copy(update={"distance_km": dist})
        items.append(summary)

    return PaginatedResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/listings/by-author", response_model=list[ListingSummary])
async def get_listings_by_author(
    author: str,
    exclude_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ListingSummary]:
    """Return up to 10 listings from the same author, excluding the given listing."""
    fav_ids = await _get_favorite_listing_ids(current_user.id, session)
    q = select(Listing).where(Listing.author == author)
    if exclude_id is not None:
        q = q.where(Listing.id != exclude_id)
    q = q.order_by(Listing.posted_at.desc()).limit(10)
    result = await session.execute(q)
    rows = result.scalars().all()
    items = []
    for row in rows:
        summary = ListingSummary.model_validate(row)
        if row.id in fav_ids:
            summary = summary.model_copy(update={"is_favorite": True})
        items.append(summary)
    return items


@router.get("/listings/{listing_id}/comparables", response_model=ComparablesResponse)
async def get_comparables(
    listing_id: int,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ComparablesResponse:
    """Return the top-N most similar listings, ranked by attribute similarity."""
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    fav_ids = await _get_favorite_listing_ids(current_user.id, session)

    base_q = (
        select(Listing)
        .where(Listing.is_sold == False)  # noqa: E712
        .where(Listing.price_numeric.is_not(None))
        .where(Listing.id != listing_id)
    )
    if listing.model_type:
        base_q = base_q.where(Listing.model_type == listing.model_type)

    candidates = list((await session.execute(base_q)).scalars().all())

    scored = [(c, similarity_score(listing, c)) for c in candidates]
    # Filter > 0.0: without any attribute match, the comparison is not meaningful.
    # Negative scores (pure wingspan diff without attribute match) are discarded —
    # with few candidates this results in 'insufficient', which is more honest than bad comparisons.
    scored = [(c, s) for c, s in scored if s > 0.0]
    # Deterministic tie-break: score desc, price asc, id asc (stable for snapshot tests).
    scored.sort(key=lambda t: (-t[1], float(t[0].price_numeric or 0), t[0].id))
    top = scored[:limit]

    quality, median_val = assess_homogeneity(listing, top)

    return ComparablesResponse(
        match_quality=quality,
        median=median_val,
        count=len(top),
        listings=[_to_comparable(c, s, fav_ids) for c, s in top],
    )


def _to_comparable(row: Listing, score_val: float, fav_ids: set[int]) -> ComparableListing:
    # Construct via explicit kwargs — model_validate() would fail on similarity_score
    # which is not an ORM attribute.
    return ComparableListing(
        id=row.id,
        title=row.title,
        url=row.url,
        price=row.price,
        price_numeric=float(row.price_numeric) if row.price_numeric is not None else None,
        condition=row.condition,
        city=row.city,
        posted_at=row.posted_at,
        is_favorite=row.id in fav_ids,
        similarity_score=round(score_val, 2),
    )


@router.get("/listings/{listing_id}", response_model=ListingDetail)
async def get_listing(
    listing_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ListingDetail:
    """Return a single listing by ID. Returns 404 if not found."""
    fav_ids = await _get_favorite_listing_ids(current_user.id, session)
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    detail = ListingDetail.model_validate(listing)
    if listing.id in fav_ids:
        detail = detail.model_copy(update={"is_favorite": True})
    return detail


@router.patch("/listings/{listing_id}/sold")
async def toggle_sold(
    listing_id: int,
    is_sold: bool,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> dict:
    """Set or clear the is_sold flag on a listing."""
    result = await session.execute(
        update(Listing).where(Listing.id == listing_id).values(is_sold=is_sold).returning(Listing.id)
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    await session.commit()
    return {"id": listing_id, "is_sold": is_sold}


@router.patch("/listings/{listing_id}/favorite")
async def toggle_favorite(
    listing_id: int,
    is_favorite: bool,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add or remove a listing from the current user's favorites."""
    exists = await session.execute(select(Listing.id).where(Listing.id == listing_id))
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    if is_favorite:
        await session.execute(
            text("""
                INSERT INTO user_favorites (user_id, listing_id)
                VALUES (:uid, :lid)
                ON CONFLICT (user_id, listing_id) DO NOTHING
            """),
            {"uid": current_user.id, "lid": listing_id},
        )
    else:
        await session.execute(
            delete(UserFavorite).where(
                UserFavorite.user_id == current_user.id,
                UserFavorite.listing_id == listing_id,
            )
        )
    await session.commit()
    return {"id": listing_id, "is_favorite": is_favorite}


@router.get("/favorites", response_model=list[ListingSummary])
async def get_favorites(
    plz: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ListingSummary]:
    """Return the current user's favorited listings, newest favorite first."""
    result = await session.execute(
        select(Listing)
        .join(UserFavorite, UserFavorite.listing_id == Listing.id)
        .where(UserFavorite.user_id == current_user.id)
        .order_by(UserFavorite.created_at.desc())
    )
    listings = result.scalars().all()

    if plz:
        pairs = await filter_by_distance(listings, plz, None, session)
        return [
            ListingSummary.model_validate(listing).model_copy(
                update={"is_favorite": True, "distance_km": dist}
            )
            for listing, dist in pairs
        ]

    return [
        ListingSummary.model_validate(l).model_copy(update={"is_favorite": True})
        for l in listings
    ]


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------

def _generate_search_name(search: str | None, plz: str | None, max_distance: int | None) -> str:
    """Auto-generate a human-readable name from search criteria."""
    if search and plz:
        return f"{search} in {plz}"
    if search:
        return search
    if plz and max_distance:
        return f"Alles in {plz} (+{max_distance}km)"
    if plz:
        return f"Alles in {plz}"
    return "Alle Anzeigen"


async def _validate_plz(plz: str, session: AsyncSession) -> None:
    """Raise HTTP 400 if the given PLZ is not found in plz_geodata."""
    result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail=f"PLZ '{plz}' not found in geodata")


async def _get_match_count(saved_search_id: int, last_viewed_at: datetime | None, session: AsyncSession) -> int:
    """Return number of notifications newer than last_viewed_at (or total if NULL)."""
    stmt = (
        select(func.count(SearchNotification.id))
        .where(SearchNotification.saved_search_id == saved_search_id)
    )
    if last_viewed_at is not None:
        stmt = stmt.where(SearchNotification.notified_at > last_viewed_at)
    result = await session.execute(stmt)
    return result.scalar_one()


@router.get("/searches", response_model=list[SavedSearchResponse])
async def list_searches(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[SavedSearchResponse]:
    """Return all saved searches for the current user with unread match counts."""
    result = await session.execute(
        select(SavedSearch)
        .where(SavedSearch.user_id == current_user.id)
        .order_by(SavedSearch.created_at.desc())
    )
    searches = result.scalars().all()

    response = []
    for s in searches:
        count = await _get_match_count(s.id, s.last_viewed_at, session)
        item = SavedSearchResponse.model_validate(s)
        item = item.model_copy(update={"match_count": count})
        response.append(item)
    return response


@router.post("/searches", response_model=SavedSearchResponse, status_code=201)
async def create_search(
    body: SavedSearchCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SavedSearchResponse:
    """Create a new saved search from filter criteria."""
    if body.plz:
        await _validate_plz(body.plz, session)

    name = _generate_search_name(body.search, body.plz, body.max_distance)
    saved = SavedSearch(
        user_id=current_user.id,
        name=name,
        search=body.search,
        plz=body.plz,
        max_distance=body.max_distance,
        sort=body.sort,
        sort_dir=body.sort_dir,
        category=body.category,
    )
    session.add(saved)
    await session.commit()
    await session.refresh(saved)
    return SavedSearchResponse.model_validate(saved)


# mark-viewed MUST be declared before {id} routes to avoid FastAPI capturing it as {id}
@router.post("/searches/mark-viewed")
async def mark_searches_viewed(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Set last_viewed_at = now() for all saved searches of the current user."""
    now = datetime.now(timezone.utc)
    await session.execute(
        update(SavedSearch)
        .where(SavedSearch.user_id == current_user.id)
        .values(last_viewed_at=now)
    )
    await session.commit()
    return {"ok": True}


@router.put("/searches/{search_id}", response_model=SavedSearchResponse)
async def update_search(
    search_id: int,
    body: SavedSearchUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SavedSearchResponse:
    """Update criteria for a saved search."""
    result = await session.execute(
        select(SavedSearch).where(
            SavedSearch.id == search_id,
            SavedSearch.user_id == current_user.id,
        )
    )
    saved = result.scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")

    if body.plz:
        await _validate_plz(body.plz, session)

    saved.search = body.search
    saved.plz = body.plz
    saved.max_distance = body.max_distance
    saved.sort = body.sort
    saved.sort_dir = body.sort_dir
    saved.category = body.category
    saved.name = _generate_search_name(body.search, body.plz, body.max_distance)
    await session.commit()
    await session.refresh(saved)

    count = await _get_match_count(saved.id, saved.last_viewed_at, session)
    item = SavedSearchResponse.model_validate(saved)
    return item.model_copy(update={"match_count": count})


@router.delete("/searches/{search_id}")
async def delete_search(
    search_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete a saved search. Returns 200 with {ok: true}."""
    result = await session.execute(
        select(SavedSearch).where(
            SavedSearch.id == search_id,
            SavedSearch.user_id == current_user.id,
        )
    )
    saved = result.scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")

    await session.delete(saved)
    await session.commit()
    return {"ok": True}


@router.patch("/searches/{search_id}")
async def toggle_search_active(
    search_id: int,
    is_active: bool = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Toggle is_active on a saved search (consistent with PATCH /listings/{id}/sold)."""
    result = await session.execute(
        update(SavedSearch)
        .where(SavedSearch.id == search_id, SavedSearch.user_id == current_user.id)
        .values(is_active=is_active)
        .returning(SavedSearch.id)
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    await session.commit()
    return {"id": search_id, "is_active": is_active}
