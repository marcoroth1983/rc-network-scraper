"""Tests for the detail page parser."""

from datetime import datetime, timezone
from pathlib import Path

from app.scraper.parser import parse_detail

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseComplete:
    def test_all_fields_from_complete(self) -> None:
        """All structured fields are non-null when the complete fixture is parsed."""
        result = parse_detail(_load("detail_complete.html"))

        assert result["title"] is not None
        assert result["price"] is not None
        assert result["condition"] is not None
        assert result["shipping"] is not None
        assert result["plz"] is not None
        assert result["city"] is not None
        assert result["description"] is not None
        assert result["author"] is not None
        assert result["posted_at"] is not None

    def test_correct_field_values(self) -> None:
        """Parsed field values match the values in the HTML fixture."""
        result = parse_detail(_load("detail_complete.html"))

        assert result["title"] == "Biete Multiplex EasyStar 3 komplett"
        assert result["price"] == "150€"
        assert result["condition"] == "Neuwertig"
        assert result["shipping"] == "DHL 5€"
        assert result["plz"] == "80331"
        assert result["city"] == "München"
        assert result["author"] == "TestUser"

    def test_images_extracted(self) -> None:
        """At least one image URL is extracted from the complete fixture."""
        result = parse_detail(_load("detail_complete.html"))
        assert isinstance(result["images"], list)
        assert len(result["images"]) >= 1


class TestMissingFields:
    def test_missing_price_is_null(self) -> None:
        """price is None when the Preis: row is absent."""
        result = parse_detail(_load("detail_missing_price.html"))
        assert result["price"] is None

    def test_missing_location_is_null(self) -> None:
        """plz and city are None when the Artikelstandort: row is absent."""
        result = parse_detail(_load("detail_missing_location.html"))
        assert result["plz"] is None
        assert result["city"] is None

    def test_city_only_location(self) -> None:
        """city is extracted and plz is None when Artikelstandort has no PLZ prefix."""
        result = parse_detail(_load("detail_malformed_location.html"))
        assert result["plz"] is None
        assert result["city"] == "München"

    def test_no_images_returns_empty_list(self) -> None:
        """images is an empty list when no attachment images are present."""
        result = parse_detail(_load("detail_no_images.html"))
        assert result["images"] == []


class TestFirstPostIsolation:
    def test_author_is_from_first_post(self) -> None:
        """author is taken from the first post, not from any reply."""
        result = parse_detail(_load("detail_complete.html"))
        assert result["author"] == "TestUser"

    def test_first_post_isolation(self) -> None:
        """The reply author (OtherUser) and reply price (99€) must not appear."""
        result = parse_detail(_load("detail_complete.html"))
        # Author must be the original poster
        assert result["author"] != "OtherUser"
        # Price must be from the first post only
        assert result["price"] == "150€"


class TestDateParsing:
    def test_date_parsed_to_datetime(self) -> None:
        """posted_at is a datetime instance."""
        result = parse_detail(_load("detail_complete.html"))
        assert isinstance(result["posted_at"], datetime)

    def test_date_is_timezone_aware(self) -> None:
        """posted_at carries timezone information."""
        result = parse_detail(_load("detail_complete.html"))
        assert result["posted_at"].tzinfo is not None

    def test_date_raw_stored(self) -> None:
        """posted_at_raw contains the original datetime string from the HTML."""
        result = parse_detail(_load("detail_complete.html"))
        assert result["posted_at_raw"] == "2024-03-15T10:30:00+01:00"
