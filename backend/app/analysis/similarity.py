"""Attribute-weighted similarity scoring between listings + homogeneity assessment.

Transparent, no ML. Weights are tuned by eye and adjustable in one place.
A score is only meaningful in relative terms (ranking), not as an absolute value.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any, Literal

_WINGSPAN_NUMERIC = re.compile(r"^\d+$")


def _parse_wingspan(attrs: dict[str, Any] | None) -> int | None:
    """Return numeric wingspan in mm or None. Filters out LLM garbage like 'weight_g'."""
    if not attrs:
        return None
    raw = attrs.get("wingspan_mm")
    if raw is None:
        return None
    s = str(raw).strip()
    if not _WINGSPAN_NUMERIC.match(s):
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    # plausibility bounds: 100 mm (tiny indoor) to 10 000 mm (large scale)
    return v if 100 <= v <= 10_000 else None


def _eq_ci(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.strip().casefold() == b.strip().casefold()


@dataclass(frozen=True)
class SimilarityWeights:
    model_name: float = 5.0
    manufacturer: float = 3.0
    model_subtype: float = 2.0
    completeness: float = 2.0
    model_type: float = 1.0
    wingspan_penalty_per_mm: float = 0.002  # 500 mm diff → -1.0


DEFAULT_WEIGHTS = SimilarityWeights()


def score(base: Any, candidate: Any, w: SimilarityWeights = DEFAULT_WEIGHTS) -> float:
    """Score similarity between two Listing-like objects (must expose the same attrs as Listing)."""
    s = 0.0
    if _eq_ci(base.model_name, candidate.model_name):
        s += w.model_name
    if _eq_ci(base.manufacturer, candidate.manufacturer):
        s += w.manufacturer
    if _eq_ci(base.model_subtype, candidate.model_subtype):
        s += w.model_subtype
    if _eq_ci(base.completeness, candidate.completeness):
        s += w.completeness
    if _eq_ci(base.model_type, candidate.model_type):
        s += w.model_type

    base_span = _parse_wingspan(base.attributes)
    cand_span = _parse_wingspan(candidate.attributes)
    if base_span is not None and cand_span is not None:
        s -= w.wingspan_penalty_per_mm * abs(base_span - cand_span)

    return s


# -------------------------------------------------------------------------
# Homogeneity assessment — shared between API route and analysis job.
# Centralised here to prevent drift.
# -------------------------------------------------------------------------

# Tunable thresholds
MIN_TOP_SIZE = 4                # < this many scorable candidates → insufficient
MIN_ATTR_AGREEMENT = 0.7        # ≥ this fraction of top must share the attribute with the base
MAX_PRICE_SPREAD = 4.0          # max/min ratio on the prices in top

Quality = Literal["homogeneous", "heterogeneous", "insufficient"]


def assess_homogeneity(base: Any, top: list[tuple[Any, float]]) -> tuple[Quality, float | None]:
    """Decide whether a top-N set is homogeneous and compute a median if so.

    Rules:
    - If |top| < MIN_TOP_SIZE → ('insufficient', None).
    - NULL base attributes are treated as 'not informative' (neutral): they do not
      force heterogeneous. If NONE of {manufacturer, model_subtype+completeness}
      are informative on the base → ('heterogeneous', None) — we cannot judge.
    - Otherwise require ≥ MIN_ATTR_AGREEMENT on each informative base attribute.
    - Price spread max/min (positive prices only) must be ≤ MAX_PRICE_SPREAD.
    """
    n = len(top)
    if n < MIN_TOP_SIZE:
        return ("insufficient", None)

    base_mfr = (base.manufacturer or "").strip().casefold()
    base_sub = (base.model_subtype or "").strip().casefold()
    base_cmp = (base.completeness or "").strip().casefold()

    mfr_informative = bool(base_mfr)
    sub_informative = bool(base_sub) and bool(base_cmp)

    if not mfr_informative and not sub_informative:
        return ("heterogeneous", None)

    if mfr_informative:
        mfr_hits = sum(
            1 for c, _ in top
            if (c.manufacturer or "").strip().casefold() == base_mfr
        )
        if mfr_hits / n < MIN_ATTR_AGREEMENT:
            return ("heterogeneous", None)

    if sub_informative:
        sub_hits = sum(
            1 for c, _ in top
            if (c.model_subtype or "").strip().casefold() == base_sub
            and (c.completeness or "").strip().casefold() == base_cmp
        )
        if sub_hits / n < MIN_ATTR_AGREEMENT:
            return ("heterogeneous", None)

    prices = [float(c.price_numeric) for c, _ in top
              if c.price_numeric is not None and c.price_numeric > 0]
    if not prices:
        return ("heterogeneous", None)
    if max(prices) / min(prices) > MAX_PRICE_SPREAD:
        return ("heterogeneous", None)

    return ("homogeneous", statistics.median(prices))
