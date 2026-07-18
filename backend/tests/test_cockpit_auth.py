"""Unit tests for the cockpit RS256 assertion verifier (cockpit_auth.py).

Tokens are minted with a test RSA keypair. _get_key / _fetch_jwks are
monkeypatched so no real JWKS endpoint is required.
"""

from __future__ import annotations

import time
import pytest

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import InvalidTokenError
import jwt

import app.cockpit_auth as _mod
from app.cockpit_auth import (
    JwksUnreachable,
    CockpitOperator,
    _verify,
    _fetch_jwks,
    consume_jti,
    _clear_jti_cache,
    verify_cockpit_bearer,
)

# ---------------------------------------------------------------------------
# Test RSA keypair — generated once per module
# ---------------------------------------------------------------------------

_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()
_TEST_KID = "test-kid-1"


def _mint(
    *,
    sub: str = "google-sub-123",
    email: str = "op@example.com",
    role: str = "admin",
    iss: str = "d2x-cockpit",
    aud: str | list[str] = "rcn-scraper-admin",
    exp_offset: int = 299,   # seconds from now
    iat_offset: int = 0,
    jti: str = "jti-test-1",
    extra_headers: dict | None = None,
    algorithm: str = "RS256",
    key=None,
) -> str:
    """Mint a JWT for testing."""
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "exp": now + exp_offset,
        "iat": now + iat_offset,
        "nbf": now - 1,
        "jti": jti,
        "role": role,
        "email": email,
    }
    headers: dict = {"kid": _TEST_KID}
    if extra_headers:
        headers.update(extra_headers)
    signing_key = key if key is not None else _TEST_PRIVATE_KEY
    return jwt.encode(payload, signing_key, algorithm=algorithm, headers=headers)


@pytest.fixture(autouse=True)
def reset_jti_cache():
    _clear_jti_cache()
    yield
    _clear_jti_cache()


@pytest.fixture()
def mock_get_key(monkeypatch):
    """Patch _get_key to return the test public key."""
    async def _fake_get_key(kid: str):
        if kid != _TEST_KID:
            raise InvalidTokenError("unknown kid")
        return _TEST_PUBLIC_KEY

    monkeypatch.setattr(_mod, "_get_key", _fake_get_key)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_token_verify_returns_claims(mock_get_key):
    """A valid RS256 token with all required claims passes _verify."""
    token = _mint()
    claims = await _verify(token)
    assert claims["sub"] == "google-sub-123"
    assert claims["jti"] == "jti-test-1"
    assert claims["role"] == "admin"


@pytest.mark.asyncio
async def test_valid_token_verify_cockpit_bearer_returns_operator(mock_get_key):
    """verify_cockpit_bearer extracts google_id and jti into a CockpitOperator."""
    from fastapi import Request

    token = _mint()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
    }
    request = Request(scope)
    operator = await verify_cockpit_bearer(request)
    assert isinstance(operator, CockpitOperator)
    assert operator.google_id == "google-sub-123"
    assert operator.jti == "jti-test-1"
    assert operator.email == "op@example.com"
    assert operator.token_exp is not None


# ---------------------------------------------------------------------------
# Algorithm / header rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alg_none_rejected():
    """alg:none tokens are rejected before any key lookup."""
    # jwt.encode with algorithm=None produces unsigned token, but PyJWT may not
    # allow it directly. Craft the header manually via decode of an existing token.
    # Simplest: encode a regular token then override the alg claim in the header.
    # Instead, we test that a token with alg="none" in get_unverified_header fails.
    # We can build such a token using the low-level API.
    import base64
    import json

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64url(json.dumps({"alg": "none", "kid": _TEST_KID}).encode())
    payload_raw = _b64url(json.dumps({"sub": "x"}).encode())
    # alg:none has empty signature
    token = f"{header}.{payload_raw}."
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_hs256_rejected():
    """HS256 token (no 'kid' header) is rejected at the alg/kid check."""
    import hmac
    import hashlib
    import base64
    import json

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    # Craft minimal HS256 token without kid
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_raw = _b64url(json.dumps({"sub": "x", "iss": "d2x-cockpit"}).encode())
    msg = f"{header}.{payload_raw}".encode()
    sig = _b64url(hmac.new(b"secret", msg, hashlib.sha256).digest())
    token = f"{header}.{payload_raw}.{sig}"
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_embedded_jku_rejected():
    """Token with 'jku' in the header is rejected (key injection prevention)."""
    token = _mint(extra_headers={"jku": "https://evil.example/jwks"})
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_embedded_x5u_rejected():
    """Token with 'x5u' in the header is rejected."""
    token = _mint(extra_headers={"x5u": "https://evil.example/cert"})
    with pytest.raises(InvalidTokenError):
        await _verify(token)


# ---------------------------------------------------------------------------
# Claim / TTL checks (all require mock_get_key so signature verifies)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_rejected(mock_get_key):
    """Expired token (exp in the past, beyond clock skew) is rejected."""
    token = _mint(exp_offset=-120, iat_offset=-420)  # expired 2 min ago, iat 7 min ago
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_exp_iat_too_long_rejected(mock_get_key):
    """Token with exp - iat > COCKPIT_MAX_TOKEN_TTL_SECONDS is rejected."""
    # Default max is 300s; mint with 400s window
    token = _mint(exp_offset=400, iat_offset=0)
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_future_iat_rejected(mock_get_key):
    """Token with iat in the future (beyond skew) is rejected."""
    token = _mint(iat_offset=200)  # iat 200s in the future (skew is 60s)
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_wrong_iss_rejected(mock_get_key):
    """Token with wrong issuer is rejected."""
    token = _mint(iss="wrong-issuer")
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_wrong_aud_rejected(mock_get_key):
    """Token with wrong audience is rejected."""
    token = _mint(aud="wrong-audience")
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_not_admin_role_rejected(mock_get_key):
    """Token without role='admin' is rejected."""
    token = _mint(role="member")
    with pytest.raises(InvalidTokenError):
        await _verify(token)


