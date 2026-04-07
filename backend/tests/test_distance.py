"""Tests for the Haversine distance utility."""

import pytest

from app.geo.distance import haversine_km


class TestHaversineKm:
    def test_same_point_returns_zero(self) -> None:
        result = haversine_km(52.5200, 13.4050, 52.5200, 13.4050)
        assert result == 0.0

    def test_berlin_to_munich_approx_504_km(self) -> None:
        # Berlin: 52.5200° N, 13.4050° E
        # Munich: 48.1351° N, 11.5820° E
        # Accepted reference: ~504 km (tolerance ±2 km)
        result = haversine_km(52.5200, 13.4050, 48.1351, 11.5820)
        assert abs(result - 504.0) <= 2.0, f"Expected ~504 km, got {result:.2f} km"

    def test_symmetry(self) -> None:
        d1 = haversine_km(52.5200, 13.4050, 48.1351, 11.5820)
        d2 = haversine_km(48.1351, 11.5820, 52.5200, 13.4050)
        assert abs(d1 - d2) < 1e-9

    def test_returns_float(self) -> None:
        result = haversine_km(0.0, 0.0, 1.0, 1.0)
        assert isinstance(result, float)
