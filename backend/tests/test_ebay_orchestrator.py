"""Unit tests for ebay_orchestrator — _normalize_item() and _all_known()."""

import json
from datetime import timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.scraper.ebay_orchestrator import _all_known, _normalize_item

FIXTURES = Path(__file__).parent / "fixtures"


def _load_item() -> dict:
    """Load the single item_summary dict from the fixture file."""
    data = json.loads((FIXTURES / "ebay_item_summary.json").read_text(encoding="utf-8"))
    return data["itemSummaries"][0]


# ---------------------------------------------------------------------------
# _normalize_item
# ---------------------------------------------------------------------------


class TestNormalizeItem:
    def test_normalize_item_all_fields(self) -> None:
        """All expected fields are present and non-empty in the normalised dict."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=48.137, lon=11.576)

        assert result["external_id"] == "ebay_v1|123456789|0"
        assert result["url"] == "https://www.ebay.de/itm/123456789"
        assert result["title"] == "Robbe Funtana 125 RC Flugzeug gebraucht"
        assert result["price"] == "149.00 EUR"
        assert result["price_numeric"] == 149.0
        assert result["condition"] == "gebraucht"
        assert result["author"] == "rc_max_1983"
        assert result["plz"] == "80331"
        assert result["city"] == "München"
        assert result["latitude"] == 48.137
        assert result["longitude"] == 11.576
        assert result["description"] == "Robbe Funtana 125 Verbrenner, gebraucht, flugbereit"
        assert result["category"] == "flugmodelle"
        assert result["source"] == "ebay"
        assert result["shipping"] == "Versand 6.99 EUR"
        assert result["posted_at"] is not None
        assert result["posted_at_raw"] == "2025-04-10T10:30:00.000Z"

    def test_normalize_item_external_id_prefix(self) -> None:
        """external_id is prefixed with 'ebay_' followed by the raw itemId."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        assert result["external_id"] == "ebay_v1|123456789|0"

    def test_normalize_item_price_numeric(self) -> None:
        """price_numeric is a float parsed from the price value string."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        assert isinstance(result["price_numeric"], float)
        assert result["price_numeric"] == 149.0

    def test_normalize_item_condition_mapping(self) -> None:
        """The eBay condition string 'Used' maps to 'gebraucht'."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        assert result["condition"] == "gebraucht"

    def test_normalize_item_datetime_parsing(self) -> None:
        """posted_at is a timezone-aware datetime."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        posted_at = result["posted_at"]
        assert posted_at.tzinfo is not None
        assert posted_at.tzinfo.utcoffset(posted_at) is not None

    def test_normalize_item_tags_default(self) -> None:
        """tags field is an empty JSON array string (never None)."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        # The actual implementation returns json.dumps([]) for the SQL ::jsonb cast
        assert json.loads(result["tags"]) == []

    def test_normalize_item_missing_seller(self) -> None:
        """author is empty string when the seller object is absent."""
        item = _load_item()
        item.pop("seller", None)
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        assert result["author"] == ""

    def test_normalize_item_shipping_formatted(self) -> None:
        """shipping field is formatted as 'Versand <value> <currency>'."""
        item = _load_item()
        result = _normalize_item(item, "flugmodelle", lat=None, lon=None)
        assert result["shipping"] == "Versand 6.99 EUR"


# ---------------------------------------------------------------------------
# _all_known
# ---------------------------------------------------------------------------


class TestAllKnown:
    @pytest.mark.asyncio
    async def test_all_known_returns_true_when_all_exist(self) -> None:
        """Returns True when every external_id in the list is already in the DB."""
        ids = ["ebay_v1|111|0", "ebay_v1|222|0"]

        # Mock session.execute() to return both IDs as known
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([("ebay_v1|111|0",), ("ebay_v1|222|0",)]))
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await _all_known(session, ids)
        assert result is True

    @pytest.mark.asyncio
    async def test_all_known_returns_false_for_new_ids(self) -> None:
        """Returns False when at least one external_id is not in the DB."""
        ids = ["ebay_v1|111|0", "ebay_v1|999|0"]

        # DB only knows about the first ID
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([("ebay_v1|111|0",)]))
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await _all_known(session, ids)
        assert result is False
