"""Tests for orchestrator._geo_lookup fallback chain — Nominatim numeric guard."""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scraper.orchestrator import _geo_lookup


async def _reset_intl(session: AsyncSession) -> None:
    """intl_geodata is not cleaned by the autouse clean_listings fixture."""
    await session.execute(text("DELETE FROM intl_geodata"))
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bare_numeric_city_does_not_call_nominatim(db_session: AsyncSession):
    """A pure-digit 'city' (e.g. '2450') must NOT be sent to Nominatim and resolves to NULL."""
    await _reset_intl(db_session)
    mock_geocode = AsyncMock(return_value=(-30.3, 153.1))  # would be Australia if called
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="2450")
    mock_geocode.assert_not_awaited()
    assert lat is None
    assert lon is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_named_city_still_uses_nominatim_fallback(db_session: AsyncSession):
    """A real place name with no local match still reaches the Nominatim fallback."""
    await _reset_intl(db_session)
    mock_geocode = AsyncMock(return_value=(47.0, 15.4))
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode), \
         patch("app.scraper.orchestrator.asyncio.sleep", new=AsyncMock()):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="IrgendwoinÖsterreich")
    mock_geocode.assert_awaited_once()
    assert (lat, lon) == (47.0, 15.4)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_austrian_plz_resolves_from_intl_geodata(db_session: AsyncSession):
    """When intl_geodata holds AT 2450, the bare-PLZ city resolves locally without Nominatim."""
    await _reset_intl(db_session)
    await db_session.execute(text(
        "INSERT INTO intl_geodata (country, plz, city, lat, lon) "
        "VALUES ('AT', '2450', 'Mannersdorf', 48.0, 16.6)"
    ))
    await db_session.commit()
    mock_geocode = AsyncMock(return_value=(-30.3, 153.1))
    with patch("app.scraper.orchestrator._nominatim_geocode", new=mock_geocode):
        lat, lon, plz = await _geo_lookup(db_session, plz=None, city="2450")
    mock_geocode.assert_not_awaited()
    assert (lat, lon) == (48.0, 16.6)
    assert plz == "2450"
