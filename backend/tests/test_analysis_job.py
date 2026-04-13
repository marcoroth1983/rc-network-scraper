"""Unit tests for the analysis job (backend/app/analysis/job.py).

These tests mock analyze_listing and AsyncSessionLocal to avoid DB and network calls.
Run with: docker compose exec backend pytest tests/test_analysis_job.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis.extractor import ListingAnalysis
from app.analysis.job import BATCH_SIZE, run_analysis_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_listing_orm(listing_id: int = 1) -> MagicMock:
    """Return a mock ORM Listing object."""
    listing = MagicMock()
    listing.id = listing_id
    listing.title = "Black Horse L-39 Albatros"
    listing.description = "Verkaufe meinen Jet, Spannweite 1700mm"
    listing.price = "1.050 €"
    listing.condition = "gebraucht"
    listing.category = "flugmodelle"
    listing.scraped_at = MagicMock()
    return listing


def _non_empty_analysis(**kwargs) -> ListingAnalysis:
    defaults = {"manufacturer": "Black Horse", "model_name": "L-39 Albatros", "model_type": "airplane"}
    defaults.update(kwargs)
    return ListingAnalysis(**defaults)


def _make_session_ctx(listings: list) -> tuple[MagicMock, MagicMock]:
    """Return (fetch_ctx, update_ctx) mocks for the two AsyncSessionLocal() calls."""
    fetch_session = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = listings
    fetch_session.execute.return_value = scalars_result

    fetch_ctx = MagicMock()
    fetch_ctx.__aenter__ = AsyncMock(return_value=fetch_session)
    fetch_ctx.__aexit__ = AsyncMock(return_value=False)

    update_session = AsyncMock()
    update_session.execute.return_value = MagicMock()

    update_ctx = MagicMock()
    update_ctx.__aenter__ = AsyncMock(return_value=update_session)
    update_ctx.__aexit__ = AsyncMock(return_value=False)

    return fetch_ctx, update_ctx


# ---------------------------------------------------------------------------
# Tests for run_analysis_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunAnalysisJob:
    async def test_skips_when_api_key_not_set(self) -> None:
        """Job exits early without DB access if OPENROUTER_API_KEY is empty."""
        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = ""
            with patch("app.analysis.job.AsyncSessionLocal") as mock_factory:
                await run_analysis_job()
            mock_factory.assert_not_called()

    async def test_no_op_when_no_unanalyzed_listings(self) -> None:
        """Job logs and returns cleanly when nothing needs analyzing."""
        fetch_ctx, _ = _make_session_ctx([])

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            with patch("app.analysis.job.AsyncSessionLocal", return_value=fetch_ctx):
                with patch("app.analysis.job.analyze_listing") as mock_analyze:
                    await run_analysis_job()
                mock_analyze.assert_not_called()

    async def test_analyzed_listing_gets_updated(self) -> None:
        """Successful analysis saves extracted fields and sets llm_analyzed=True."""
        listing = _make_listing_orm(listing_id=42)
        analysis = _non_empty_analysis()

        fetch_ctx, update_ctx = _make_session_ctx([listing])
        call_count = 0

        def _make_ctx():
            nonlocal call_count
            call_count += 1
            return fetch_ctx if call_count == 1 else update_ctx

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            with patch("app.analysis.job.AsyncSessionLocal", side_effect=_make_ctx):
                with patch("app.analysis.job.analyze_listing", new_callable=AsyncMock, return_value=analysis):
                    with patch("app.analysis.job.asyncio.sleep", new_callable=AsyncMock):
                        with patch("app.analysis.job.recalculate_price_indicators", new_callable=AsyncMock):
                            await run_analysis_job()

        update_session = await update_ctx.__aenter__()
        assert update_session.execute.called
        assert update_session.commit.called

    async def test_analyze_listing_exception_propagates(self) -> None:
        """When analyze_listing raises, run_analysis_job propagates the exception.

        The new job has no try/except per design — failures surface so the scheduler
        can log them. Use backfill.py for retry-tolerant processing.
        """
        listing = _make_listing_orm(listing_id=5)
        fetch_ctx, _ = _make_session_ctx([listing])

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            with patch("app.analysis.job.AsyncSessionLocal", return_value=fetch_ctx):
                with patch(
                    "app.analysis.job.analyze_listing",
                    new_callable=AsyncMock,
                    side_effect=Exception("LLM timeout"),
                ):
                    with patch("app.analysis.job.asyncio.sleep", new_callable=AsyncMock):
                        with pytest.raises(Exception, match="LLM timeout"):
                            await run_analysis_job()

    async def test_batch_size_constant_is_correct(self) -> None:
        """BATCH_SIZE is 3 — respects ~20 req/min free tier limit."""
        assert BATCH_SIZE == 3
