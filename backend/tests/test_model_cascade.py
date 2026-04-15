"""Unit tests for app/analysis/model_cascade.py.

All DB calls are mocked — no real database connection required.
Run with: docker compose exec backend pytest tests/test_model_cascade.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis.model_cascade import (
    _filter_upstream,
    _invalidate_cache,
    _is_zero_price,
    load_cascade,
    record_failure,
    record_success,
    refresh_from_openrouter,
    seed_if_empty,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upstream_model(
    model_id: str = "vendor/model:free",
    prompt_price: object = "0",
    completion_price: object = "0",
    supported: list[str] | None = None,
    created: int = 1_700_000_000,
    context_length: int = 131072,
) -> dict:
    return {
        "id": model_id,
        "pricing": {"prompt": prompt_price, "completion": completion_price},
        "supported_parameters": supported if supported is not None else ["structured_outputs"],
        "created": created,
        "context_length": context_length,
    }


def _session_ctx_returning(rows: list) -> MagicMock:
    """Return a context-manager mock whose execute().all() returns *rows*."""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _scalar_ctx(scalar_value: object) -> MagicMock:
    """Context-manager mock whose execute().scalar() returns *scalar_value*."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = scalar_value
    session.execute.return_value = result

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# _is_zero_price — pricing shape handling
# ---------------------------------------------------------------------------

class TestIsZeroPrice:
    def test_string_zero(self) -> None:
        assert _is_zero_price("0") is True

    def test_string_zero_dot_zero(self) -> None:
        assert _is_zero_price("0.0") is True

    def test_int_zero(self) -> None:
        assert _is_zero_price(0) is True

    def test_float_zero(self) -> None:
        assert _is_zero_price(0.0) is True

    def test_nonzero_string(self) -> None:
        assert _is_zero_price("0.0000015") is False

    def test_nonzero_float(self) -> None:
        assert _is_zero_price(0.0000015) is False

    def test_none(self) -> None:
        assert _is_zero_price(None) is False

    def test_garbage_string(self) -> None:
        assert _is_zero_price("free") is False


# ---------------------------------------------------------------------------
# _filter_upstream — pricing / SO / aggregator rules
# ---------------------------------------------------------------------------

class TestFilterUpstream:
    def test_keeps_free_so_model(self) -> None:
        models = [_make_upstream_model("good/model:free")]
        result = _filter_upstream(models, top_n=4)
        assert len(result) == 1
        assert result[0]["id"] == "good/model:free"

    def test_excludes_paid_prompt(self) -> None:
        models = [_make_upstream_model("paid/model", prompt_price="0.0000015")]
        assert _filter_upstream(models, top_n=4) == []

    def test_excludes_paid_completion(self) -> None:
        models = [_make_upstream_model("paid/model", completion_price="0.0000015")]
        assert _filter_upstream(models, top_n=4) == []

    def test_excludes_aggregator(self) -> None:
        models = [_make_upstream_model("openrouter/auto")]
        assert _filter_upstream(models, top_n=4) == []

    def test_excludes_no_structured_outputs(self) -> None:
        models = [_make_upstream_model(supported=["temperature"])]
        assert _filter_upstream(models, top_n=4) == []

    def test_respects_top_n(self) -> None:
        models = [
            _make_upstream_model(f"vendor/model-{i}:free", created=1_700_000_000 - i)
            for i in range(6)
        ]
        result = _filter_upstream(models, top_n=3)
        assert len(result) == 3

    def test_sorts_by_created_desc(self) -> None:
        models = [
            _make_upstream_model("vendor/old:free", created=1_000_000),
            _make_upstream_model("vendor/new:free", created=2_000_000),
        ]
        result = _filter_upstream(models, top_n=4)
        assert result[0]["id"] == "vendor/new:free"

    def test_pricing_string_zero_dot_zero(self) -> None:
        models = [_make_upstream_model("vendor/model:free", prompt_price="0.0", completion_price="0.0")]
        assert len(_filter_upstream(models, top_n=4)) == 1

    def test_pricing_int_zero(self) -> None:
        models = [_make_upstream_model("vendor/model:free", prompt_price=0, completion_price=0)]
        assert len(_filter_upstream(models, top_n=4)) == 1

    def test_pricing_float_zero(self) -> None:
        models = [_make_upstream_model("vendor/model:free", prompt_price=0.0, completion_price=0.0)]
        assert len(_filter_upstream(models, top_n=4)) == 1


