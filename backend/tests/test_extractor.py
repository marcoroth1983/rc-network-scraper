"""Unit tests for the OpenRouter analysis extractor.

No live API calls — the OpenRouter client is fully mocked.

Run with:
    docker compose exec backend pytest tests/test_extractor.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force module-level import so patch targets resolve correctly.
from app.analysis.extractor import ListingAnalysis, analyze_listing

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers — build mock response objects matching the openai SDK shape
# ---------------------------------------------------------------------------

def _make_parse_response(parsed_obj) -> MagicMock:
    """Return a mock response as returned by client.beta.chat.completions.parse."""
    message = MagicMock()
    message.parsed = parsed_obj
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_completion_response(content: str) -> MagicMock:
    """Return a mock response as returned by client.chat.completions.create."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client_with_parse(mock_parse: AsyncMock) -> MagicMock:
    """Build a mock AsyncOpenAI client that handles structured output."""
    mock_client = MagicMock()
    mock_client.beta = MagicMock()
    mock_client.beta.chat = MagicMock()
    mock_client.beta.chat.completions = MagicMock()
    mock_client.beta.chat.completions.parse = mock_parse
    return mock_client


def _mock_client_with_fallback(mock_parse: AsyncMock, mock_create: AsyncMock) -> MagicMock:
    """Build a mock AsyncOpenAI client with both parse (failing) and create (fallback)."""
    mock_client = _mock_client_with_parse(mock_parse)
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = mock_create
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnalyzeListing:

    async def test_empty_api_key_returns_empty_analysis(self) -> None:
        """When OPENROUTER_API_KEY is not set, return an empty ListingAnalysis immediately."""
        with patch("app.analysis.extractor.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = ""
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="Black Horse L-39",
                description="Spannweite 1700mm",
                price="1.050 €",
                condition="gebraucht",
                category="flugmodelle",
            )

        assert isinstance(result, ListingAnalysis)
        assert result.manufacturer is None
        assert result.model_name is None
        assert result.attributes == {}

    async def test_valid_structured_response_returns_correct_analysis(self) -> None:
        """Structured output path: parsed response is returned as ListingAnalysis."""
        expected = ListingAnalysis(
            manufacturer="Black Horse",
            model_name="L-39 Albatros",
            drive_type="electric",
            model_type="airplane",
            model_subtype="jet",
            completeness="ARF",
            attributes={"wingspan_mm": "1700", "weight_g": "3500"},
        )

        mock_parse = AsyncMock(return_value=_make_parse_response(expected))
        mock_client = _mock_client_with_parse(mock_parse)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="Black Horse L-39 Albatros",
                description="Spannweite 1700mm, 3500g, 12S Setup",
                price="1.050 €",
                condition="gebraucht",
                category="flugmodelle",
            )

        assert result.manufacturer == "Black Horse"
        assert result.model_name == "L-39 Albatros"
        assert result.drive_type == "electric"
        assert result.model_type == "airplane"
        assert result.model_subtype == "jet"
        assert result.completeness == "ARF"
        assert result.attributes == {"wingspan_mm": "1700", "weight_g": "3500"}

    async def test_malformed_structured_response_falls_back_to_json_parsing(self) -> None:
        """When structured output fails, fall back to parsing JSON from message content."""
        json_content = """{
            "manufacturer": "Multiplex",
            "model_name": "EasyStar 3",
            "drive_type": "electric",
            "model_type": "airplane",
            "model_subtype": "trainer",
            "completeness": "RTF",
            "attributes": {"wingspan_mm": "1000"}
        }"""

        mock_parse = AsyncMock(side_effect=Exception("Structured output not supported"))
        mock_create = AsyncMock(return_value=_make_completion_response(json_content))
        mock_client = _mock_client_with_fallback(mock_parse, mock_create)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="Multiplex EasyStar 3 RTF",
                description="Komplett, flugbereit, Spannweite 1000mm",
                price="250 €",
                condition="gebraucht",
                category="flugmodelle",
            )

        assert result.manufacturer == "Multiplex"
        assert result.model_name == "EasyStar 3"
        assert result.drive_type == "electric"
        assert result.model_type == "airplane"
        assert result.completeness == "RTF"
        assert result.attributes == {"wingspan_mm": "1000"}

    async def test_fallback_strips_markdown_code_fence(self) -> None:
        """Fallback JSON parsing must strip markdown code fences."""
        json_with_fence = "```json\n{\"manufacturer\": \"FMS\", \"model_name\": \"F-16\"}\n```"

        mock_parse = AsyncMock(side_effect=Exception("Structured output not supported"))
        mock_create = AsyncMock(return_value=_make_completion_response(json_with_fence))
        mock_client = _mock_client_with_fallback(mock_parse, mock_create)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="FMS F-16",
                description="Jet, Spannweite 900mm",
                price="350 €",
                condition="neu",
                category="flugmodelle",
            )

        assert result.manufacturer == "FMS"
        assert result.model_name == "F-16"

    async def test_refusal_response_falls_back_to_json_parsing(self) -> None:
        """When parsed is None (model refusal), fall back to JSON parsing."""
        json_content = '{"manufacturer": "Graupner", "model_name": "mz-24"}'

        mock_parse = AsyncMock(return_value=_make_parse_response(None))
        mock_create = AsyncMock(return_value=_make_completion_response(json_content))
        mock_client = _mock_client_with_fallback(mock_parse, mock_create)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="Graupner mz-24 Sender",
                description="Sender mit Empfänger",
                price="400 €",
                condition="gebraucht",
                category="rc-elektronik",
            )

        assert result.manufacturer == "Graupner"
        assert result.model_name == "mz-24"

    async def test_both_paths_fail_returns_empty_analysis(self) -> None:
        """When both structured output and JSON fallback fail, return empty ListingAnalysis."""
        mock_parse = AsyncMock(side_effect=Exception("Structured output not supported"))
        mock_create = AsyncMock(return_value=_make_completion_response("not valid json at all"))
        mock_client = _mock_client_with_fallback(mock_parse, mock_create)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            result = await analyze_listing(
                title="Irgendwas",
                description="Beschreibung",
                price=None,
                condition=None,
                category="einzelteile",
            )

        assert isinstance(result, ListingAnalysis)
        assert result.manufacturer is None
        assert result.model_name is None

    async def test_model_override_is_passed_to_client(self) -> None:
        """Caller can override the model; the overridden model must be used in the API call."""
        expected = ListingAnalysis(manufacturer="Robbe", model_name="Fokker DR.1")
        mock_parse = AsyncMock(return_value=_make_parse_response(expected))
        mock_client = _mock_client_with_parse(mock_parse)

        with patch("app.analysis.extractor.settings") as mock_settings, \
             patch("app.analysis.extractor._make_client", return_value=mock_client):

            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.OPENROUTER_MODEL = "openrouter/free"

            await analyze_listing(
                title="Robbe Fokker DR.1",
                description="Doppeldecker, Spannweite 920mm",
                price="180 €",
                condition="gebraucht",
                category="flugmodelle",
                model="google/gemini-2.5-flash-lite",
            )

        call_kwargs = mock_parse.call_args.kwargs
        assert call_kwargs.get("model") == "google/gemini-2.5-flash-lite"


