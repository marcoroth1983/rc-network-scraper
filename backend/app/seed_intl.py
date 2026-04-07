"""Seed AT and CH postal code geodata from GeoNames into intl_geodata table.

Usage (from inside Docker):
    python -m app.seed_intl
    python -m app.seed_intl --backfill   # also backfill NULL-geo listings
"""

import argparse
import asyncio
import csv
import io
import logging
import zipfile

import asyncpg
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_COUNTRIES = ["AT", "CH"]
_GEONAMES_URL = "https://download.geonames.org/export/zip/{country}.zip"
_ASYNCPG_DSN = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def _download_and_parse(country: str) -> list[tuple[str, str, str, float, float]]:
    url = _GEONAMES_URL.format(country=country)
    logger.info("Downloading %s ...", url)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    rows: list[tuple[str, str, str, float, float]] = []
    seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open(f"{country}.txt") as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t")
            for row in reader:
                if len(row) < 11:
                    continue
                plz = row[1].strip()
                city = row[2].strip()
                if not plz or not city or plz in seen:
                    continue
                try:
                    lat = float(row[9].strip())
                    lon = float(row[10].strip())
                except ValueError:
                    continue
                seen.add(plz)
                rows.append((country, plz, city, lat, lon))
    logger.info("Parsed %d unique PLZ entries for %s", len(rows), country)
    return rows


async def seed() -> None:
    conn: asyncpg.Connection = await asyncpg.connect(_ASYNCPG_DSN)
    try:
        for country in _COUNTRIES:
            rows = await _download_and_parse(country)
            result = await conn.executemany(
                """
                INSERT INTO intl_geodata (country, plz, city, lat, lon)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (country, plz) DO NOTHING
                """,
                rows,
            )
            logger.info("Seeded %s: %s", country, result)
    finally:
        await conn.close()


async def backfill_geo() -> None:
    """Re-run geo lookup for all listings with NULL coordinates."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.scraper.orchestrator import _geo_lookup
    from app.config import settings as app_settings

    engine = create_async_engine(app_settings.DATABASE_URL, echo=False)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    conn: asyncpg.Connection = await asyncpg.connect(_ASYNCPG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT id, plz, city FROM listings WHERE latitude IS NULL ORDER BY id"
        )
        logger.info("Backfill: %d listings with NULL coordinates", len(rows))
        resolved = 0
        async with Session() as session:
            for i, row in enumerate(rows):
                lat, lon, resolved_plz = await _geo_lookup(session, row["plz"], row["city"])
                if lat is not None:
                    await conn.execute(
                        "UPDATE listings SET latitude=$1, longitude=$2, plz=COALESCE($3, plz) WHERE id=$4",
                        lat, lon, resolved_plz, row["id"],
                    )
                    resolved += 1
                    logger.info(
                        "  [%d/%d] id=%d resolved → %.4f, %.4f (plz=%s city=%s)",
                        i + 1, len(rows), row["id"], lat, lon, row["plz"], row["city"],
                    )
                else:
                    logger.info(
                        "  [%d/%d] id=%d unresolved (plz=%s city=%s)",
                        i + 1, len(rows), row["id"], row["plz"], row["city"],
                    )
        logger.info("Backfill complete: %d/%d resolved", resolved, len(rows))
    finally:
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="Backfill NULL-geo listings after seeding")
    args = parser.parse_args()

    async def main() -> None:
        await seed()
        if args.backfill:
            await backfill_geo()

    asyncio.run(main())
