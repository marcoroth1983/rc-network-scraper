"""Unit tests for _parse_price_numeric in the scrape orchestrator."""

import pytest

from app.scraper.orchestrator import _parse_price_numeric


@pytest.mark.parametrize(
    "price, expected",
    [
        # Basic integer values
        ("120", 120.0),
        ("700", 700.0),
        # Euro symbol variants
        ("700€", 700.0),
        ("50€", 50.0),
        ("300€", 300.0),
        # German decimal comma
        ("275,00 Euro", 275.0),
        ("275,00 EUR", 275.0),
        # Trailing dash (Verkaufspreis ohne Cents)
        ("1300,-€", 1300.0),
        ("1300,-", 1300.0),
        # Space as thousands separator
        ("1 300,00 €", 1300.0),
        ("25 €", 25.0),
        ("250 €", 250.0),
        # Dot as thousands sep + comma as decimal (German 4-digit format)
        ("1.300,00", 1300.0),
        ("2.500,00 €", 2500.0),
        # Non-breaking space (U+00A0)
        ("1\u00a0200,00\u00a0€", 1200.0),
        # Returns None for non-parseable strings
        ("VB", None),
        ("vb", None),
        ("Vb", None),
        (None, None),
        ("", None),
        # Zero is excluded (not a useful price)
        ("0", None),
        ("0,00 €", None),
        # Large prices with dot-thousands separator
        ("25.000,00 €", 25000.0),
        ("10.000,-€", 10000.0),
        # Lowercase "euro"
        ("275,00 euro", 275.0),
        # Dot-thousands with lowercase "euro" (bug: was parsed as 6.9)
        ("6.900 euro", 6900.0),
        # Trailing comma (no decimal digits)
        ("200,", 200.0),
        # Multiple prices in one string — take only the first
        ("275,- leer oder 375,- mit Antrieb", 275.0),
        ("100 oder 150 EUR", 100.0),
        # Space as thousands separator without decimal
        ("1 000", 1000.0),
        ("1 000,-", 1000.0),
        ("1 000 oder 2 000", 1000.0),
    ],
)
def test_parse_price_numeric(price: str | None, expected: float | None) -> None:
    result = _parse_price_numeric(price)
    assert result == expected, f"_parse_price_numeric({price!r}) == {result!r}, expected {expected!r}"
