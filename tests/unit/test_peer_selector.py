"""Unit tests for PeerSelector."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

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
def mock_cache():
    from unittest.mock import MagicMock
    return MagicMock()


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
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions") as mock_subs,
        ):
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
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions", return_value=_FAKE_SUBMISSIONS),
        ):
            # If DDG returns anything with "apple" in the name, resolve it to AAPL
            mock_lookup.side_effect = lambda name, max_results=5: (
                [_AAPL_ENTRY] if "apple" in name.lower() else
                [_MSFT_TICKER_ENTRY] if "microsoft" in name.lower() else []
            )
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        symbols = [p.symbol for p, _ in results]
        assert "AAPL" not in symbols

    def test_select_respects_max_peers(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        _counter = {"n": 0}
        def _rotating_lookup(name, max_results=5):
            n = _counter["n"]
            _counter["n"] += 1
            return [{"ticker": f"PEER{n}", "cik_str": 1000000 + n, "title": f"Peer {n} Corp"}]

        with (
            patch("company_research.sources.peer_selector.lookup_by_name") as mock_lookup,
            patch("company_research.identity.edgar.get_submissions", return_value=_FAKE_SUBMISSIONS),
        ):
            mock_lookup.side_effect = _rotating_lookup
            selector = PeerSelector(cache=mock_cache, max_peers=2, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert len(results) <= 2

    def test_select_deduplicates_peers(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("company_research.sources.peer_selector.lookup_by_name", return_value=[_MSFT_TICKER_ENTRY]),
            patch("company_research.identity.edgar.get_submissions", return_value=_FAKE_SUBMISSIONS),
        ):
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        symbols = [p.symbol for p, _ in results]
        assert len(symbols) == len(set(symbols)), "Duplicate peers returned"

    def test_select_skips_unresolvable_candidates(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with patch("company_research.sources.peer_selector.lookup_by_name", return_value=[]):
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert results == []

    def test_select_graceful_on_ddg_failure(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        # Simulate DDG being completely unavailable at the internal helper level
        with patch("company_research.sources.peer_selector._ddg_snippets", side_effect=Exception("network error")):
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

        assert results == []

    def test_select_graceful_on_edgar_failure(self, apple, mock_cache):
        from company_research.sources.peer_selector import PeerSelector

        with (
            patch("company_research.sources.peer_selector.lookup_by_name", return_value=[_MSFT_TICKER_ENTRY]),
            patch("company_research.sources.edgar.get_submissions", side_effect=Exception("EDGAR down")),
        ):
            selector = PeerSelector(cache=mock_cache, max_peers=5, max_peer_filings=2)
            results = selector.select(apple, cutoff=date(2026, 6, 15))

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
