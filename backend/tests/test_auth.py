"""Tests for auth cookie domain helper and post-login return_to handling (PLAN-034)."""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# _resolve_return_base — pure unit tests (no HTTP, no DB)
# ---------------------------------------------------------------------------


class TestResolveReturnBase:
    """Unit tests for the _resolve_return_base allowlist helper."""

    def test_returns_frontend_url_for_none(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _resolve_return_base

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        assert _resolve_return_base(None) == "http://localhost:4200"

    def test_returns_frontend_url_for_unknown_origin(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _resolve_return_base

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        assert _resolve_return_base("http://evil.example.com") == "http://localhost:4200"

    def test_returns_frontend_url_for_itself(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _resolve_return_base

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        assert _resolve_return_base("http://localhost:4200") == "http://localhost:4200"

    def test_returns_admin_url_when_matched(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _resolve_return_base

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        assert _resolve_return_base("http://localhost:4300") == "http://localhost:4300"

    def test_rejects_trailing_slash_variant(self, monkeypatch):
        """Exact-match allowlist: trailing slash must NOT match the registered origin."""
        from app.config import settings
        from app.api.auth import _resolve_return_base

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        # Neither origin has a trailing slash — the slash variant must fall back to FRONTEND_URL
        assert _resolve_return_base("http://localhost:4300/") == "http://localhost:4200"
        assert _resolve_return_base("http://localhost:4200/") == "http://localhost:4200"


# ---------------------------------------------------------------------------
# _cookie_domain_kwargs — pure unit tests
# ---------------------------------------------------------------------------


class TestCookieDomainKwargs:
    """Unit tests for _cookie_domain_kwargs helper."""

    def test_returns_empty_dict_when_cookie_domain_not_set(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _cookie_domain_kwargs

        monkeypatch.setattr(settings, "COOKIE_DOMAIN", "", raising=False)

        assert _cookie_domain_kwargs() == {}

    def test_returns_domain_kwarg_when_cookie_domain_set(self, monkeypatch):
        from app.config import settings
        from app.api.auth import _cookie_domain_kwargs

        monkeypatch.setattr(settings, "COOKIE_DOMAIN", ".rcn-scout.d2x-labs.de", raising=False)

        assert _cookie_domain_kwargs() == {"domain": ".rcn-scout.d2x-labs.de"}


# ---------------------------------------------------------------------------
# /auth/google endpoint — integration tests via ASGI transport
# ---------------------------------------------------------------------------


class TestAuthGoogleEndpoint:
    """HTTP-level tests for GET /api/auth/google."""

    @pytest.mark.asyncio
    async def test_auth_google_with_admin_return_to_sets_oauth_return_cookie(self, monkeypatch):
        """return_to matching ADMIN_URL stores that origin in oauth_return cookie."""
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/auth/google",
                params={"return_to": "http://localhost:4300"},
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        cookies = resp.cookies
        assert "oauth_return" in cookies
        # Cookie value is URL-encoded (quote(url, safe="")); unquote to compare the origin.
        assert unquote(cookies["oauth_return"]) == "http://localhost:4300"

    @pytest.mark.asyncio
    async def test_auth_google_with_unlisted_return_to_falls_back_to_frontend(self, monkeypatch):
        """An unlisted return_to value must fall back to FRONTEND_URL in oauth_return cookie."""
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:4200", raising=False)
        monkeypatch.setattr(settings, "ADMIN_URL", "http://localhost:4300", raising=False)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/auth/google",
                params={"return_to": "http://evil.example.com"},
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        cookies = resp.cookies
        assert "oauth_return" in cookies
        # Cookie value is URL-encoded (quote(url, safe="")); unquote to compare the origin.
        assert unquote(cookies["oauth_return"]) == "http://localhost:4200"
