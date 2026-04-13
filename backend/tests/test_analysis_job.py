"""Unit tests for the analysis job (backend/app/analysis/job.py).

These tests mock analyze_listing and AsyncSessionLocal to avoid DB and network calls.
Run with: docker compose exec backend pytest tests/test_analysis_job.py -v
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.analysis.extractor import ListingAnalysis
from app.analysis.job import (
    _MAX_RETRIES,
    _fetch_unanalyzed,
    _increment_retries,
    _update_listing_analysis,
    run_analysis_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_listing(
    listing_id: int = 1,
    analysis_retries: int = 0,
) -> dict:
    return {
        "id": listing_id,
        "title": "Black Horse L-39 Albatros",
        "description": "Verkaufe meinen Jet, Spannweite 1700mm",
        "price": "1.050 €",
        "condition": "gebraucht",
        "category": "flugmodelle",
        "analysis_retries": analysis_retries,
    }


def _non_empty_analysis(**kwargs) -> ListingAnalysis:
    defaults = {"manufacturer": "Black Horse", "model_name": "L-39 Albatros", "model_type": "airplane"}
    defaults.update(kwargs)
    return ListingAnalysis(**defaults)


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
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"
            mock_settings.OPENROUTER_BATCH_MODEL = "google/gemini-2.5-flash-lite"
            with patch("app.analysis.job.AsyncSessionLocal", return_value=mock_ctx):
                with patch("app.analysis.job.analyze_listing") as mock_analyze:
                    await run_analysis_job()
                mock_analyze.assert_not_called()

    async def test_analyzed_listing_gets_updated(self) -> None:
        """Successful analysis saves extracted fields and sets analyzed_at."""
        listing = _make_listing(listing_id=42)
        analysis = _non_empty_analysis()

        # Session 1: fetch_unanalyzed returns the listing
        fetch_session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.all.return_value = [listing]
        fetch_session.execute.return_value = fetch_result

        # Session 2: update listing
        update_session = AsyncMock()
        update_result = MagicMock()
        update_session.execute.return_value = update_result

        call_count = 0

        def _make_ctx():
            nonlocal call_count
            call_count += 1
            session = fetch_session if call_count == 1 else update_session
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"
            mock_settings.OPENROUTER_BATCH_MODEL = "google/gemini-2.5-flash-lite"
            with patch("app.analysis.job.AsyncSessionLocal", side_effect=_make_ctx):
                with patch("app.analysis.job.analyze_listing", new_callable=AsyncMock, return_value=analysis):
                    with patch("app.analysis.job.asyncio.sleep", new_callable=AsyncMock):
                        await run_analysis_job()

        # The update session must have been called with an UPDATE statement
        assert update_session.execute.called
        assert update_session.commit.called

    async def test_free_model_fails_paid_fallback_succeeds(self) -> None:
        """When free model returns empty analysis, paid fallback is tried."""
        listing = _make_listing(listing_id=7)
        empty_analysis = ListingAnalysis()  # all None — treated as failure
        good_analysis = _non_empty_analysis()

        fetch_session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.all.return_value = [listing]
        fetch_session.execute.return_value = fetch_result

        update_session = AsyncMock()
        update_session.execute.return_value = MagicMock()

        call_count = 0

        def _make_ctx():
            nonlocal call_count
            call_count += 1
            session = fetch_session if call_count == 1 else update_session
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        analyze_calls = []

        async def _mock_analyze(**kwargs):
            analyze_calls.append(kwargs.get("model"))
            if kwargs.get("model") == "openrouter/free":
                return empty_analysis
            return good_analysis

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"
            mock_settings.OPENROUTER_BATCH_MODEL = "google/gemini-2.5-flash-lite"
            with patch("app.analysis.job.AsyncSessionLocal", side_effect=_make_ctx):
                with patch("app.analysis.job.analyze_listing", side_effect=_mock_analyze):
                    with patch("app.analysis.job.asyncio.sleep", new_callable=AsyncMock):
                        await run_analysis_job()

        assert "openrouter/free" in analyze_calls
        assert "google/gemini-2.5-flash-lite" in analyze_calls
        # update commit should have been called (paid fallback succeeded)
        assert update_session.commit.called

    async def test_both_models_fail_increments_retries(self) -> None:
        """When both free and paid models return empty analysis, retries counter is incremented."""
        listing = _make_listing(listing_id=5)
        empty_analysis = ListingAnalysis()  # all None

        fetch_session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.all.return_value = [listing]
        fetch_session.execute.return_value = fetch_result

        retry_session = AsyncMock()
        retry_session.execute.return_value = MagicMock()

        call_count = 0

        def _make_ctx():
            nonlocal call_count
            call_count += 1
            session = fetch_session if call_count == 1 else retry_session
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"
            mock_settings.OPENROUTER_BATCH_MODEL = "google/gemini-2.5-flash-lite"
            with patch("app.analysis.job.AsyncSessionLocal", side_effect=_make_ctx):
                with patch(
                    "app.analysis.job.analyze_listing",
                    new_callable=AsyncMock,
                    return_value=empty_analysis,
                ):
                    with patch("app.analysis.job.asyncio.sleep", new_callable=AsyncMock):
                        await run_analysis_job()

        # retry session execute must have been called for the increment
        assert retry_session.execute.called
        assert retry_session.commit.called

    async def test_listing_with_max_retries_excluded_from_fetch(self) -> None:
        """The fetch query filters out listings where analysis_retries >= _MAX_RETRIES.

        We verify this by checking the SQL query contains the analysis_retries < :max_retries
        condition. The actual filtering is done by the database.
        """
        fetch_session = AsyncMock()
        fetch_result = MagicMock()
        # Simulate DB returning no rows (all filtered out by SQL)
        fetch_result.mappings.return_value.all.return_value = []
        fetch_session.execute.return_value = fetch_result

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=fetch_session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.analysis.job.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "sk-test"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"
            mock_settings.OPENROUTER_BATCH_MODEL = "google/gemini-2.5-flash-lite"
            with patch("app.analysis.job.AsyncSessionLocal", return_value=ctx):
                await run_analysis_job()

        # Check that the query included the analysis_retries bound
        call_args = fetch_session.execute.call_args
        assert call_args is not None
        bound_params = call_args[0][1]  # positional arg: dict of params
        assert "max_retries" in bound_params
        assert bound_params["max_retries"] == _MAX_RETRIES
