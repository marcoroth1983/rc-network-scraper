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
    "llm_analyzed",
    "shipping_available",
]

REMOVED_COLUMNS = [
    "analyzed_at",
    "analysis_retries",
]


class TestAnalysisColumnsExist:
    """Verify the analysis columns were added/removed from the listings table."""

    @pytest.mark.integration
    async def test_all_analysis_columns_present(self, test_engine) -> None:
        """After init_db() the listings table must have all PLAN-014 columns."""
        from app.db import init_db  # noqa: PLC0415

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

        for col in REMOVED_COLUMNS:
            assert col not in column_names, f"Column should have been dropped: {col}"

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
    async def test_llm_analyzed_default_is_false(self, db_session: AsyncSession) -> None:
        """New rows must have llm_analyzed default to false."""
        await db_session.execute(
            text("""
                INSERT INTO listings (external_id, url, title, description, images, tags,
                    author, scraped_at)
                VALUES ('test-llm-default', 'https://example.com/2', 'Test2', '',
                    '[]', '[]', 'tester', NOW())
            """)
        )
        await db_session.commit()

        row = await db_session.execute(
            text("SELECT llm_analyzed FROM listings WHERE external_id = 'test-llm-default'")
        )
        llm_analyzed = row.scalar_one()
        assert llm_analyzed is False, f"Expected False, got {llm_analyzed!r}"

    @pytest.mark.integration
    async def test_shipping_available_defaults_to_null(self, db_session: AsyncSession) -> None:
        """New rows must have shipping_available = NULL (not yet analyzed)."""
        await db_session.execute(
            text("""
                INSERT INTO listings (external_id, url, title, description, images, tags,
                    author, scraped_at)
                VALUES ('test-shipping-default', 'https://example.com/4', 'Test4', '',
                    '[]', '[]', 'tester', NOW())
            """)
        )
        await db_session.commit()

        row = await db_session.execute(
            text("SELECT shipping_available FROM listings WHERE external_id = 'test-shipping-default'")
        )
        shipping_available = row.scalar_one_or_none()
        assert shipping_available is None, f"Expected NULL, got {shipping_available!r}"
