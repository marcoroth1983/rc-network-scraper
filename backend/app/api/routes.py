"""REST API endpoints."""

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ListingDetail, ListingSummary, PaginatedResponse, PlzResponse, ScrapeSummary, ScrapeStatus
from app.db import get_session
from app.geo.distance import haversine_km
from app.models import Listing, PlzGeodata
from app.scrape_runner import get_state, start_background_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/scrape", status_code=202)
async def start_scrape() -> dict:
    """Trigger a background scrape job. Returns 409 if already running."""
    logger.info("POST /api/scrape — triggering background job")
    started = start_background_job()
    if not started:
        raise HTTPException(status_code=409, detail="Scrape already running")
    return {"status": "started"}


@router.get("/scrape/status", response_model=ScrapeStatus)
async def scrape_status() -> ScrapeStatus:
    """Return current scrape job status for frontend polling."""
    state = get_state()
    summary_data = state.get("summary")
    summary = ScrapeSummary(**summary_data) if summary_data else None
    return ScrapeStatus(
        status=state["status"],
        started_at=state["started_at"],
        finished_at=state["finished_at"],
        phase=state["phase"],
        progress=state["progress"],
        summary=summary,
        error=state["error"],
    )


@router.get("/geo/plz/{plz}", response_model=PlzResponse)
async def resolve_plz(
    plz: str,
    session: AsyncSession = Depends(get_session),
) -> PlzResponse:
    """Resolve a German PLZ to coordinates. Returns 404 if PLZ not found."""
    result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PLZ not found")
    return PlzResponse.model_validate(row)


def _dist_key(listing: Listing, ref_lat: float, ref_lon: float) -> float:
    """Return Haversine distance from listing to reference point, or inf if no coords."""
    if listing.latitude is None or listing.longitude is None:
        return float("inf")
    return haversine_km(ref_lat, ref_lon, listing.latitude, listing.longitude)


@router.get("/listings", response_model=PaginatedResponse)
async def list_listings(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    sort: Literal["date", "price", "distance"] = Query(default="date"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    plz: str | None = Query(default=None),
    max_distance: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse:
    """Return a paginated, filterable, sortable list of listings."""
    # Validate parameter combinations
    if sort == "distance" and plz is None:
        raise HTTPException(status_code=400, detail="plz is required when sort=distance")
    if max_distance is not None and plz is None:
        raise HTTPException(status_code=400, detail="plz is required when max_distance is set")

    offset = (page - 1) * per_page
    asc = sort_dir == "asc"

    # Base statement with optional search filter
    stmt = select(Listing)
    if search:
        stmt = stmt.where(
            or_(
                Listing.title.ilike(f"%{search}%"),
                Listing.description.ilike(f"%{search}%"),
                cast(Listing.tags, String).ilike(f"%{search}%"),
            )
        )

    if sort == "date" and max_distance is None:
        # SQL-side sort and count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await session.execute(count_stmt)
        total: int = count_result.scalar_one()

        date_order = Listing.posted_at.asc().nulls_last() if asc else Listing.posted_at.desc().nulls_last()
        rows_result = await session.execute(
            stmt.order_by(date_order).limit(per_page).offset(offset)
        )
        rows = rows_result.scalars().all()

        # Compute distances for current page when PLZ is provided
        if plz is not None:
            geo_result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
            geo_row = geo_result.scalar_one_or_none()
            if geo_row is None:
                raise HTTPException(status_code=400, detail=f"PLZ '{plz}' not found in geodata")
            items = []
            for row in rows:
                summary = ListingSummary.model_validate(row)
                if row.latitude is not None and row.longitude is not None:
                    dist = haversine_km(geo_row.lat, geo_row.lon, row.latitude, row.longitude)
                    summary = summary.model_copy(update={"distance_km": dist})
                items.append(summary)
        else:
            items = [ListingSummary.model_validate(row) for row in rows]

        return PaginatedResponse(total=total, page=page, per_page=per_page, items=items)

    # For price/distance sort or max_distance filter: fetch all matching rows, sort/filter in Python
    all_rows_result = await session.execute(stmt)
    all_rows = list(all_rows_result.scalars().all())

    # Resolve reference coordinates when plz is provided
    ref_lat: float | None = None
    ref_lon: float | None = None
    if plz is not None:
        geo_result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
        geo_row = geo_result.scalar_one_or_none()
        if geo_row is None:
            raise HTTPException(status_code=400, detail=f"PLZ '{plz}' not found in geodata")
        ref_lat = geo_row.lat
        ref_lon = geo_row.lon

    # Build (row, distance_km) pairs
    pairs: list[tuple[Listing, float | None]] = []
    for row in all_rows:
        if ref_lat is not None and ref_lon is not None:
            dist: float | None = _dist_key(row, ref_lat, ref_lon)
            if dist == float("inf"):
                dist = None  # no coordinates on listing
        else:
            dist = None
        pairs.append((row, dist))

    # Apply max_distance filter (Python-side)
    if max_distance is not None and ref_lat is not None and ref_lon is not None:
        filtered: list[tuple[Listing, float | None]] = []
        for row, dist in pairs:
            if row.latitude is not None and row.longitude is not None:
                actual_dist = haversine_km(ref_lat, ref_lon, row.latitude, row.longitude)
                if actual_dist <= max_distance:
                    filtered.append((row, actual_dist))
            # listings without coordinates are excluded when max_distance is active
        pairs = filtered

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
        summary = summary.model_copy(update={"distance_km": dist})
        items.append(summary)

    return PaginatedResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/listings/{listing_id}", response_model=ListingDetail)
async def get_listing(
    listing_id: int,
    session: AsyncSession = Depends(get_session),
) -> ListingDetail:
    """Return a single listing by ID. Returns 404 if not found."""
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    return ListingDetail.model_validate(listing)


@router.patch("/listings/{listing_id}/sold")
async def toggle_sold(
    listing_id: int,
    is_sold: bool,
    session: AsyncSession = Depends(get_session),
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
) -> dict:
    """Set or clear the is_favorite flag on a listing."""
    result = await session.execute(
        update(Listing)
        .where(Listing.id == listing_id)
        .values(is_favorite=is_favorite)
        .returning(Listing.id)
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    await session.commit()
    return {"id": listing_id, "is_favorite": is_favorite}


@router.get("/favorites", response_model=list[ListingSummary])
async def get_favorites(
    session: AsyncSession = Depends(get_session),
) -> list[ListingSummary]:
    """Return all favorited listings ordered by posted_at desc."""
    result = await session.execute(
        select(Listing)
        .where(Listing.is_favorite.is_(True))
        .order_by(Listing.posted_at.desc().nulls_last())
    )
    rows = result.scalars().all()
    return [ListingSummary.model_validate(row) for row in rows]
