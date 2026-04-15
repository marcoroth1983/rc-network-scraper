"""Dynamic free-tier model cascade backed by the `llm_models` DB table.

Responsibilities:
  - load_cascade()            — current active cascade (cached in-process, 60s TTL)
  - record_success(model_id)  — clear failure counter + disabled_until
  - record_failure(model_id, error) — increment counter, auto-disable after 3 strikes
  - refresh_from_openrouter() — fetch latest top-N free+SO models, upsert into DB
  - seed_if_empty()           — on startup, seed from OPENROUTER_FREE_MODELS env if empty

Failure policy:
  - 3 consecutive failures → disabled for 1 hour (auto re-enabled after that)
  - Successful call resets the counter to 0 and clears any disabled_until
  - The 12h refresh preserves per-model failure counters for surviving models
    and resets them for models newly added to the cascade.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 60.0
REFRESH_TIMEOUT = 15.0

# These fall back to module-level defaults if settings are not yet loaded
# (e.g. during import in tests). The properties are accessed lazily.
def _top_n() -> int:
    return settings.LLM_CASCADE_TOP_N

def _failure_threshold() -> int:
    return settings.LLM_CASCADE_FAILURE_THRESHOLD

def _disable_duration() -> timedelta:
    return timedelta(hours=settings.LLM_CASCADE_DISABLE_HOURS)

# Simple in-process cache: the cascade list is read on every analyze_listing()
# call; querying Postgres every time is fine but wasteful. 60s TTL is short
# enough that failure-demotions propagate quickly between workers.
_cache: tuple[float, list[str]] | None = None


def _invalidate_cache() -> None:
    global _cache
    _cache = None


async def load_cascade() -> list[str]:
    """Return the active cascade (not-disabled, ordered by position).

    Empty list means we should fall through to the paid fallback.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and (now - _cache[0]) < CACHE_TTL_SECONDS:
        return _cache[1]

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT model_id
            FROM llm_models
            WHERE is_active = TRUE
              AND (disabled_until IS NULL OR disabled_until < now())
            ORDER BY position ASC
        """))
        models = [row[0] for row in result.all()]

    _cache = (now, models)
    return models


async def record_success(model_id: str) -> None:
    """Mark a successful call — clear failure counter and any disable window."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                UPDATE llm_models
                SET consecutive_failures = 0,
                    disabled_until = NULL,
                    last_error = NULL
                WHERE model_id = :mid AND (consecutive_failures > 0 OR disabled_until IS NOT NULL)
            """),
            {"mid": model_id},
        )
        await session.commit()


async def record_failure(model_id: str, error: str) -> None:
    """Increment failure counter; auto-disable after LLM_CASCADE_FAILURE_THRESHOLD strikes."""
    threshold = _failure_threshold()
    disabled_until = datetime.now(timezone.utc) + _disable_duration()
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                UPDATE llm_models
                SET consecutive_failures = consecutive_failures + 1,
                    last_error = :err,
                    disabled_until = CASE
                        WHEN consecutive_failures + 1 >= :threshold THEN :until
                        ELSE disabled_until
                    END
                WHERE model_id = :mid
            """),
            {
                "mid": model_id,
                "err": error[:500],
                "threshold": threshold,
                "until": disabled_until,
            },
        )
        # Fetch updated state so we can log a useful DISABLE warning
        result = await session.execute(
            text("SELECT consecutive_failures, disabled_until FROM llm_models WHERE model_id = :mid"),
            {"mid": model_id},
        )
        row = result.one_or_none()
        await session.commit()

    _invalidate_cache()

    if row is not None:
        failures, until = row
        if failures >= threshold and until is not None:
            logger.warning(
                "DISABLE [%s] — consecutive_failures=%d, disabled_until=%s, last_error=%s",
                model_id, failures, until.isoformat(), error[:200],
            )


def _is_zero_price(value: object) -> bool:
    """Return True if the pricing value represents zero cost.

    OpenRouter represents free-tier pricing as various zero shapes:
    "0", "0.0", 0 (int), 0.0 (float).  We convert to float inside a
    try/except so upstream format drift doesn't wipe the cascade.
    """
    try:
        return float(value) == 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _filter_upstream(models: list[dict], top_n: int) -> list[dict]:
    """Apply selection heuristics: free + structured_outputs + not aggregator.

    We deliberately do NOT exclude preview/alpha/beta tagged models. The
    runtime failure-tracking handles unreliable models by auto-disabling them
    — being too restrictive here shrinks the pool to nothing on bad days.
    """
    picks: list[dict] = []
    for m in models:
        pricing = m.get("pricing", {}) or {}
        if not _is_zero_price(pricing.get("prompt")):
            continue
        if not _is_zero_price(pricing.get("completion")):
            continue
        mid = m.get("id", "")
        if not mid or mid.startswith("openrouter/"):
            # Skip aggregator endpoints — opaque routing, not a real model.
            continue
        supported = m.get("supported_parameters", []) or []
        if "structured_outputs" not in supported:
            continue
        picks.append({
            "id": mid,
            "created": m.get("created") or 0,
            "ctx": m.get("context_length") or 0,
        })

    picks.sort(key=lambda x: x["created"], reverse=True)
    return picks[:top_n]


