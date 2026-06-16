"""Unit tests for PeerSelector."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from company_research.models.identity import CompanyIdentity
from company_research.models.sources import SourceRecord


@pytest.fixture()
def apple() -> CompanyIdentity:
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
    return MagicMock()


_DDG_SNIPPETS_HTML = b"""
<html><body>
<a class="result__a" href="#">Apple's main competitors are Microsoft and Samsung</a>
<div class="result__snippet">Microsoft Corp and Samsung Electronics are frequently compared to Apple Inc.</div>
<a class="result__a" href="#">Google vs Apple comparison</a>
<div class="result__snippet">Alphabet Inc (Google) competes with Apple in mobile and cloud.</div>
</body></html>
"""

_MSFT_TICKER_ENTRY = {"ticker": "MSFT", "cik_str": 789019, "title": "MICROSOFT CORP"}
_GOOG_TICKER_ENTRY = {"ticker": "GOOGL", "cik_str": 1652044, "title": "ALPHABET INC"}
_SMSN_TICKER_ENTRY = {"ticker": "SSNLF", "cik_str": 310158, "title": "SAMSUNG ELECTRONICS CO LTD"}

_FAKE_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q"],
            "accessionNumber": ["0000789019-24-000001", "0000789019-24-000002"],
            "filingDate": ["2024-07-30", "2024-04-25"],
            "primaryDocument": ["form10k.htm", "form10q.htm"],
            "primaryDocDescription": ["10-K", "10-Q"],
        }
    }
}


class TestPeerSelector:

    def test_select_returns_list_of_tuples(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions") as mock_subs,
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            mock_lookup.side_effect = lambda name, max_results=5: (
                [_MSFT_TICKER_ENTRY] if "microsoft" in name.lower() else
                [_GOOG_TICKER_ENTRY] if "alphabet" in name.lower() or "google" in name.lower() else
                [_SMSN_TICKER_ENTRY] if "samsung" in name.lower() else
                []
            )
            mock_subs.return_value = _FAKE_SUBMISSIONS

            selector = PeerSelector(cache=mock_cache, max_peers=3, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert isinstance(results, list)
        for peer_identity, peer_sources in results:
            assert isinstance(peer_identity, CompanyIdentity)
            assert isinstance(peer_sources, list)

    def test_select_excludes_target_company(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        _AAPL_ENTRY = {"ticker": "AAPL", "cik_str": 320193, "title": "APPLE INC"}

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            # Always return Apple itself
            mock_lookup.return_value = [_AAPL_ENTRY]

            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        symbols = [p.symbol for p, _ in results]
        assert "AAPL" not in symbols

    def test_select_respects_max_peers(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions") as mock_subs,
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            # Always resolve to distinct tickers
            _counter = {"n": 0}
            def _rotating_lookup(name, max_results=5):
                n = _counter["n"]
                _counter["n"] += 1
                return [{"ticker": f"PEER{n}", "cik_str": 1000000 + n, "title": f"Peer {n} Corp"}]
            mock_lookup.side_effect = _rotating_lookup
            mock_subs.return_value = _FAKE_SUBMISSIONS

            selector = PeerSelector(cache=mock_cache, max_peers=2, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert len(results) <= 2

    def test_select_deduplicates_peers(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions") as mock_subs,
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            # All candidates resolve to the same ticker
            mock_lookup.return_value = [_MSFT_TICKER_ENTRY]
            mock_subs.return_value = _FAKE_SUBMISSIONS

            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        symbols = [p.symbol for p, _ in results]
        assert len(symbols) == len(set(symbols)), "Duplicate peers returned"

    def test_select_skips_unresolvable_candidates(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name", return_value=[]),
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        # No matches → empty results
        assert results == []

    def test_select_graceful_on_ddg_failure(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post", side_effect=Exception("network error")),
            patch("time.sleep"),
        ):
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert results == []

    def test_select_graceful_on_edgar_failure(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("httpx.post") as mock_post,
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.sources.edgar.get_submissions", side_effect=Exception("EDGAR down")),
            patch("time.sleep"),
        ):
            resp = MagicMock()
            resp.content = _DDG_SNIPPETS_HTML
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            mock_lookup.return_value = [_MSFT_TICKER_ENTRY]

            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        # Peer identity resolved but no sources
        for _peer, peer_sources in results:
            assert peer_sources == []


class TestExtractCompanyNames:

    def test_extracts_title_case_names(self):
        from company_research.sources.peer_selector import _extract_company_names

        text = "Apple's main competitors are Microsoft Corp and Samsung Electronics."
        names = _extract_company_names(text)
        assert any("Microsoft" in n for n in names)

    def test_ignores_short_names(self):
        from company_research.sources.peer_selector import _extract_company_names

        names = _extract_company_names("vs Inc Co The")
        assert all(len(n) >= 4 for n in names)

    def test_empty_text_returns_empty(self):
        from company_research.sources.peer_selector import _extract_company_names

        assert _extract_company_names("") == []
