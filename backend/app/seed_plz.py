"""One-time PLZ CSV to database import script.

Usage (from inside Docker):
    python -m app.seed_plz

Source file: backend/data/plz_de.csv
Format: GeoNames DE.txt — tab-separated, no header.
Relevant columns:
    index 1: postal_code  → plz
    index 2: place_name   → city
    index 9: latitude     → lat
    index 10: longitude   → lon
"""

import asyncio
import csv
import logging
from pathlib import Path

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

# Path is relative to this file's location (backend/app/), so ../data/plz_de.csv
_CSV_PATH = Path(__file__).parent.parent / "data" / "plz_de.csv"

# asyncpg does not accept postgresql+asyncpg:// — strip the SQLAlchemy dialect prefix
_ASYNCPG_DSN = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _parse_rows(csv_path: Path) -> list[tuple[str, str, float, float]]:
    """Read and parse the GeoNames TSV file into (plz, city, lat, lon) tuples.

    Skips rows where required columns are missing or non-numeric.
    """
    rows: list[tuple[str, str, float, float]] = []
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for line_num, row in enumerate(reader, start=1):
            if len(row) < 11:
                logger.warning("Line %d: too few columns (%d), skipping", line_num, len(row))
                continue
            plz = row[1].strip()
            city = row[2].strip()
            lat_raw = row[9].strip()
            lon_raw = row[10].strip()
            if not plz or not city:
                logger.warning("Line %d: empty plz or city, skipping", line_num)
                continue
            try:
                lat = float(lat_raw)
                lon = float(lon_raw)
            except ValueError:
                logger.warning("Line %d: non-numeric lat/lon ('%s', '%s'), skipping", line_num, lat_raw, lon_raw)
                continue
            rows.append((plz, city, lat, lon))
    return rows


async def seed(csv_path: Path = _CSV_PATH) -> None:
    """Read CSV and bulk-insert into plz_geodata. Idempotent via ON CONFLICT DO NOTHING."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"PLZ data file not found: {csv_path}\n"
            "Download it with:\n"
            "  curl -L https://download.geonames.org/export/zip/DE.zip -o /tmp/DE.zip\n"
            "  unzip /tmp/DE.zip DE.txt -d /tmp/\n"
            "  cp /tmp/DE.txt backend/data/plz_de.csv"
        )

    logger.info("Parsing %s ...", csv_path)
    rows = _parse_rows(csv_path)
    logger.info("Parsed %d rows", len(rows))

    conn: asyncpg.Connection = await asyncpg.connect(_ASYNCPG_DSN)
    try:
        result = await conn.executemany(
            """
            INSERT INTO plz_geodata (plz, city, lat, lon)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (plz) DO NOTHING
            """,
            rows,
        )
        logger.info("Bulk insert complete: %s", result)
    finally:
        await conn.close()

    logger.info("PLZ seed done — %d rows processed", len(rows))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed())
