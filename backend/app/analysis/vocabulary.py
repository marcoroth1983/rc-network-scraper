"""Canonical vocabulary for LLM-extracted model classification fields.

All values are lowercase. clamp_* helpers normalise LLM output to canonical
values or None — they never raise.
"""
from __future__ import annotations

MODEL_TYPES: set[str] = {
    "airplane", "helicopter", "multicopter", "glider", "boat", "car",
}

MODEL_SUBTYPES: dict[str, set[str]] = {
    "airplane": {
        "jet", "warbird", "trainer", "scale", "3d", "nurflügler",
        "hochdecker", "tiefdecker", "mitteldecker", "delta", "biplane",
        "aerobatic", "kit", "hotliner", "funflyer", "speed", "pylon",
    },
    "helicopter": {"700", "580", "600", "550", "500", "450", "420", "380", "scale"},
    "glider": {
        "thermik", "hotliner", "f3b", "f3k", "f3j", "f5j", "f5b", "f5k",
        "f3f", "f3l", "hangflug", "dlg", "scale", "motorglider",
    },
    "multicopter": {"quadcopter", "hexacopter", "fpv"},
    "boat": {"rennboot", "segelboot", "schlepper", "submarine", "yacht"},
    "car": {"buggy", "monstertruck", "crawler", "tourenwagen", "truggy", "drift"},
}


def clamp_model_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    return v if v in MODEL_TYPES else None


def clamp_model_subtype(model_type: str | None, value: str | None) -> str | None:
    if not model_type or not value:
        return None
    allowed = MODEL_SUBTYPES.get(model_type, set())
    v = value.strip().lower()
    return v if v in allowed else None
