"""Overview page traversal — fetches thread links from rc-network.de listing pages."""

import asyncio
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = "rc-markt-scout/0.1 (personal hobby project)"
_THREAD_ID_RE = re.compile(r"/threads/[^/]+\.(\d+)/")


def _build_page_url(base_url: str, page: int) -> str:
    """Return the URL for a given page number.

    Page 1 uses the base URL directly; subsequent pages append /page-N.
    """
    base = base_url.rstrip("/")
    if page == 1:
        return base + "/"
    return f"{base}/page-{page}/"


def _extract_listings(html: str, base_url: str) -> list[dict]:
    """Parse overview page HTML and return a list of {external_id, url} dicts."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []

    for item in soup.select("div.structItem"):
        if "structItem--sticky" in item.get("class", []):
            continue
        # Each structItem should have a thread title link
        link_tag = item.select_one("div.structItem-title a[href*='/threads/']")
        if link_tag is None:
            continue

        href: str = link_tag.get("href", "")
        match = _THREAD_ID_RE.search(href)
        if match is None:
            logger.debug("Could not extract external_id from href: %s", href)
            continue

        external_id = match.group(1)

        # Build absolute URL if the href is relative
        if href.startswith("http"):
            url = href
        else:
            url = urljoin(base_url, href)

        results.append({"external_id": external_id, "url": url})

    return results


async def fetch_listings(
    start_url: str,
    max_pages: int,
    delay: float = 1.0,
) -> list[dict]:
    """Fetch overview pages and return all thread links found.

    Args:
        start_url: Base URL of the forum section (e.g. https://www.rc-network.de/forums/biete-flugmodelle.132/).
        max_pages: Maximum number of overview pages to fetch.
        delay: Seconds to wait between requests.

    Returns:
        List of dicts with keys ``external_id`` (str) and ``url`` (str).
        No deduplication or filtering is performed — that is the orchestrator's job.
    """
    headers = {"User-Agent": _USER_AGENT}
    listings: list[dict] = []

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            url = _build_page_url(start_url, page)
            logger.info("Fetching overview page %d: %s", page, url)

            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "HTTP error %s for %s — stopping pagination",
                    exc.response.status_code,
                    url,
                )
                break
            except httpx.RequestError as exc:
                logger.warning("Request error for %s: %s — stopping pagination", url, exc)
                break

            page_listings = _extract_listings(response.text, start_url)
            logger.info("Page %d: found %d listings", page, len(page_listings))

            if not page_listings:
                logger.info("Empty page at %d — stopping pagination", page)
                break

            listings.extend(page_listings)

            if page < max_pages:
                await asyncio.sleep(delay)

    return listings