# --- Vocabulary clamping ---

class TestListingAnalysisVocabularyClamping:
    def test_known_model_type_passes_through(self):
        a = ListingAnalysis(model_type="airplane", model_subtype="jet")
        assert a.model_type == "airplane"
        assert a.model_subtype == "jet"

    def test_unknown_model_type_clamped_to_none(self):
        a = ListingAnalysis(model_type="rc-elektronik", model_subtype="sender")
        assert a.model_type is None
        assert a.model_subtype is None  # subtype also cleared when type is invalid

    def test_unknown_model_subtype_clamped_to_none(self):
        a = ListingAnalysis(model_type="airplane", model_subtype="high-wing")
        assert a.model_type == "airplane"
        assert a.model_subtype is None

    def test_case_insensitive_normalization(self):
        a = ListingAnalysis(model_type="Airplane", model_subtype="JET")
        assert a.model_type == "airplane"
        assert a.model_subtype == "jet"

    def test_none_values_unchanged(self):
        a = ListingAnalysis(model_type=None, model_subtype=None)
        assert a.model_type is None
        assert a.model_subtype is None

    def test_valid_subtype_for_wrong_type_clamped(self):
        # "thermik" is valid for glider but not airplane
        a = ListingAnalysis(model_type="airplane", model_subtype="thermik")
        assert a.model_subtype is None

    def test_drive_type_unknown_clamped_to_none(self):
        a = ListingAnalysis(drive_type="brushless")
        assert a.drive_type is None

    def test_drive_type_known_passes_through(self):
        a = ListingAnalysis(drive_type="turbine")
        assert a.drive_type == "turbine"

    def test_drive_type_case_normalized(self):
        a = ListingAnalysis(drive_type="Electric")
        assert a.drive_type == "electric"
