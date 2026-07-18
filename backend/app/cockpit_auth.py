"""Cockpit RS256 assertion verifier and FastAPI dependency (contract §8)."""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class JwksUnreachable(Exception):
    """Distinct from InvalidTokenError → maps to 503, never allow (fail-closed)."""


@dataclass
class CockpitOperator:
    google_id: str          # assertion `sub` — the immutable identity join key
    email: str              # display / audit only
    jti: str | None         # set on the cockpit path (for replay); None on the cookie path
    token_exp: float | None # for the jti cache TTL


# ---------------------------------------------------------------------------
# Hardened async JWKS fetcher (contract §8 #6)
# ASYNC httpx (never block the event loop — cycle-2 fix), 64 KB size cap,
# per-unknown-kid cooldown, asyncio.Lock.
# ---------------------------------------------------------------------------

_JWKS: dict = {"keys": [], "fetched": 0.0}
_UNKNOWN_KID_LAST: dict[str, float] = {}
_LOCK = asyncio.Lock()       # asyncio, NOT threading — this path is async
_MAX_JWKS_BYTES = 64 * 1024
_JWKS_TTL = 300              # cache lifespan (seconds)
_KID_COOLDOWN = 30           # min seconds between refetches triggered by the same unknown kid


async def _fetch_jwks() -> dict:
    """Fetch the JWKS from the configured URL. Raises JwksUnreachable on any error."""
    url = settings.COCKPIT_JWKS_URL
    if not url.startswith("https://"):
        raise JwksUnreachable("JWKS url must be https")
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:  # no cross-host redirects
            r = await c.get(url)
            r.raise_for_status()
            if len(r.content) > _MAX_JWKS_BYTES:                      # response-size cap
                raise JwksUnreachable("JWKS too large")
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise JwksUnreachable(str(e))


async def _get_key(kid: str):
    """Resolve a signing key from the cached/fresh JWKS by kid.

    Raises InvalidTokenError if the kid remains unknown after allowed refetches.
    Raises JwksUnreachable if the JWKS endpoint cannot be reached (fail-closed).
    """
    now = time.time()
    async with _LOCK:
        fresh = now - _JWKS["fetched"] < _JWKS_TTL
        have = any(k.get("kid") == kid for k in _JWKS["keys"])
        if not have and not fresh:
            _JWKS.update(keys=(await _fetch_jwks()).get("keys", []), fetched=now)
        elif not have and fresh:
            # Unknown kid on a fresh cache → allow ONE throttled refetch (anti refetch-storm/kid-spray).
            if now - _UNKNOWN_KID_LAST.get(kid, 0) >= _KID_COOLDOWN:
                _UNKNOWN_KID_LAST[kid] = now
                _JWKS.update(keys=(await _fetch_jwks()).get("keys", []), fetched=now)
        jwk = next((k for k in _JWKS["keys"] if k.get("kid") == kid), None)
    if jwk is None:
        raise InvalidTokenError("unknown kid")
    return jwt.PyJWK(jwk).key


# ---------------------------------------------------------------------------
# Token verifier — strict RS256 profile (contract §8 #3)
# ---------------------------------------------------------------------------


async def _verify(token: str) -> dict:
    """Verify a cockpit RS256 assertion. Raises InvalidTokenError or JwksUnreachable."""
    # Reject alg confusion + token-embedded keys: only RS256, key ONLY from our pinned JWKS (by kid).
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256" or "kid" not in header:
        raise InvalidTokenError("bad alg/kid")
    if any(k in header for k in ("jku", "x5u", "jwk", "x5c")):
        raise InvalidTokenError("embedded key header rejected")
    key = await _get_key(header["kid"])   # raises JwksUnreachable (→503) or InvalidTokenError (→401)
    claims = jwt.decode(
        token, key, algorithms=["RS256"],
        issuer=settings.COCKPIT_ISSUER, audience=settings.COCKPIT_AUDIENCE,
        leeway=settings.COCKPIT_CLOCK_SKEW_SECONDS,
        options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]},
    )
    now = time.time()
    if claims["exp"] - claims["iat"] > settings.COCKPIT_MAX_TOKEN_TTL_SECONDS:
        raise InvalidTokenError("ttl too long")
    if claims["iat"] > now + settings.COCKPIT_CLOCK_SKEW_SECONDS:
        raise InvalidTokenError("iat in future")
    if now - claims["iat"] > settings.COCKPIT_MAX_TOKEN_TTL_SECONDS + settings.COCKPIT_CLOCK_SKEW_SECONDS:
        raise InvalidTokenError("iat too old")
    if claims.get("role") != "admin":
        raise InvalidTokenError("not admin")
    return claims


# ---------------------------------------------------------------------------
# Plain helper (NOT a FastAPI dependency)
# Session passed explicitly so it composes without DI misuse.
# ---------------------------------------------------------------------------


async def verify_cockpit_bearer(request: Request, db: AsyncSession) -> CockpitOperator:
    """Verify the Bearer token in the request. JwksUnreachable / InvalidTokenError bubble to caller."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "cockpit assertion required")
    claims = await _verify(auth[7:])
    google_id = claims["sub"]
    return CockpitOperator(
        google_id=google_id,
        email=claims.get("email", ""),
        jti=claims["jti"],
        token_exp=float(claims["exp"]),
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def require_cockpit_admin(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CockpitOperator:
    """FastAPI dependency: verify cockpit RS256 assertion, map errors to HTTP status codes."""
    try:
        return await verify_cockpit_bearer(request, db)
    except JwksUnreachable:
        raise HTTPException(503, "cockpit key set unreachable")   # fail-closed, distinct from 401
    except InvalidTokenError:
        raise HTTPException(401, "invalid cockpit assertion")


# ---------------------------------------------------------------------------
# Single-use jti replay cache (contract §8 #4)
# In-process, single replica. If rcn-scraper ever runs multiple replicas,
# move to a shared store (Redis). Note filed in contract §8.
# ---------------------------------------------------------------------------

# {jti: exp_timestamp} — lazily pruned on each consume_jti call
_JTI_CACHE: dict[str, float] = {}


def _prune_jti_cache() -> None:
    """Remove entries whose token has already expired."""
    now = time.time()
    expired = [k for k, v in _JTI_CACHE.items() if v < now]
    for k in expired:
        del _JTI_CACHE[k]


def consume_jti(jti: str, exp: float) -> bool:
    """Record a jti as seen. Returns True if new (ok to proceed), False if replay (reject)."""
    _prune_jti_cache()
    if jti in _JTI_CACHE:
        return False
    _JTI_CACHE[jti] = exp
    return True


def _clear_jti_cache() -> None:
    """Clear the jti replay cache. Used in tests for isolation."""
    _JTI_CACHE.clear()
