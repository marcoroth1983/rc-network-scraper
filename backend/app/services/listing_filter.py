"""Shared listing filter utilities used by the API route and the search matcher."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.geo.distance import haversine_km
from app.models import Listing, PlzGeodata


def build_text_filter(search: str | None) -> list[ColumnElement]:
    """Return SQLAlchemy filter clauses for text search (title/description/tags).

    Returns empty list if search is None.
    """
    if not search:
        return []
    return [
        or_(
            Listing.title.ilike(f"%{search}%"),
            Listing.model_type.ilike(f"%{search}%"),
            Listing.model_subtype.ilike(f"%{search}%"),
            Listing.model_name.ilike(f"%{search}%"),
            Listing.manufacturer.ilike(f"%{search}%"),
        )
    ]


async def filter_by_distance(
    listings: list[Listing],
    plz: str,
    max_distance: int | None,
    session: AsyncSession,
) -> list[tuple[Listing, float | None]]:
    """Compute Haversine distances from PLZ for each listing.

    Looks up PLZ coords from plz_geodata table.
    Returns (listing, distance_km) pairs.

    When max_distance is set: only returns listings within range.
    Listings without coordinates are excluded when max_distance is set.
    When max_distance is None: returns ALL listings with computed distances.
    Listings without coordinates get distance=None (not inf — inf is not valid JSON).
    """
    geo_result = await session.execute(select(PlzGeodata).where(PlzGeodata.plz == plz))
    geo_row = geo_result.scalar_one_or_none()
    if geo_row is None:
        # PLZ not found — return all listings with distance=None
        return [(listing, None) for listing in listings]

    ref_lat = geo_row.lat
    ref_lon = geo_row.lon

    pairs: list[tuple[Listing, float | None]] = []
    for listing in listings:
        if listing.latitude is not None and listing.longitude is not None:
            dist: float | None = haversine_km(ref_lat, ref_lon, listing.latitude, listing.longitude)
        else:
            dist = None
        pairs.append((listing, dist))

    if max_distance is not None:
        # Filter: only include listings within range (those without coords are excluded)
        pairs = [
            (listing, dist)
            for listing, dist in pairs
            if dist is not None and dist <= max_distance
        ]

    return pairs
