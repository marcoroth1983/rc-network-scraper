"""Unit tests for the controlled vocabulary helpers.

Run with:
    docker compose exec backend pytest tests/test_vocabulary.py -v
"""
import pytest
from app.analysis.vocabulary import MODEL_TYPES, MODEL_SUBTYPES, clamp_model_type, clamp_model_subtype


def test_model_types_are_expected_set():
    assert MODEL_TYPES == {"airplane", "helicopter", "multicopter", "glider", "boat", "car"}


def test_clamp_model_type_known_value():
    assert clamp_model_type("airplane") == "airplane"


def test_clamp_model_type_unknown_returns_none():
    assert clamp_model_type("rc-elektronik") is None
    assert clamp_model_type("engine") is None
    assert clamp_model_type("Unknown") is None


def test_clamp_model_type_none_returns_none():
    assert clamp_model_type(None) is None


def test_clamp_model_subtype_known():
    assert clamp_model_subtype("airplane", "jet") == "jet"
    assert clamp_model_subtype("glider", "thermik") == "thermik"
    assert clamp_model_subtype("helicopter", "700") == "700"


def test_clamp_model_subtype_case_insensitive():
    assert clamp_model_subtype("airplane", "JET") == "jet"
    assert clamp_model_subtype("glider", "F5J") == "f5j"


def test_clamp_model_subtype_unknown_returns_none():
    assert clamp_model_subtype("airplane", "high-wing") is None
    assert clamp_model_subtype("airplane", "high_wing") is None
    assert clamp_model_subtype("airplane", "aerobatic_plane") is None


def test_clamp_model_subtype_case_normalizes_to_canonical():
    # "3D" lowercases to "3d" which IS canonical — should return "3d", not None
    assert clamp_model_subtype("airplane", "3D") == "3d"
    assert clamp_model_subtype("glider", "F5J") == "f5j"


def test_clamp_model_subtype_none_model_type_returns_none():
    assert clamp_model_subtype(None, "jet") is None


def test_clamp_model_subtype_none_subtype_returns_none():
    assert clamp_model_subtype("airplane", None) is None


def test_model_subtypes_airplane_contains_required_values():
    airplane = MODEL_SUBTYPES["airplane"]
    for v in ("jet", "warbird", "trainer", "scale", "3d", "hochdecker", "tiefdecker"):
        assert v in airplane, f"Missing: {v}"
