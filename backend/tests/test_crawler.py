"""Tests for the overview page crawler."""

from pathlib import Path

from app.scraper.crawler import _extract_listings

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.rc-network.de/forums/biete-flugmodelle.132/"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestExtractListings:
    def test_extract_listings_from_overview(self) -> None:
        """Parses all structItem thread links from the overview fixture."""
        html = _load("overview_page.html")
        results = _extract_listings(html, BASE_URL)

        assert len(results) >= 1
        for item in results:
            assert "external_id" in item
            assert "url" in item
            # external_id must be a non-empty numeric string
            assert item["external_id"].isdigit()
            # URL must contain the /threads/ path segment
            assert "/threads/" in item["url"]

    def test_all_five_listings_extracted(self) -> None:
        """The overview fixture contains exactly 5 structItem entries."""
        html = _load("overview_page.html")
        results = _extract_listings(html, BASE_URL)
        assert len(results) == 5

    def test_external_id_parsing(self) -> None:
        """Numeric IDs are correctly extracted from thread URLs."""
        html = _load("overview_page.html")
        results = _extract_listings(html, BASE_URL)

        ids = {item["external_id"] for item in results}
        assert "12345" in ids
        assert "67890" in ids
        assert "11111" in ids

    def test_url_is_absolute(self) -> None:
        """Relative hrefs are resolved to absolute URLs."""
        html = _load("overview_page.html")
        results = _extract_listings(html, BASE_URL)

        for item in results:
            assert item["url"].startswith("http")

    def test_empty_page_returns_empty_list(self) -> None:
        """An HTML page with no structItem elements returns an empty list."""
        html = "<html><body><div class='nothing'></div></body></html>"
        results = _extract_listings(html, BASE_URL)
        assert results == []

    def test_extract_listings_skips_sticky_items(self) -> None:
        """Sticky/notice threads (structItem--sticky) must be excluded from results."""
        html = """
        <html><body>
          <div class="structItem structItem--sticky structItem--thread">
            <div class="structItem-title">
              <a href="/threads/hinweis.123/">Ergänzende Hinweise</a>
            </div>
          </div>
          <div class="structItem structItem--thread">
            <div class="structItem-title">
              <a href="/threads/verkaufe-flieger.456/">Verkaufe Flieger</a>
            </div>
          </div>
        </body></html>
        """
        results = _extract_listings(html, BASE_URL)
        assert len(results) == 1
        assert results[0]["external_id"] == "456"