# ---------------------------------------------------------------------------
# load_cascade — excludes disabled / respects is_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLoadCascade:
    async def test_returns_active_models(self) -> None:
        _invalidate_cache()
        rows = [("vendor/model-a:free",), ("vendor/model-b:free",)]
        ctx = _session_ctx_returning(rows)
        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            result = await load_cascade()
        assert result == ["vendor/model-a:free", "vendor/model-b:free"]

    async def test_returns_empty_when_all_disabled(self) -> None:
        _invalidate_cache()
        ctx = _session_ctx_returning([])
        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            result = await load_cascade()
        assert result == []

    async def test_uses_cache_on_second_call(self) -> None:
        _invalidate_cache()
        rows = [("vendor/model:free",)]
        ctx = _session_ctx_returning(rows)
        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx) as mock_factory:
            await load_cascade()
            await load_cascade()
        # Second call must not create a new DB session
        assert mock_factory.call_count == 1

    async def test_invalidate_cache_forces_db_hit(self) -> None:
        _invalidate_cache()
        rows = [("vendor/model:free",)]
        ctx = _session_ctx_returning(rows)
        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx) as mock_factory:
            await load_cascade()
            _invalidate_cache()
            await load_cascade()
        assert mock_factory.call_count == 2


# ---------------------------------------------------------------------------
# record_failure — disable after threshold + cache invalidation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRecordFailure:
    async def _make_session_for_failure(
        self, failures_after: int, disabled_until: datetime | None
    ) -> tuple[MagicMock, MagicMock]:
        """Return (update_session, ctx) where post-update SELECT returns (failures, until)."""
        session = AsyncMock()

        update_result = MagicMock()
        select_result = MagicMock()
        select_result.one_or_none.return_value = (failures_after, disabled_until)

        call_count = 0

        async def _execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return select_result if call_count == 2 else update_result

        session.execute.side_effect = _execute

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return session, ctx

    async def test_cache_invalidated_on_failure(self) -> None:
        """record_failure must invalidate the in-process cache."""
        _invalidate_cache()
        # Pre-populate the cache
        rows = [("vendor/model:free",)]
        load_ctx = _session_ctx_returning(rows)
        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=load_ctx):
            await load_cascade()

        # Now fire a failure — cache must be wiped
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        _, fail_ctx = await self._make_session_for_failure(3, future)

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=fail_ctx):
            with patch("app.analysis.model_cascade.settings") as mock_cfg:
                mock_cfg.LLM_CASCADE_FAILURE_THRESHOLD = 3
                mock_cfg.LLM_CASCADE_DISABLE_HOURS = 1.0
                await record_failure("vendor/model:free", "timeout")

        # Cache must be None — next load_cascade will hit DB
        from app.analysis import model_cascade as mc
        assert mc._cache is None

    async def test_disable_logged_at_threshold(self) -> None:
        """WARNING DISABLE message is emitted when failures >= threshold."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        _, ctx = await self._make_session_for_failure(3, future)

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.settings") as mock_cfg:
                mock_cfg.LLM_CASCADE_FAILURE_THRESHOLD = 3
                mock_cfg.LLM_CASCADE_DISABLE_HOURS = 1.0
                with patch("app.analysis.model_cascade.logger") as mock_logger:
                    await record_failure("vendor/model:free", "RateLimitError: 429")
                    mock_logger.warning.assert_called_once()
                    call_args = mock_logger.warning.call_args[0]
                    assert "DISABLE" in call_args[0]
                    assert "vendor/model:free" in call_args[1]

    async def test_no_disable_log_below_threshold(self) -> None:
        """No DISABLE warning before threshold is reached."""
        _, ctx = await self._make_session_for_failure(1, None)

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.settings") as mock_cfg:
                mock_cfg.LLM_CASCADE_FAILURE_THRESHOLD = 3
                mock_cfg.LLM_CASCADE_DISABLE_HOURS = 1.0
                with patch("app.analysis.model_cascade.logger") as mock_logger:
                    await record_failure("vendor/model:free", "timeout")
                    mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# record_success — clears disable state and counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRecordSuccess:
    async def test_clears_failure_state(self) -> None:
        session = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            await record_success("vendor/model:free")

        session.execute.assert_called_once()
        session.commit.assert_called_once()
        sql = session.execute.call_args[0][0].text
        assert "consecutive_failures = 0" in sql
        assert "disabled_until = NULL" in sql


# ---------------------------------------------------------------------------
# refresh_from_openrouter — preserves counters + zero-eligible guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRefreshFromOpenrouter:
    def _make_refresh_session(
        self, existing_ids: list[str]
    ) -> tuple[MagicMock, MagicMock]:
        session = AsyncMock()
        existing_result = MagicMock()
        existing_result.all.return_value = [(mid,) for mid in existing_ids]
        session.execute.return_value = existing_result

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return session, ctx

    async def test_preserves_failure_counters_for_kept_models(self) -> None:
        """Models surviving a refresh must not have their failure state reset."""
        upstream = [_make_upstream_model("vendor/kept:free")]
        _, ctx = self._make_refresh_session(["vendor/kept:free"])

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(return_value=MagicMock(
                        raise_for_status=MagicMock(),
                        json=MagicMock(return_value={"data": upstream}),
                    ))
                ))
                mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await refresh_from_openrouter(top_n=4)

        assert "vendor/kept:free" in result["kept"]
        assert result["added"] == []

        # Verify the UPDATE (not INSERT) was called for the kept model
        session = await ctx.__aenter__()
        calls = [str(c[0][0]) for c in session.execute.call_args_list if hasattr(c[0][0], "text")]
        # There should be no INSERT for the kept model — only UPDATE
        inserts = [c for c in calls if "INSERT" in c]
        assert len(inserts) == 0

    async def test_aborts_when_zero_eligible(self) -> None:
        """If upstream returns 0 eligible models, refresh must abort without wiping DB."""
        # All models are paid
        upstream = [_make_upstream_model("paid/model", prompt_price="0.001")]
        _, ctx = self._make_refresh_session(["vendor/existing:free"])

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(return_value=MagicMock(
                        raise_for_status=MagicMock(),
                        json=MagicMock(return_value={"data": upstream}),
                    ))
                ))
                mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await refresh_from_openrouter(top_n=4)

        assert result.get("error") == "no_eligible_models"
        # The DB session must NOT have been entered (no writes happened)
        ctx.__aenter__.assert_not_called()

    async def test_adds_new_model(self) -> None:
        upstream = [_make_upstream_model("vendor/new:free")]
        _, ctx = self._make_refresh_session([])  # nothing pre-existing

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.httpx.AsyncClient") as mock_http:
                mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(return_value=MagicMock(
                        raise_for_status=MagicMock(),
                        json=MagicMock(return_value={"data": upstream}),
                    ))
                ))
                mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await refresh_from_openrouter(top_n=4)

        assert "vendor/new:free" in result["added"]


# ---------------------------------------------------------------------------
# seed_if_empty — no-op when table is non-empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeedIfEmpty:
    async def test_noop_when_table_has_rows(self) -> None:
        """seed_if_empty must not insert anything when llm_models is non-empty."""
        ctx = _scalar_ctx(2)  # COUNT(*) = 2

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.settings") as mock_cfg:
                mock_cfg.openrouter_free_models_list = ["vendor/model:free"]
                await seed_if_empty()

        session = await ctx.__aenter__()
        # Only a SELECT COUNT(*) should have been executed, no INSERT
        assert session.execute.call_count == 1
        assert session.commit.call_count == 0

    async def test_inserts_when_empty(self) -> None:
        """seed_if_empty must insert rows when the table is empty."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        session.execute.return_value = count_result

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.analysis.model_cascade.AsyncSessionLocal", return_value=ctx):
            with patch("app.analysis.model_cascade.settings") as mock_cfg:
                mock_cfg.openrouter_free_models_list = ["vendor/model-a:free", "vendor/model-b:free"]
                await seed_if_empty()

        # Two INSERTs + one commit
        assert session.execute.call_count == 3  # 1 COUNT + 2 INSERTs
        session.commit.assert_called_once()
