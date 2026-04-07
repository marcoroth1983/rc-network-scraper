"""REST API endpoints."""

import logging
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ListingDetail, ListingSummary, PaginatedResponse, PlzResponse, ScrapeSummary
from app.db import get_session
from app.geo.distance import haversine_km
from app.models import Listing, PlzGeodata
from app.scraper.orchestrator import run_scrape

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/scrape", response_model=ScrapeSummary)
async def scrape(
    max_pages: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ScrapeSummary:
    """Trigger a scrape run synchronously. Blocks until complete."""
    logger.info("POST /api/scrape — max_pages=%d", max_pages)
    summary = await run_scrape(session=session, max_pages=max_pages)
    return ScrapeSummary(**summary)


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


def _price_numeric(price: str | None) -> float:
    """Extract the numeric value from a price string. Returns inf for non-numeric."""
    if not price:
        return float("inf")
    # Strip thousands separators (., space) and take integer part before decimal comma
    cleaned = price.split(",")[0].replace(".", "").replace(" ", "")
    m = re.search(r"\d+", cleaned)
    return float(m.group()) if m else float("inf")


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

    # Base statement with optional search filter
    stmt = select(Listing)
    if search:
        stmt = stmt.where(
            or_(
                Listing.title.ilike(f"%{search}%"),
                Listing.description.ilike(f"%{search}%"),
            )
        )

    if sort == "date" and max_distance is None:
        # SQL-side sort and count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await session.execute(count_stmt)
        total: int = count_result.scalar_one()

        rows_result = await session.execute(
            stmt.order_by(Listing.posted_at.desc().nulls_last()).limit(per_page).offset(offset)
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

    # Apply Python-side sort
    if sort == "price":
        pairs.sort(key=lambda p: _price_numeric(p[0].price))
    elif sort == "distance":
        pairs.sort(key=lambda p: (p[1] is None, p[1] if p[1] is not None else float("inf")))
    else:
        # sort=date but max_distance was active — fall back to date sort in Python
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        pairs.sort(
            key=lambda p: p[0].posted_at if p[0].posted_at is not None else _epoch,
            reverse=True,
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