async def refresh_from_openrouter(top_n: int | None = None) -> dict:
    """Fetch current top-N free+SO models and upsert into llm_models.

    - Existing rows keep their consecutive_failures / disabled_until.
    - New rows start fresh (failures=0, disabled_until=NULL).
    - Rows not in the new top-N are deleted (cascade size stays bounded).
    - Returns a summary dict for logging: {added, kept, removed}.
    """
    resolved_top_n = top_n if top_n is not None else _top_n()
    logger.info("model_cascade: refresh starting — top_n=%d", resolved_top_n)

    async with httpx.AsyncClient(timeout=REFRESH_TIMEOUT) as client:
        resp = await client.get(OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        upstream = resp.json().get("data", []) or []

    picks = _filter_upstream(upstream, resolved_top_n)
    if not picks:
        logger.error("model_cascade: OpenRouter returned 0 eligible models — aborting refresh")
        return {"added": 0, "kept": 0, "removed": 0, "error": "no_eligible_models"}

    new_ids = {p["id"] for p in picks}

    async with AsyncSessionLocal() as session:
        existing = await session.execute(text("SELECT model_id FROM llm_models"))
        existing_ids = {row[0] for row in existing.all()}

        added: list[str] = []
        kept: list[str] = []
        for position, p in enumerate(picks):
            created_ts = datetime.fromtimestamp(p["created"], tz=timezone.utc) if p["created"] else None
            if p["id"] in existing_ids:
                kept.append(p["id"])
                await session.execute(
                    text("""
                        UPDATE llm_models
                        SET position = :pos,
                            context_length = :ctx,
                            created_upstream = :created,
                            last_refresh_at = now()
                        WHERE model_id = :mid
                    """),
                    {"pos": position, "ctx": p["ctx"], "created": created_ts, "mid": p["id"]},
                )
            else:
                added.append(p["id"])
                await session.execute(
                    text("""
                        INSERT INTO llm_models
                            (model_id, position, context_length, created_upstream)
                        VALUES (:mid, :pos, :ctx, :created)
                    """),
                    {"mid": p["id"], "pos": position, "ctx": p["ctx"], "created": created_ts},
                )

        removed_ids = list(existing_ids - new_ids)
        if removed_ids:
            await session.execute(
                text("DELETE FROM llm_models WHERE model_id = ANY(:ids)"),
                {"ids": removed_ids},
            )
        await session.commit()

    _invalidate_cache()
    logger.info(
        "model_cascade: refresh done — added=%s kept=%s removed=%s",
        added, kept, removed_ids,
    )
    return {"added": added, "kept": kept, "removed": removed_ids}


async def seed_if_empty() -> None:
    """Seed the cascade from OPENROUTER_FREE_MODELS env on first boot / empty DB.

    Done once at startup; the 12h refresh then takes over.
    """
    async with AsyncSessionLocal() as session:
        count = await session.execute(text("SELECT COUNT(*) FROM llm_models"))
        if count.scalar() or 0:
            return

        seed_list = settings.openrouter_free_models_list
        if not seed_list:
            logger.warning("model_cascade: llm_models empty and OPENROUTER_FREE_MODELS unset")
            return

        for position, mid in enumerate(seed_list):
            await session.execute(
                text("""
                    INSERT INTO llm_models (model_id, position)
                    VALUES (:mid, :pos)
                    ON CONFLICT (model_id) DO NOTHING
                """),
                {"mid": mid, "pos": position},
            )
        await session.commit()
        logger.info("model_cascade: seeded %d models from env", len(seed_list))


async def refresh_job() -> None:
    """Entry point for the APScheduler 12h job. Logs errors, never raises."""
    try:
        result = await refresh_from_openrouter()
        if result.get("error"):
            logger.warning("model_cascade: refresh skipped — %s", result["error"])
    except Exception as exc:
        logger.exception("model_cascade: refresh job failed: %s", exc)
