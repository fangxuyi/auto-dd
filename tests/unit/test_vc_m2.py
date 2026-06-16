"""Unit tests for VC-M2: HTML extraction, reverse lookup, improved resolution."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from company_research.models.value_chain import EntityCandidate, PublicEntityIdentity
from company_research.value_chain.html_extraction import extract_text


# ── HTML extraction ───────────────────────────────────────────────────────────


class TestExtractText:
    def test_strips_html_tags(self):
        html = b"<html><body><p>Apple sells iPhones to customers worldwide.</p></body></html>"
        text = extract_text(html)
        assert "Apple sells iPhones" in text
        assert "<p>" not in text
        assert "<body>" not in text

    def test_strips_script_tags(self):
        html = b"<html><body><script>alert('x')</script><p>Real content here.</p></body></html>"
        text = extract_text(html)
        assert "alert" not in text
        assert "Real content" in text

    def test_strips_style_tags(self):
        html = b"<html><head><style>.foo { color: red; }</style></head><body><p>Text content.</p></body></html>"
        text = extract_text(html)
        assert "color: red" not in text
        assert "Text content" in text

    def test_fallback_on_invalid_bytes(self):
        # BeautifulSoup should still handle binary noise gracefully
        result = extract_text(b"\xff\xfe<p>Some text here for testing.</p>")
        assert isinstance(result, str)

    def test_returns_string(self):
        assert isinstance(extract_text(b"<html><body><p>Hello world, this is text.</p></body></html>"), str)

    def test_preserves_paragraph_content(self):
        html = b"""<html><body>
            <p>Our primary supplier, Samsung Electronics, provides OLED displays.</p>
            <p>Significant customers include Best Buy and Walmart Stores.</p>
        </body></html>"""
        text = extract_text(html)
        assert "Samsung Electronics" in text
        assert "Best Buy" in text

    def test_strips_xbrl_tags(self):
        html = b"""<html><body>
        <xbrli:context id="ctx1"><xbrli:entity><xbrli:identifier>0000320193</xbrli:identifier></xbrli:entity></xbrli:context>
        <p>Apple reports revenue of $394 billion for fiscal year 2024.</p>
        </body></html>"""
        text = extract_text(html)
        assert "0000320193" not in text
        assert "Apple reports revenue" in text

    def test_min_word_filter(self):
        html = b"<html><body><p>OK</p><p>This is a longer paragraph with meaningful content about suppliers.</p></body></html>"
        text = extract_text(html)
        # Short "OK" block should be filtered out (< 8 words)
        assert "This is a longer paragraph" in text

    def test_empty_html(self):
        result = extract_text(b"<html></html>")
        assert isinstance(result, str)


# ── Reverse EDGAR lookup ──────────────────────────────────────────────────────


class TestDiscoverReverseMentions:
    def _make_fts_hit(self, cik: str, name: str, ticker: str = "XXX", form: str = "10-K") -> dict:
        """Build a hit matching the actual EDGAR FTS response format."""
        return {
            "_source": {
                "ciks": [cik],
                "display_names": [f"{name}  ({ticker})  (CIK {cik})"],
                "root_forms": [form],
                "form": form,
                "file_date": "2025-03-15",
                "adsh": f"{cik}-25-000001",
            }
        }

    def test_returns_candidates_from_hits(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()

        hit1 = self._make_fts_hit("0000897723", "TAIWAN SEMICONDUCTOR MFG CO LTD", "TSM", "20-F")
        hit2 = self._make_fts_hit("0000049196", "BROADCOM INC", "AVGO", "10-K")

        # Both queries return the same hits (deduplicated across passes)
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[hit1, hit2], []],
        ):
            candidates = discover_reverse_mentions(
                company_name="Apple Inc",
                run_id="run-1",
                as_of=date(2026, 1, 1),
                db=mock_db,
            )

        assert len(candidates) == 2
        names = {c.normalized_name for c in candidates}
        assert "TAIWAN SEMICONDUCTOR MFG CO LTD" in names
        assert "BROADCOM INC" in names

    def test_deduplicates_same_cik(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        hit = self._make_fts_hit("0000897723", "TSMC", "TSM", "10-K")
        # Same CIK returned by both queries
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[hit], [hit]],
        ):
            candidates = discover_reverse_mentions("Apple Inc", "r", date(2026, 1, 1), mock_db)
        assert len(candidates) == 1

    def test_skips_invalid_display_names(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        hits = [
            {"_source": {"ciks": ["0000001234"], "display_names": ["NoParens"], "form": "10-K", "file_date": "2025-01-01"}},
        ]
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[hits, []],
        ):
            candidates = discover_reverse_mentions("Apple Inc", "r", date(2026, 1, 1), mock_db)
        assert candidates == []

    def test_candidates_marked_resolved(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        hit = self._make_fts_hit("0000897723", "TSMC", "TSM")
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[hit], []],
        ):
            candidates = discover_reverse_mentions("Apple Inc", "r", date(2026, 1, 1), mock_db)
        assert candidates[0].resolution_status == "resolved"

    def test_candidates_have_supplies_type(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        hit = self._make_fts_hit("0000897723", "TSMC", "TSM")
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[hit], []],
        ):
            candidates = discover_reverse_mentions("Apple Inc", "r", date(2026, 1, 1), mock_db)
        assert candidates[0].proposed_relationship_type == "SUPPLIES"

    def test_graceful_on_network_error(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[], []],
        ):
            candidates = discover_reverse_mentions("Apple Inc", "r", date(2026, 1, 1), mock_db)
        assert candidates == []

    def test_excludes_target_company_own_cik(self):
        from company_research.value_chain.edgar_reverse import discover_reverse_mentions

        mock_db = MagicMock()
        apple_hit = self._make_fts_hit("0000320193", "Apple Inc", "AAPL", "10-K")
        tsmc_hit = self._make_fts_hit("0000897723", "TSMC", "TSM", "20-F")
        with patch(
            "company_research.value_chain.edgar_reverse._fts_search",
            side_effect=[[apple_hit, tsmc_hit], []],
        ):
            candidates = discover_reverse_mentions(
                "Apple Inc", "r", date(2026, 1, 1), mock_db, target_cik="0000320193"
            )
        # Apple's own filing should be excluded; only TSMC
        assert len(candidates) == 1
        assert candidates[0].normalized_name == "TSMC"


# ── Improved verification (fuzzy name resolution) ────────────────────────────


class TestResolveWithFuzzyFallback:
    def _make_candidate(self, name: str, status: str = "unresolved") -> EntityCandidate:
        return EntityCandidate(
            run_id="r",
            raw_name=name,
            normalized_name=name,
            source_id="src-1",
            source_excerpt="...",
            resolution_status=status,
        )

    def test_pre_resolved_candidate_loaded_from_db(self):
        from company_research.value_chain.verification import resolve_candidates

        entity_id = "entity-abc-123"
        candidate = self._make_candidate("TSMC")
        candidate.resolution_status = "resolved"
        candidate.resolved_entity_id = entity_id

        mock_db = MagicMock()
        mock_db.get_vc_entity.return_value = {
            "entity_id": entity_id,
            "legal_name": "TAIWAN SEMICONDUCTOR MFG CO LTD",
            "common_name": "TSMC",
            "ticker": "TSM",
            "regulator_id": "0000897723",
            "active_listing": 1,
        }
        mock_db.upsert_vc_entity.return_value = None

        pairs = resolve_candidates([candidate], mock_db, max_resolve=10)
        assert len(pairs) == 1
        cand, entity = pairs[0]
        assert entity is not None
        assert entity.legal_name == "TAIWAN SEMICONDUCTOR MFG CO LTD"
        assert entity.entity_id == entity_id

    def test_exact_ticker_match_resolves(self):
        from company_research.value_chain.verification import resolve_candidates

        candidate = self._make_candidate("TSMC")
        mock_db = MagicMock()
        mock_db.upsert_vc_entity.return_value = None

        with patch(
            "company_research.value_chain.verification.lookup_cik",
            return_value=[{"ticker": "TSM", "title": "Taiwan Semiconductor", "cik": 897723}],
        ):
            pairs = resolve_candidates([candidate], mock_db, max_resolve=10)

        assert pairs[0][1] is not None
        assert pairs[0][0].resolution_status == "resolved"

    def test_fuzzy_name_fallback_resolves(self):
        from company_research.value_chain.verification import resolve_candidates

        candidate = self._make_candidate("Taiwan Semiconductor")
        mock_db = MagicMock()
        mock_db.upsert_vc_entity.return_value = None

        with (
            patch("company_research.value_chain.verification.lookup_cik", return_value=[]),
            patch(
                "company_research.value_chain.verification.lookup_by_name",
                return_value=[{"ticker": "TSM", "title": "Taiwan Semiconductor Mfg", "cik": 897723}],
            ),
        ):
            pairs = resolve_candidates([candidate], mock_db, max_resolve=10)

        cand, entity = pairs[0]
        assert entity is not None
        assert cand.resolution_status == "resolved"

    def test_ambiguous_exact_unresolved(self):
        from company_research.value_chain.verification import resolve_candidates

        candidate = self._make_candidate("Apple")
        mock_db = MagicMock()

        with patch(
            "company_research.value_chain.verification.lookup_cik",
            return_value=[
                {"ticker": "AAPL", "title": "Apple Inc", "cik": 320193},
                {"ticker": "APLE", "title": "Apple Hospitality REIT", "cik": 1418121},
            ],
        ):
            pairs = resolve_candidates([candidate], mock_db, max_resolve=10)

        cand, entity = pairs[0]
        assert entity is None
        assert cand.resolution_status == "unresolved"

    def test_no_match_marks_unresolved(self):
        from company_research.value_chain.verification import resolve_candidates

        candidate = self._make_candidate("Unknown Company XYZ")
        mock_db = MagicMock()

        with (
            patch("company_research.value_chain.verification.lookup_cik", return_value=[]),
            patch("company_research.value_chain.verification.lookup_by_name", return_value=[]),
        ):
            pairs = resolve_candidates([candidate], mock_db, max_resolve=10)

        cand, entity = pairs[0]
        assert entity is None
        assert cand.resolution_status == "unresolved"
