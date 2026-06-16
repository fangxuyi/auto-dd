"""Unit tests for WebSearchAdapter, IRPageAdapter, and ProductPageAdapter."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from company_research.models.identity import CompanyIdentity
from company_research.models.sources import RawDocument, SourceRecord


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def company() -> CompanyIdentity:
    return CompanyIdentity(
        symbol="AAPL",
        exchange="NASDAQ",
        issuer_name="Apple Inc.",
        cik="0000320193",
        fiscal_year_end="09-30",
        currency="USD",
        ir_url="https://investor.apple.com",
        filing_jurisdiction="US",
    )


@pytest.fixture()
def mock_cache() -> MagicMock:
    cache = MagicMock()
    raw_doc = MagicMock(spec=RawDocument)
    raw_doc.content_hash = "abc123"
    cache.store_bytes.return_value = raw_doc
    cache.read.return_value = b"<html><body>content</body></html>"
    return cache


_FAKE_DDG_HTML = b"""
<html><body>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.reuters.com%2Fapple-review&rut=x">Apple review on Reuters</a>
<div class="result__snippet">Apple Inc faces tough competition from Samsung.</div>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.bloomberg.com%2Fapple-analysis&rut=x">Apple analysis on Bloomberg</a>
<div class="result__snippet">An analyst note on Apple.</div>
</body></html>
"""

_FAKE_IR_HTML = b"""
<html><body>
<a href="/press-release/2024-earnings">Q4 2024 Earnings Press Release</a>
<a href="/investor/annual-report-2024">Annual Report 2024</a>
<a href="/investor/presentation-q4-2024">Q4 Investor Presentation</a>
<a href="https://external.com/other">External Link</a>
</body></html>
"""

_FAKE_PRODUCT_HTML = b"""
<html><body>
<a href="/products/iphone">iPhone Products</a>
<a href="/pricing">Pricing Plans</a>
<a href="/solutions/enterprise">Enterprise Solutions</a>
<a href="/about">About Us</a>
</body></html>
"""


# ── WebSearchAdapter ───────────────────────────────────────────────────────────

class TestWebSearchAdapter:

    def test_search_returns_source_records(self, company, mock_cache):
        from company_research.sources.web_search import WebSearchAdapter

        with patch("httpx.post") as mock_post:
            resp = MagicMock()
            resp.content = _FAKE_DDG_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            adapter = WebSearchAdapter(cache=mock_cache, max_results=2)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert len(sources) > 0
        for src in sources:
            assert isinstance(src, SourceRecord)
            assert src.source_type == "web_search"
            assert src.company_or_external == "external"
            assert src.reliability_tier >= 4

    def test_search_deduplicates_urls(self, company, mock_cache):
        from company_research.sources.web_search import WebSearchAdapter

        duplicate_html = _FAKE_DDG_HTML  # same HTML for all 3 queries

        with patch("httpx.post") as mock_post:
            resp = MagicMock()
            resp.content = duplicate_html
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            adapter = WebSearchAdapter(cache=mock_cache, max_results=5)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        urls = [s.url for s in sources]
        assert len(urls) == len(set(urls)), "Duplicate URLs returned"

    def test_search_graceful_failure(self, company, mock_cache):
        from company_research.sources.web_search import WebSearchAdapter

        with patch("httpx.post", side_effect=Exception("network error")):
            adapter = WebSearchAdapter(cache=mock_cache, max_results=3)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert sources == []

    def test_reliability_tier_assignment(self):
        from company_research.sources.web_search import _reliability_tier

        assert _reliability_tier("https://www.bloomberg.com/article") == 4
        assert _reliability_tier("https://www.reuters.com/news") == 4
        assert _reliability_tier("https://seekingalpha.com/article") == 5
        assert _reliability_tier("https://www.randomsite.com/article") == 6
        assert _reliability_tier("https://www.sec.gov/cgi-bin/browse") == 4

    def test_fetch_stores_in_cache(self, mock_cache):
        from company_research.sources.web_search import WebSearchAdapter

        source = SourceRecord(
            title="Test",
            publisher="reuters.com",
            url="https://www.reuters.com/test",
            source_type="web_search",
            primary_or_secondary="secondary",
            company_or_external="external",
            reliability_tier=4,
        )
        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = b"<html>content</html>"
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = WebSearchAdapter(cache=mock_cache, max_results=3)
            raw_doc = adapter.fetch(source)

        mock_cache.store_bytes.assert_called_once()
        assert raw_doc is not None

    def test_fetch_returns_empty_on_http_error(self, mock_cache):
        from company_research.sources.web_search import WebSearchAdapter

        source = SourceRecord(
            title="Test",
            publisher="example.com",
            url="https://www.example.com/404",
            source_type="web_search",
            primary_or_secondary="secondary",
            company_or_external="external",
            reliability_tier=6,
        )
        with patch("httpx.get", side_effect=Exception("404")), patch("time.sleep"):
            adapter = WebSearchAdapter(cache=mock_cache, max_results=3)
            raw_doc = adapter.fetch(source)

        # Should still call store_bytes with empty bytes
        mock_cache.store_bytes.assert_called_once()
        args = mock_cache.store_bytes.call_args[0]
        assert args[0] == b""


# ── IRPageAdapter ──────────────────────────────────────────────────────────────

class TestIRPageAdapter:

    def test_search_returns_root_plus_sub_links(self, company, mock_cache):
        from company_research.sources.ir_page import IRPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_IR_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = IRPageAdapter(cache=mock_cache, max_pages=5)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert len(sources) >= 1
        root = sources[0]
        assert root.url == "https://investor.apple.com"
        assert root.source_type == "ir_page"
        assert root.reliability_tier == 5
        assert root.company_or_external == "company"

    def test_search_returns_empty_when_no_ir_url(self, mock_cache):
        from company_research.sources.ir_page import IRPageAdapter

        no_ir = CompanyIdentity(
            symbol="NURL",
            exchange="NYSE",
            issuer_name="No IR Corp",
            cik="0000000001",
            fiscal_year_end="12-31",
            currency="USD",
            filing_jurisdiction="US",
        )
        adapter = IRPageAdapter(cache=mock_cache, max_pages=3)
        sources = adapter.search(no_ir, cutoff=date(2026, 6, 15))

        assert sources == []

    def test_search_respects_max_pages(self, company, mock_cache):
        from company_research.sources.ir_page import IRPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_IR_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = IRPageAdapter(cache=mock_cache, max_pages=2)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert len(sources) <= 2

    def test_search_graceful_on_fetch_failure(self, company, mock_cache):
        from company_research.sources.ir_page import IRPageAdapter

        with patch("httpx.get", side_effect=Exception("timeout")):
            adapter = IRPageAdapter(cache=mock_cache, max_pages=3)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        # Root source is always added; sub-link discovery just skipped
        assert len(sources) == 1
        assert sources[0].url == "https://investor.apple.com"

    def test_classify_source_types(self):
        from company_research.sources.ir_page import _classify_source_type

        assert _classify_source_type("/press-release/q4", "Q4 Press Release") == "press_release"
        assert _classify_source_type("/earnings/2024", "Earnings") == "earnings_release"
        assert _classify_source_type("/investor/presentation", "Presentation") == "investor_presentation"
        assert _classify_source_type("/investor/landing", "Investor") == "ir_page"


# ── ProductPageAdapter ─────────────────────────────────────────────────────────

class TestProductPageAdapter:

    def test_search_discovers_product_links(self, company, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_PRODUCT_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = ProductPageAdapter(cache=mock_cache, max_pages=5)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert len(sources) > 0
        types = {s.source_type for s in sources}
        assert types <= {"product_page", "pricing_page"}

    def test_search_prioritises_pricing_pages(self, company, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_PRODUCT_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = ProductPageAdapter(cache=mock_cache, max_pages=5)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        if any(s.source_type == "pricing_page" for s in sources):
            # Pricing pages should appear before product pages
            first_pricing = next(i for i, s in enumerate(sources) if s.source_type == "pricing_page")
            first_product = next(
                (i for i, s in enumerate(sources) if s.source_type == "product_page"), None
            )
            if first_product is not None:
                assert first_pricing <= first_product

    def test_search_returns_empty_when_no_ir_url(self, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        no_ir = CompanyIdentity(
            symbol="NURL",
            exchange="NYSE",
            issuer_name="No IR Corp",
            cik="0000000001",
            fiscal_year_end="12-31",
            currency="USD",
            filing_jurisdiction="US",
        )
        adapter = ProductPageAdapter(cache=mock_cache, max_pages=3)
        sources = adapter.search(no_ir, cutoff=date(2026, 6, 15))
        assert sources == []

    def test_search_respects_max_pages(self, company, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_PRODUCT_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = ProductPageAdapter(cache=mock_cache, max_pages=1)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert len(sources) <= 1

    def test_search_assigns_tier_2(self, company, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        with patch("httpx.get") as mock_get, patch("time.sleep"):
            resp = MagicMock()
            resp.content = _FAKE_PRODUCT_HTML
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp

            adapter = ProductPageAdapter(cache=mock_cache, max_pages=5)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        for src in sources:
            assert src.reliability_tier == 2

    def test_search_graceful_on_fetch_failure(self, company, mock_cache):
        from company_research.sources.product_page import ProductPageAdapter

        with patch("httpx.get", side_effect=Exception("connection refused")):
            adapter = ProductPageAdapter(cache=mock_cache, max_pages=3)
            sources = adapter.search(company, cutoff=date(2026, 6, 15))

        assert sources == []
