"""Regression test for init_db() schema migrations.

Guards against the saved_searches drift (PLAN-031): columns added to a model
after its table already exists must be mirrored as explicit ALTERs in init_db(),
or prod (where the table pre-exists) is missing them. conftest rebuilds the
schema from Base.metadata, so only a legacy-shaped table reproduces the bug.
"""
import pytest
from sqlalchemy import text

import app.db as db_module
from app.db import init_db

_FILTER_COLUMNS = [
    "price_min", "price_max", "drive_type", "completeness", "shipping_available",
    "model_type", "model_subtype", "show_outdated", "only_sold",
]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_init_db_readds_saved_search_filter_columns(test_engine, monkeypatch):
    # Bind init_db() to the test engine (it uses the module-global `engine`).
    monkeypatch.setattr(db_module, "engine", test_engine)

    # Simulate the legacy prod table: drop the 9 filter columns.
    async with test_engine.begin() as conn:
        for col in _FILTER_COLUMNS:
            await conn.execute(text(f"ALTER TABLE saved_searches DROP COLUMN IF EXISTS {col}"))

    # Run the real migration.
    await init_db()

    # All 9 columns must exist again.
    async with test_engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'saved_searches'"
        ))
        present = {row[0] for row in result.fetchall()}
    missing = [c for c in _FILTER_COLUMNS if c not in present]
    assert not missing, f"init_db did not add columns: {missing}"