# ---------------------------------------------------------------------------
# JWKS infrastructure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_kid_raises_invalid_token_error(monkeypatch):
    """Token with an unknown kid raises InvalidTokenError (→ 401 at the dependency)."""
    async def _missing_key(kid: str):
        raise InvalidTokenError("unknown kid")

    monkeypatch.setattr(_mod, "_get_key", _missing_key)
    token = _mint()
    with pytest.raises(InvalidTokenError):
        await _verify(token)


@pytest.mark.asyncio
async def test_jwks_unreachable_raises(monkeypatch):
    """When JWKS is unreachable, _get_key raises JwksUnreachable (maps to 503)."""
    async def _unreachable(kid: str):
        raise JwksUnreachable("endpoint down")

    monkeypatch.setattr(_mod, "_get_key", _unreachable)
    token = _mint()
    with pytest.raises(JwksUnreachable):
        await _verify(token)


@pytest.mark.asyncio
async def test_oversized_jwks_rejected(monkeypatch):
    """_fetch_jwks raises JwksUnreachable when response exceeds the size cap."""
    import httpx as _httpx

    class _FakeResponse:
        content = b"x" * (_mod._MAX_JWKS_BYTES + 1)
        status_code = 200
        headers: dict = {}  # no Content-Length → Content-Length check skipped, backstop fires

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {}

    class _FakeClient:
        def __init__(self, **kwargs): pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url: str) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(_httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(_mod.settings, "COCKPIT_JWKS_URL", "https://example.com/jwks")
    with pytest.raises(JwksUnreachable, match="too large"):
        await _fetch_jwks()


# ---------------------------------------------------------------------------
# jti replay cache
# ---------------------------------------------------------------------------

def test_consume_jti_returns_true_once_then_false_on_replay():
    """consume_jti records a jti and rejects it on replay."""
    exp = time.time() + 300
    assert consume_jti("replay-jti", exp) is True   # first use: ok
    assert consume_jti("replay-jti", exp) is False  # replay: rejected


def test_consume_jti_two_distinct_jtis_both_accepted():
    """Two different jtis are each accepted on first use."""
    exp = time.time() + 300
    assert consume_jti("jti-a", exp) is True
    assert consume_jti("jti-b", exp) is True


def test_consume_jti_expired_entry_pruned_and_reaccepted():
    """An expired jti is pruned and may be reused (window elapsed)."""
    exp_past = time.time() - 1   # already expired
    # First: record it (it won't be pruned yet — nothing in cache)
    assert consume_jti("old-jti", exp_past) is True
    # Second call: the entry has exp < now, so it's pruned first, then re-accepted
    assert consume_jti("old-jti", time.time() + 300) is True


# ---------------------------------------------------------------------------
# H1 — kid-spray: bounded dict + global fetch throttle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kid_spray_bounded_dict_and_global_fetch_throttle(monkeypatch):
    """H1: _UNKNOWN_KID_LAST stays bounded AND global throttle limits fetch count.

    Two sub-scenarios:
    1. Burst: 200 distinct kids at one instant → global throttle allows at most 1 fetch.
    2. Sustained: manually reset global throttle between each kid (simulating time passing)
       → dict stays at or below _MAX_UNKNOWN_KID_ENTRIES despite 200 fetches.
    """
    fetch_count = 0

    async def _fake_fetch() -> dict:
        nonlocal fetch_count
        fetch_count += 1
        return {"keys": []}  # no valid keys — all kids remain unknown

    monkeypatch.setattr(_mod, "_fetch_jwks", _fake_fetch)

    # --- Part 1: rapid burst -----------------------------------------------
    # Fresh cache so we enter the unknown-kid branch, global throttle at 0.0 (allows first fetch).
    _mod._UNKNOWN_KID_LAST.clear()
    _mod._LAST_UNKNOWN_FETCH = 0.0
    _mod._JWKS.update(keys=[], fetched=time.time())

    for i in range(200):
        with pytest.raises(InvalidTokenError):
            await _mod._get_key(f"burst-kid-{i}")

    assert fetch_count <= 1, (
        f"global throttle failed on burst: {fetch_count} fetches for 200-kid spray"
    )

    # --- Part 2: sustained spray (simulate time passing via manual reset) ---
    # Reset to allow each kid its own fetch; verify the dict stays bounded.
    fetch_count = 0
    _mod._UNKNOWN_KID_LAST.clear()
    _mod._LAST_UNKNOWN_FETCH = 0.0
    _mod._JWKS.update(keys=[], fetched=time.time())

    for i in range(200):
        # Simulate global cooldown elapsed by manually resetting _LAST_UNKNOWN_FETCH
        _mod._LAST_UNKNOWN_FETCH = 0.0
        with pytest.raises(InvalidTokenError):
            await _mod._get_key(f"sustained-kid-{i}")

    assert len(_mod._UNKNOWN_KID_LAST) <= _mod._MAX_UNKNOWN_KID_ENTRIES, (
        f"kid dict unbounded: {len(_mod._UNKNOWN_KID_LAST)} entries after 200 fetches"
    )
    assert fetch_count == 200, f"expected exactly 200 fetches in sustained scenario, got {fetch_count}"
