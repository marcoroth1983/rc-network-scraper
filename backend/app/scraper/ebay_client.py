import asyncio
import base64
import logging
import time
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1"
EBAY_MARKETPLACE = "EBAY_DE"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

_token: str = ""
_token_expires_at: float = 0.0
_token_lock = asyncio.Lock()


async def _get_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at
    async with _token_lock:
        if _token and time.time() < _token_expires_at - 300:
            return _token
        credentials = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
        ).decode()
        try:
            resp = await client.post(
                EBAY_OAUTH_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
                timeout=10,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("eBay OAuth token request failed: status=%d", exc.response.status_code)
            raise
        data = resp.json()
        _token = data["access_token"]
        _token_expires_at = time.time() + data["expires_in"]
        return _token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
        "Accept-Language": "de-DE",
    }


async def search_items(
    client: httpx.AsyncClient,
    category_id: int,
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """Search eBay listings. Returns raw API response dict."""
    token = await _get_token(client)
    resp = await client.get(
        f"{EBAY_BROWSE_URL}/item_summary/search",
        headers=_headers(token),
        params={
            "category_ids": str(category_id),
            "filter": "conditionIds:{3000}",  # Used items only
            "sort": "newlyListed",
            "limit": str(limit),
            "offset": str(offset),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


async def get_item(client: httpx.AsyncClient, external_id: str) -> dict | None:
    """
    Fetch a single item for sold-recheck.
    external_id is our internal "ebay_v1|123|0" format.
    Returns None on 404 (sold/removed).
    """
    if not external_id.startswith("ebay_"):
        raise ValueError(f"get_item() called with non-eBay external_id: {external_id!r}")
    raw_id = external_id[len("ebay_"):]
    encoded_id = quote(raw_id, safe="")  # encode pipes: v1%7C123%7C0
    resp = await client.get(
        f"{EBAY_BROWSE_URL}/item/{encoded_id}",
        headers=_headers(await _get_token(client)),
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
