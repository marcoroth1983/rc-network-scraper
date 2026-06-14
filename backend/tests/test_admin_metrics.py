"""Tests for admin metrics endpoints (PLAN-033)."""

import pytest


@pytest.mark.asyncio
async def test_metrics_summary_counts(admin_client, db_session):
    client, _ = admin_client
    resp = await client.get("/api/admin/metrics/summary")
    assert resp.status_code == 200
    body = resp.json()
    # admin_client seeds exactly one approved admin user
    assert body["users_total"] >= 1
    assert body["users_approved"] >= 1
    assert set(body) >= {"users_pending", "users_active_7d", "users_active_30d",
                         "listings_total", "favorites_total", "saved_searches_total"}


@pytest.mark.asyncio
async def test_metrics_timeseries_zero_filled_and_clamped(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/metrics/timeseries?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["logins"]) == 7          # zero-filled continuous window
    assert len(body["listings_new"]) == 7


@pytest.mark.asyncio
async def test_metrics_requires_admin(authenticated_client):
    client = authenticated_client          # role=member
    resp = await client.get("/api/admin/metrics/summary")
    assert resp.status_code == 403
