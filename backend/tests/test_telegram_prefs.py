"""Tests for app.telegram.prefs — notification preference upsert."""

import pytest
from app.telegram import prefs


@pytest.mark.asyncio
async def test_get_defaults_all_true(db_user):
    p = await prefs.get_prefs(db_user.id)
    assert all([p.new_search_results, p.fav_sold, p.fav_price, p.fav_deleted])


@pytest.mark.asyncio
async def test_partial_update_keeps_unspecified_fields(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is False
    assert p.fav_price is True  # unchanged
    assert p.new_search_results is True


@pytest.mark.asyncio
async def test_idempotent_upsert(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    await prefs.set_prefs(db_user.id, fav_sold=True)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is True


@pytest.mark.asyncio
async def test_set_empty_partial_returns_current(db_user):
    p1 = await prefs.get_prefs(db_user.id)
    p2 = await prefs.set_prefs(db_user.id)
    assert p1 == p2
