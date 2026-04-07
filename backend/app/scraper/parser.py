"""Detail page extraction — pure function, no I/O."""

import copy
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

_PLZ_RE = re.compile(r"^\d{5}$")

_SOLD_RE = re.compile(r"\bverkauft\b|\bsold\b|\bvergeben\b", re.IGNORECASE)

# Labels used in XenForo's structured "pairs" block (without trailing colon)
_LABEL_PRICE = "Preis"
_LABEL_CONDITION = "Zustand"
_LABEL_SHIPPING = "Versandart/-kosten"
_LABEL_LOCATION = "Artikelstandort"


def _first_post(soup: BeautifulSoup) -> Tag | None:
    """Return the first article.message--post element, or None."""
    return soup.select_one("article.message--post")


def _extract_title(soup: BeautifulSoup) -> str | None:
    """Extract thread title from the page <title> or h1."""
    # XenForo puts the thread title in <h1 class="p-title-value"> or the page <title>
    h1 = soup.select_one("h1.p-title-value")
    if h1:
        return h1.get_text(strip=True) or None

    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        # XenForo appends " | Forum name" — strip everything after the last pipe
        if "|" in raw:
            raw = raw.rsplit("|", 1)[0].strip()
        return raw or None

    return None


def _extract_pairs(post: Tag) -> dict[str, str]:
    """Extract label→value pairs from the structured info block in the first post.

    XenForo listings use a definition-list style layout:
      <dl class="pairs ...">
        <dt>Label:</dt>
        <dd>Value</dd>
      </dl>
    or alternatively a table with <th> / <td> cells.
    """
    pairs: dict[str, str] = {}

    # Try dl.pairs first (most common XenForo pattern)
    for dl in post.select("dl.pairs"):
        dt = dl.select_one("dt")
        dd = dl.select_one("dd")
        if dt and dd:
            label = dt.get_text(strip=True)
            value = dd.get_text(strip=True)
            if label:
                pairs[label] = value

    # Fallback: table rows with th + td
    if not pairs:
        for row in post.select("tr"):
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                label = th.get_text(strip=True)
                value = td.get_text(strip=True)
                if label:
                    pairs[label] = value

    return pairs


def _parse_location(raw: str | None) -> tuple[str | None, str | None]:
    """Split a location string into (plz, city).

    Handles these formats (comma-separated and space-separated):
    - "80331, München"  → ("80331", "München")
    - "80331 München"   → ("80331", "München")
    - "80331"           → ("80331", None)
    - "München"         → (None, "München")
    - "CH 3000 Bern"    → (None, "CH 3000 Bern")   non-German format
    """
    if not raw:
        return None, None

    raw = raw.strip()

    # Try comma-separated first: "PLZ, City"
    if "," in raw:
        plz_part, _, city_part = raw.partition(",")
        plz_candidate = plz_part.strip()
        city_candidate = city_part.strip()
        if _PLZ_RE.match(plz_candidate):
            return plz_candidate, city_candidate or None
        # Comma but no valid PLZ — keep full string as city
        return None, raw or None

    # Try space-separated: "PLZ City" where first token is exactly 5 digits
    first, _, rest = raw.partition(" ")
    if _PLZ_RE.match(first):
        return first, rest.strip() or None

    # Just a city name (or non-German PLZ format)
    return None, raw or None


