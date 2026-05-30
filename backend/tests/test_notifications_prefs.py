"""Tests for app.notifications.prefs — notification preference upsert."""

import pytest

from app.notifications import prefs


@pytest.mark.asyncio
async def test_get_prefs_creates_default_row(db_user):
    p = await prefs.get_prefs(db_user.id)
    assert p.new_search_results is True
    assert p.fav_sold is True
    assert p.fav_price is True
    assert p.fav_deleted is True
    assert p.web_push_enabled is True


@pytest.mark.asyncio
async def test_set_prefs_partial_update(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is False
    assert p.fav_price is True  # untouched


@pytest.mark.asyncio
async def test_set_prefs_web_push_enabled_toggle(db_user):
    await prefs.set_prefs(db_user.id, web_push_enabled=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.web_push_enabled is False


@pytest.mark.asyncio
async def test_set_prefs_no_fields_is_noop(db_user):
    p = await prefs.set_prefs(db_user.id)  # nothing to write
    assert p.new_search_results is True
