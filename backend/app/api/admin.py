"""Admin-only endpoints: LLM cascade management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.analysis import model_cascade
from app.api.deps import require_admin
from app.db import AsyncSessionLocal
from app.models import User
from sqlalchemy import text

router = APIRouter(prefix="/admin", tags=["admin"])


class LLMModelRow(BaseModel):
    model_id: str
    position: int
    is_active: bool
    active_now: bool
    context_length: int | None
    created_upstream: datetime | None
    added_at: datetime
    last_refresh_at: datetime
    consecutive_failures: int
    disabled_until: datetime | None
    last_error: str | None


async def _fetch_all_rows() -> list[LLMModelRow]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT
                model_id,
                position,
                is_active,
                context_length,
                created_upstream,
                added_at,
                last_refresh_at,
                consecutive_failures,
                disabled_until,
                last_error
            FROM llm_models
            ORDER BY position ASC
        """))
        rows = result.all()

    return [
        LLMModelRow(
            model_id=row.model_id,
            position=row.position,
            is_active=row.is_active,
            active_now=(
                row.is_active
                and (row.disabled_until is None or row.disabled_until < now)
            ),
            context_length=row.context_length,
            created_upstream=row.created_upstream,
            added_at=row.added_at,
            last_refresh_at=row.last_refresh_at,
            consecutive_failures=row.consecutive_failures,
            disabled_until=row.disabled_until,
            last_error=row.last_error,
        )
        for row in rows
    ]


@router.get("/llm-models", response_model=list[LLMModelRow])
async def list_llm_models(_: User = Depends(require_admin)) -> list[LLMModelRow]:
    """Return all cascade models with live active_now computed field."""
    return await _fetch_all_rows()


@router.post("/llm-models/refresh", response_model=list[LLMModelRow])
async def refresh_llm_models(_: User = Depends(require_admin)) -> list[LLMModelRow]:
    """Trigger an immediate cascade refresh from OpenRouter, return updated rows."""
    await model_cascade.refresh_from_openrouter()
    return await _fetch_all_rows()