def _parse_datetime(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string to a timezone-aware datetime.

    Returns None if parsing fails.
    """
    if not raw:
        return None
    try:
        dt = dateutil_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return None


def _extract_posted_at(post: Tag) -> tuple[datetime | None, str | None]:
    """Return (posted_at, posted_at_raw) from the first <time> tag in the post header."""
    # XenForo posts have <time class="u-dt" datetime="2024-01-15T10:30:00+0100">
    time_tag = post.select_one("time[datetime]")
    if time_tag is None:
        return None, None

    raw: str = time_tag.get("datetime", "").strip()
    if not raw:
        return None, None

    return _parse_datetime(raw), raw


def _extract_author(post: Tag) -> str | None:
    """Extract the poster's username from the post element."""
    # data-author attribute on the article element is the most reliable
    author = post.get("data-author", "").strip()
    if author:
        return author

    # Fallback: h4.message-name or .username link
    name_tag = post.select_one("h4.message-name .username") or post.select_one(".message-name")
    if name_tag:
        return name_tag.get_text(strip=True) or None

    return None


def _extract_description(post: Tag, pairs: dict[str, str]) -> str:
    """Extract the post body text, removing the structured pairs block.

    Strategy: take the message-body / bbWrapper text, then strip out lines
    that match any of the known label values so the description is clean.
    """
    body = post.select_one(".bbWrapper") or post.select_one(".message-body")
    if body is None:
        return ""

    # Remove the pairs container from the DOM clone so its text doesn't appear
    body_copy = copy.deepcopy(body)
    for dl in body_copy.select("dl.pairs"):
        dl.decompose()
    for table in body_copy.select("table"):
        # Only remove tables that look like the pairs table (contain known labels)
        th_texts = {th.get_text(strip=True) for th in table.select("th")}
        known_labels = {_LABEL_PRICE, _LABEL_CONDITION, _LABEL_SHIPPING, _LABEL_LOCATION}
        if th_texts & known_labels:
            table.decompose()

    text = body_copy.get_text(separator="\n", strip=True)
    return text


def _extract_images(post: Tag, page_url: str = "") -> list[str]:
    """Collect absolute image URLs from attachment blocks within the post."""
    urls: list[str] = []

    # XenForo attachment thumbnails / full images
    for img in post.select(".attachment img[src], .attachmentList img[src]"):
        src: str = img.get("src", "").strip()
        if src:
            urls.append(urljoin(page_url, src) if page_url else src)

    # Also pick up inline images inside bbWrapper that are not smilies
    for img in post.select(".bbWrapper img[src]"):
        src = img.get("src", "").strip()
        resolved = urljoin(page_url, src) if page_url else src
        if src and resolved not in urls and "smilie" not in src.lower():
            urls.append(resolved)

    return urls


def _extract_tags(soup: BeautifulSoup) -> list[str]:
    """Extract thread tags from the js-tagList span (outside the first post)."""
    return [
        a.get_text(strip=True)
        for a in soup.select("span.js-tagList a.tagItem")
        if a.get_text(strip=True)
    ]


def _detect_sold(soup: BeautifulSoup) -> bool:
    """Return True if the thread title or any reply indicates the item is sold."""
    title = _extract_title(soup) or ""
    if _SOLD_RE.search(title):
        return True
    # Scan reply posts (all posts after the first)
    posts = soup.select("article.message--post")
    for reply in posts[1:]:
        wrapper = reply.select_one(".bbWrapper")
        if wrapper and _SOLD_RE.search(wrapper.get_text()):
            return True
    return False


def parse_detail(html: str, page_url: str = "") -> dict:
    """Parse a XenForo detail/thread page and return structured listing data.

    Returns a dict with keys:
        title, price, condition, shipping, plz, city,
        description, images, author, posted_at, posted_at_raw, is_sold
    """
    soup = BeautifulSoup(html, "lxml")

    post = _first_post(soup)
    if post is None:
        logger.warning("parse_detail: no article.message--post found in HTML")
        return {
            "title": _extract_title(soup),
            "price": None,
            "condition": None,
            "shipping": None,
            "plz": None,
            "city": None,
            "description": "",
            "images": [],
            "tags": _extract_tags(soup),
            "author": None,
            "posted_at": None,
            "posted_at_raw": None,
            "is_sold": _detect_sold(soup),
        }

    pairs = _extract_pairs(post)

    price: str | None = pairs.get(_LABEL_PRICE) or None
    condition: str | None = pairs.get(_LABEL_CONDITION) or None
    shipping: str | None = pairs.get(_LABEL_SHIPPING) or None

    raw_location: str | None = pairs.get(_LABEL_LOCATION) or None
    plz, city = _parse_location(raw_location)

    posted_at, posted_at_raw = _extract_posted_at(post)

    return {
        "title": _extract_title(soup),
        "price": price,
        "condition": condition,
        "shipping": shipping,
        "plz": plz,
        "city": city,
        "description": _extract_description(post, pairs),
        "images": _extract_images(post, page_url),
        "tags": _extract_tags(soup),
        "author": _extract_author(post),
        "posted_at": posted_at,
        "posted_at_raw": posted_at_raw,
        "is_sold": _detect_sold(soup),
    }
