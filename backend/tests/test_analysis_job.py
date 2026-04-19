"""Unit tests for the analysis job (backend/app/analysis/job.py) and extractor cascade behaviour.

These tests mock analyze_listing and AsyncSessionLocal to avoid DB and network calls.
Run with: docker compose exec backend pytest tests/test_analysis_job.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis.extractor import ListingAnalysis, analyze_listing
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


# ---------------------------------------------------------------------------
# Tests for analyze_listing cascade fallback behaviour (extractor.py)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeListingCascade:
    """Verify the cascade → paid-fallback flow inside analyze_listing()."""

    _CALL_ARGS = dict(
        title="Multiplex Easy Glider",
        description="Sehr guter Zustand, Spannweite 1800mm",
        price="350 €",
        condition="gebraucht",
        category="flugmodelle",
        listing_id=42,
    )

    async def test_cascade_exhaustion_falls_through_to_paid_fallback(self) -> None:
        """All free models fail → paid fallback is tried and succeeds."""
        paid_result = ListingAnalysis(manufacturer="Multiplex", model_name="Easy Glider")

        with patch("app.analysis.extractor.settings") as mock_cfg:
            mock_cfg.OPENROUTER_API_KEY = "sk-test"
            mock_cfg.OPENROUTER_FALLBACK_MODEL = "mistralai/mistral-nemo"

            with patch(
                "app.analysis.extractor.model_cascade.load_cascade",
                new_callable=AsyncMock,
                return_value=["vendor/free-a:free", "vendor/free-b:free"],
            ):
                with patch(
                    "app.analysis.extractor.model_cascade.record_failure",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "app.analysis.extractor.model_cascade.record_success",
                        new_callable=AsyncMock,
                    ):
                        # _try_analyze returns (None, err) for free models, (result, None) for paid
                        async def _try_side_effect(client, model, user_message):
                            if model == "mistralai/mistral-nemo":
                                return paid_result, None
                            return None, f"RateLimitError from {model}"

                        with patch(
                            "app.analysis.extractor._try_analyze",
                            side_effect=_try_side_effect,
                        ):
                            result = await analyze_listing(**self._CALL_ARGS)

        assert result.manufacturer == "Multiplex"
        assert result.model_name == "Easy Glider"

    async def test_empty_cascade_goes_straight_to_paid_fallback(self) -> None:
        """Empty cascade → no free model attempts → paid fallback used directly."""
        paid_result = ListingAnalysis(model_type="glider")

        with patch("app.analysis.extractor.settings") as mock_cfg:
            mock_cfg.OPENROUTER_API_KEY = "sk-test"
            mock_cfg.OPENROUTER_FALLBACK_MODEL = "mistralai/mistral-nemo"

            with patch(
                "app.analysis.extractor.model_cascade.load_cascade",
                new_callable=AsyncMock,
                return_value=[],  # empty cascade
            ):
                with patch(
                    "app.analysis.extractor._try_analyze",
                    new_callable=AsyncMock,
                    return_value=(paid_result, None),
                ) as mock_try:
                    result = await analyze_listing(**self._CALL_ARGS)

        assert result.model_type == "glider"
        # _try_analyze must have been called exactly once — for the paid fallback
        mock_try.assert_called_once()
        _, called_model, _ = mock_try.call_args[0]
        assert called_model == "mistralai/mistral-nemo"



