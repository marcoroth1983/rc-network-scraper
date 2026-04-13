"""Integration tests: verify that PLAN-014 analysis columns exist after init_db().

These tests require a running PostgreSQL database (run via Docker Compose).
Run with:
    docker compose exec backend pytest tests/test_analysis_db.py -v
"""

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


EXPECTED_ANALYSIS_COLUMNS = [
    "manufacturer",
    "model_name",
    "drive_type",
    "model_type",
    "model_subtype",
    "completeness",
    "attributes",
    "analyzed_at",
    "analysis_retries",
]


class TestAnalysisColumnsExist:
    """Verify the analysis columns were added to the listings table."""

    @pytest.mark.integration
    async def test_all_analysis_columns_present(self, test_engine) -> None:
        """After init_db() the listings table must have all PLAN-014 columns."""
        from app.db import init_db  # noqa: PLC0415

        # init_db() uses the global engine; override it with the test engine
        import app.db as db_module  # noqa: PLC0415

        original_engine = db_module.engine
        db_module.engine = test_engine
        try:
            await init_db()
        finally:
            db_module.engine = original_engine

        async with test_engine.connect() as conn:
            column_names: list[str] = await conn.run_sync(
                lambda sync_conn: [
                    col["name"]
                    for col in inspect(sync_conn).get_columns("listings")
                ]
            )

        for col in EXPECTED_ANALYSIS_COLUMNS:
            assert col in column_names, f"Missing column on listings table: {col}"

    @pytest.mark.integration
    async def test_attributes_default_is_empty_object(self, db_session: AsyncSession) -> None:
        """New rows must have attributes default to empty JSONB object {}."""
        await db_session.execute(
            text("""
                INSERT INTO listings (external_id, url, title, description, images, tags,
                    author, scraped_at)
                VALUES ('test-attr-default', 'https://example.com/1', 'Test', '',
                    '[]', '[]', 'tester', NOW())
            """)
        )
        await db_session.commit()

        row = await db_session.execute(
            text("SELECT attributes FROM listings WHERE external_id = 'test-attr-default'")
        )
        attributes = row.scalar_one()
        assert attributes == {}, f"Expected empty dict, got {attributes!r}"

    @pytest.mark.integration
    async def test_analysis_retries_default_is_zero(self, db_session: AsyncSession) -> None:
        """New rows must have analysis_retries default to 0."""
        await db_session.execute(
            text("""
                INSERT INTO listings (external_id, url, title, description, images, tags,
                    author, scraped_at)
                VALUES ('test-retries-default', 'https://example.com/2', 'Test2', '',
                    '[]', '[]', 'tester', NOW())
            """)
        )
        await db_session.commit()

        row = await db_session.execute(
            text("SELECT analysis_retries FROM listings WHERE external_id = 'test-retries-default'")
        )
        retries = row.scalar_one()
        assert retries == 0, f"Expected 0, got {retries!r}"

    @pytest.mark.integration
    async def test_analyzed_at_defaults_to_null(self, db_session: AsyncSession) -> None:
        """New rows must have analyzed_at = NULL (not yet analyzed)."""
        await db_session.execute(
            text("""
                INSERT INTO listings (external_id, url, title, description, images, tags,
                    author, scraped_at)
                VALUES ('test-analyzed-at', 'https://example.com/3', 'Test3', '',
                    '[]', '[]', 'tester', NOW())
            """)
        )
        await db_session.commit()

        row = await db_session.execute(
            text("SELECT analyzed_at FROM listings WHERE external_id = 'test-analyzed-at'")
        )
        analyzed_at = row.scalar_one_or_none()
        assert analyzed_at is None, f"Expected NULL, got {analyzed_at!r}"
