"""Unit tests for the attribute-weighted similarity scorer (app/analysis/similarity.py).

Run with: docker compose exec backend pytest tests/test_similarity_scorer.py -v
"""

from unittest.mock import MagicMock

import pytest

from app.analysis.similarity import DEFAULT_WEIGHTS, SimilarityWeights, score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _listing(
    model_name: str | None = None,
    manufacturer: str | None = None,
    model_subtype: str | None = None,
    completeness: str | None = None,
    model_type: str | None = None,
    attributes: dict | None = None,
) -> MagicMock:
    """Return a mock Listing-like object."""
    m = MagicMock()
    m.model_name = model_name
    m.manufacturer = manufacturer
    m.model_subtype = model_subtype
    m.completeness = completeness
    m.model_type = model_type
    m.attributes = attributes
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimilarityScorer:
    def test_identical_attributes_returns_sum_of_all_weights(self) -> None:
        """All attributes matching → full score without any wingspan penalty."""
        w = DEFAULT_WEIGHTS
        base = _listing(
            model_name="Easy Glider",
            manufacturer="Multiplex",
            model_subtype="thermal",
            completeness="RTF",
            model_type="glider",
            attributes=None,
        )
        candidate = _listing(
            model_name="Easy Glider",
            manufacturer="Multiplex",
            model_subtype="thermal",
            completeness="RTF",
            model_type="glider",
            attributes=None,
        )
        expected = w.model_name + w.manufacturer + w.model_subtype + w.completeness + w.model_type
        assert score(base, candidate) == pytest.approx(expected)

    def test_only_manufacturer_match_returns_manufacturer_weight(self) -> None:
        """Only manufacturer matches → only w.manufacturer contributes."""
        base = _listing(manufacturer="CARF", model_name="Prime Jet")
        candidate = _listing(manufacturer="CARF", model_name="Rebel Jet")
        result = score(base, candidate)
        assert result == pytest.approx(DEFAULT_WEIGHTS.manufacturer)

    def test_wingspan_diff_500mm_reduces_score_by_one(self) -> None:
        """500 mm wingspan difference → -1.0 penalty (0.002 per mm × 500)."""
        base = _listing(
            manufacturer="CARF",
            attributes={"wingspan_mm": "1500"},
        )
        candidate = _listing(
            manufacturer="CARF",
            attributes={"wingspan_mm": "2000"},
        )
        # manufacturer match: +3.0, wingspan penalty: -1.0
        expected = DEFAULT_WEIGHTS.manufacturer - 1.0
        assert score(base, candidate) == pytest.approx(expected)

    def test_garbage_wingspan_value_has_no_effect(self) -> None:
        """Garbage wingspan string like 'weight_g' is ignored — no penalty applied."""
        base = _listing(
            manufacturer="Arrows",
            attributes={"wingspan_mm": "weight_g"},
        )
        candidate = _listing(
            manufacturer="Arrows",
            attributes={"wingspan_mm": "1200"},
        )
        # Only manufacturer weight — no wingspan penalty because base wingspan is invalid
        assert score(base, candidate) == pytest.approx(DEFAULT_WEIGHTS.manufacturer)

    def test_casing_difference_counts_as_equal(self) -> None:
        """'CARF' vs 'Carf' should match (case-insensitive comparison)."""
        base = _listing(manufacturer="CARF")
        candidate = _listing(manufacturer="Carf")
        assert score(base, candidate) == pytest.approx(DEFAULT_WEIGHTS.manufacturer)

    def test_null_attributes_listing_scores_zero(self) -> None:
        """Listing with all NULL attributes scores 0.0 against anything."""
        base = _listing()
        candidate = _listing(
            model_name="L-39",
            manufacturer="Black Horse",
            model_subtype="warbird",
            completeness="ARF",
            model_type="airplane",
        )
        assert score(base, candidate) == pytest.approx(0.0)

    def test_wingspan_out_of_bounds_is_ignored(self) -> None:
        """Wingspan values outside [100, 10000] mm are treated as invalid."""
        base = _listing(
            manufacturer="Multiplex",
            attributes={"wingspan_mm": "50"},  # below 100 mm bound
        )
        candidate = _listing(
            manufacturer="Multiplex",
            attributes={"wingspan_mm": "1800"},
        )
        # No wingspan penalty — base wingspan filtered out as implausible
        assert score(base, candidate) == pytest.approx(DEFAULT_WEIGHTS.manufacturer)

    def test_both_wingspan_none_no_penalty(self) -> None:
        """If neither listing has wingspan data, no penalty is applied."""
        base = _listing(manufacturer="Robbe", attributes=None)
        candidate = _listing(manufacturer="Robbe", attributes=None)
        assert score(base, candidate) == pytest.approx(DEFAULT_WEIGHTS.manufacturer)
