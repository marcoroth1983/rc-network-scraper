"""Unit tests for ebay_client — OAuth token management + Browse API calls.

No live HTTP calls. All network interactions are mocked with AsyncMock/MagicMock.
Module-level globals _token and _token_expires_at are reset between tests to
ensure isolation.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.scraper.ebay_client as ebay_client_module
from app.scraper.ebay_client import _get_token, get_item, search_items


def _reset_token_globals() -> None:
    """Reset module-level token cache so tests do not bleed into each other."""
    ebay_client_module._token = ""
    ebay_client_module._token_expires_at = 0.0


def _make_token_response(token: str = "tok_test", expires_in: int = 7200) -> MagicMock:
    """Build a mock httpx response for the OAuth token endpoint."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"access_token": token, "expires_in": expires_in}
    return resp


# ---------------------------------------------------------------------------
# _get_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_cached() -> None:
    """Second call to _get_token() reuses the cached token without an HTTP call."""
    _reset_token_globals()

    oauth_resp = _make_token_response("cached_token")
    client = AsyncMock()
    client.post = AsyncMock(return_value=oauth_resp)

    with patch("app.scraper.ebay_client.settings") as mock_settings:
        mock_settings.ebay_client_id = "client_id"
        mock_settings.ebay_client_secret = "client_secret"

        first = await _get_token(client)
        second = await _get_token(client)

    assert first == "cached_token"
    assert second == "cached_token"
    # Only one HTTP call should have been made
    assert client.post.call_count == 1


@pytest.mark.asyncio
async def test_token_refresh_on_expiry() -> None:
    """Expired token triggers a new OAuth call."""
    _reset_token_globals()
    # Pre-set an expired token
    ebay_client_module._token = "old_token"
    ebay_client_module._token_expires_at = time.time() - 1  # already expired

    fresh_resp = _make_token_response("new_token")
    client = AsyncMock()
    client.post = AsyncMock(return_value=fresh_resp)

    with patch("app.scraper.ebay_client.settings") as mock_settings:
        mock_settings.ebay_client_id = "client_id"
        mock_settings.ebay_client_secret = "client_secret"

        token = await _get_token(client)

    assert token == "new_token"
    assert client.post.call_count == 1


# ---------------------------------------------------------------------------
# search_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_items_passes_correct_params() -> None:
    """search_items() sends conditionIds:{3000}, correct category_ids and offset."""
    _reset_token_globals()

    oauth_resp = _make_token_response("search_token")
    search_resp = MagicMock()
    search_resp.raise_for_status = MagicMock()
    search_resp.json.return_value = {"itemSummaries": []}

    client = AsyncMock()
    client.post = AsyncMock(return_value=oauth_resp)
    client.get = AsyncMock(return_value=search_resp)

    with patch("app.scraper.ebay_client.settings") as mock_settings:
        mock_settings.ebay_client_id = "client_id"
        mock_settings.ebay_client_secret = "client_secret"

        await search_items(client, category_id=29332, offset=200, limit=200)

    client.get.assert_called_once()
    _args, kwargs = client.get.call_args
    params = kwargs["params"]

    assert params["category_ids"] == "29332"
    assert params["filter"] == "conditionIds:{3000}"
    assert params["offset"] == "200"


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_item_404_returns_none() -> None:
    """get_item() returns None when the eBay API responds with 404."""
    _reset_token_globals()

    oauth_resp = _make_token_response("tok_404")
    not_found_resp = MagicMock()
    not_found_resp.status_code = 404

    client = AsyncMock()
    client.post = AsyncMock(return_value=oauth_resp)
    client.get = AsyncMock(return_value=not_found_resp)

    with patch("app.scraper.ebay_client.settings") as mock_settings:
        mock_settings.ebay_client_id = "client_id"
        mock_settings.ebay_client_secret = "client_secret"

        result = await get_item(client, "ebay_v1|123456789|0")

    assert result is None


@pytest.mark.asyncio
async def test_get_item_url_encodes_pipes() -> None:
    """get_item() URL-encodes pipe characters: v1|123|0 → v1%7C123%7C0."""
    _reset_token_globals()

    oauth_resp = _make_token_response("tok_encode")
    item_resp = MagicMock()
    item_resp.status_code = 200
    item_resp.raise_for_status = MagicMock()
    item_resp.json.return_value = {"itemId": "v1|123|0"}

    client = AsyncMock()
    client.post = AsyncMock(return_value=oauth_resp)
    client.get = AsyncMock(return_value=item_resp)

    with patch("app.scraper.ebay_client.settings") as mock_settings:
        mock_settings.ebay_client_id = "client_id"
        mock_settings.ebay_client_secret = "client_secret"

        await get_item(client, "ebay_v1|123|0")

    client.get.assert_called_once()
    called_url: str = client.get.call_args[0][0]
    assert "v1%7C123%7C0" in called_url
    assert "|" not in called_url


# ---------------------------------------------------------------------------
# run_ebay_fetch — no-op without credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_op_without_credentials() -> None:
    """run_ebay_fetch() returns zeros and makes no HTTP calls when ebay_client_id is empty."""
    from app.scraper.ebay_orchestrator import run_ebay_fetch

    with patch("app.scraper.ebay_orchestrator.settings") as mock_settings:
        mock_settings.ebay_client_id = ""

        result = await run_ebay_fetch()

    assert result == {"total_new": 0, "total_updated": 0, "total_skipped": 0}
