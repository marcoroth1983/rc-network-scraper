"""Unit tests for assess_homogeneity (app/analysis/similarity.py).

Run with: docker compose exec backend pytest tests/test_similarity_homogeneity.py -v
"""

from unittest.mock import MagicMock

import pytest

from app.analysis.similarity import assess_homogeneity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base(
    manufacturer: str | None = None,
    model_subtype: str | None = None,
    completeness: str | None = None,
) -> MagicMock:
    m = MagicMock()
    m.manufacturer = manufacturer
    m.model_subtype = model_subtype
    m.completeness = completeness
    return m


def _candidate(
    manufacturer: str | None = None,
    model_subtype: str | None = None,
    completeness: str | None = None,
    price_numeric: float | None = None,
) -> MagicMock:
    m = MagicMock()
    m.manufacturer = manufacturer
    m.model_subtype = model_subtype
    m.completeness = completeness
    m.price_numeric = price_numeric
    return m


def _top(candidates: list[MagicMock] | list[tuple]) -> list[tuple]:
    """Wrap bare candidates in (candidate, score) tuples."""
    result = []
    for c in candidates:
        if isinstance(c, tuple):
            result.append(c)
        else:
            result.append((c, 1.0))
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAssessHomogeneity:
    def test_three_candidates_returns_insufficient(self) -> None:
        """Fewer than MIN_TOP_SIZE (4) candidates → insufficient."""
        base = _base(manufacturer="Multiplex")
        top = _top([
            _candidate(manufacturer="Multiplex", price_numeric=100.0),
            _candidate(manufacturer="Multiplex", price_numeric=200.0),
            _candidate(manufacturer="Multiplex", price_numeric=300.0),
        ])
        quality, median = assess_homogeneity(base, top)
        assert quality == "insufficient"
        assert median is None

    def test_six_with_full_agreement_and_acceptable_spread_returns_homogeneous(self) -> None:
        """6 candidates, 100% mfr+subtype agreement, spread 3× → homogeneous with correct median."""
        base = _base(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF")
        candidates = [
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=100.0),
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=150.0),
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=200.0),
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=250.0),
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=280.0),
            _candidate(manufacturer="Multiplex", model_subtype="thermal", completeness="RTF", price_numeric=300.0),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "homogeneous"
        # statistics.median of [100, 150, 200, 250, 280, 300] = (200+250)/2 = 225
        assert median == pytest.approx(225.0)

    def test_six_with_fifty_percent_mfr_agreement_returns_heterogeneous(self) -> None:
        """6 candidates but only 3/6 (50%) share the manufacturer → heterogeneous."""
        base = _base(manufacturer="CARF")
        candidates = [
            _candidate(manufacturer="CARF", price_numeric=500.0),
            _candidate(manufacturer="CARF", price_numeric=600.0),
            _candidate(manufacturer="CARF", price_numeric=700.0),
            _candidate(manufacturer="Freewing", price_numeric=200.0),
            _candidate(manufacturer="Freewing", price_numeric=250.0),
            _candidate(manufacturer="Arrows", price_numeric=80.0),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "heterogeneous"
        assert median is None

    def test_six_with_full_agreement_but_too_wide_price_spread_returns_heterogeneous(self) -> None:
        """100% attribute agreement but price spread 5× (100–500) → heterogeneous."""
        base = _base(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF")
        candidates = [
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=100.0),
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=150.0),
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=200.0),
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=300.0),
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=400.0),
            _candidate(manufacturer="Multiplex", model_subtype="warbird", completeness="ARF", price_numeric=500.0),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "heterogeneous"
        assert median is None

    def test_base_without_manufacturer_but_with_subtype_agreement_returns_homogeneous(self) -> None:
        """Base has no manufacturer, but subtype+completeness 100% agreement + acceptable price → homogeneous."""
        base = _base(manufacturer=None, model_subtype="glider", completeness="RTF")
        candidates = [
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=300.0),
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=350.0),
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=400.0),
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=450.0),
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=500.0),
            _candidate(model_subtype="glider", completeness="RTF", price_numeric=550.0),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "homogeneous"
        assert median is not None

    def test_base_without_any_informative_attribute_returns_heterogeneous(self) -> None:
        """Base has neither manufacturer nor subtype+completeness → heterogeneous (cannot judge)."""
        base = _base(manufacturer=None, model_subtype=None, completeness=None)
        candidates = [
            _candidate(manufacturer="CARF", price_numeric=500.0),
            _candidate(manufacturer="CARF", price_numeric=600.0),
            _candidate(manufacturer="CARF", price_numeric=700.0),
            _candidate(manufacturer="CARF", price_numeric=800.0),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "heterogeneous"
        assert median is None

    def test_no_positive_prices_returns_heterogeneous(self) -> None:
        """All candidates have NULL or zero price → heterogeneous (no price data to judge)."""
        base = _base(manufacturer="Multiplex")
        candidates = [
            _candidate(manufacturer="Multiplex", price_numeric=None),
            _candidate(manufacturer="Multiplex", price_numeric=None),
            _candidate(manufacturer="Multiplex", price_numeric=None),
            _candidate(manufacturer="Multiplex", price_numeric=None),
        ]
        top = _top(candidates)
        quality, median = assess_homogeneity(base, top)
        assert quality == "heterogeneous"
        assert median is None

    def test_exactly_four_candidates_is_sufficient(self) -> None:
        """Exactly MIN_TOP_SIZE (4) candidates does not trigger insufficient."""
        base = _base(manufacturer="Robbe")
        candidates = [
            _candidate(manufacturer="Robbe", price_numeric=200.0),
            _candidate(manufacturer="Robbe", price_numeric=220.0),
            _candidate(manufacturer="Robbe", price_numeric=240.0),
            _candidate(manufacturer="Robbe", price_numeric=260.0),
        ]
        top = _top(candidates)
        quality, _ = assess_homogeneity(base, top)
        assert quality != "insufficient"
