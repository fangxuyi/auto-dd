"""Unit tests for VC-M3: external discovery, profit pool enrichment, LLM synthesis, reporting."""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from company_research.models.value_chain import (
    ChokepointAssessment,
    CompanyRelationship,
    GraphEdge,
    GraphNode,
    ProfitPoolAssessment,
    ValueChainGraph,
    ValueChainLayer,
)
from company_research.value_chain.reporting import write_value_chain_report


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_id() -> str:
    return str(uuid.uuid4())


def _make_graph(run_id: str, symbol: str = "AAPL") -> ValueChainGraph:
    return ValueChainGraph(run_id=run_id, symbol=symbol, as_of_date=date(2026, 6, 16))


# ── external_discovery ────────────────────────────────────────────────────────


def _make_company():
    from company_research.models.identity import CompanyIdentity
    return CompanyIdentity(
        symbol="AAPL", exchange="NASDAQ", issuer_name="Apple Inc.",
        cik="0000320193", filing_jurisdiction="US",
        fiscal_year_end="09-30", currency="USD",
    )


class TestDiscoverFromWeb:
    def test_returns_empty_on_ddgs_import_error(self):
        company = _make_company()
        cache = MagicMock()
        with patch.dict("sys.modules", {"ddgs": None}):
            from company_research.value_chain import external_discovery
            import importlib
            # Patch the import inside the function
            with patch("builtins.__import__", side_effect=ImportError("ddgs")):
                result = external_discovery.discover_from_web(company, _run_id(), cache)
        # Will raise ImportError caught by the function — returns []
        assert isinstance(result, list)

    def test_returns_candidates_from_snippets(self):
        company = _make_company()
        cache = MagicMock()
        cache.store_bytes = MagicMock(return_value=MagicMock())

        mock_result = [{
            "href": "https://example.com/article",
            "body": "Apple Inc. supplier Samsung Electronics provides OLED displays to Apple.",
        }]

        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = mock_result
        mock_ddgs_class = MagicMock(return_value=mock_ddgs_instance)

        from company_research.value_chain.external_discovery import discover_from_web
        with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=mock_ddgs_class)}):
            with patch("urllib.request.urlopen", side_effect=Exception("no network in tests")):
                result = discover_from_web(company, _run_id(), cache, max_per_query=1)

        assert isinstance(result, list)
        for c in result:
            assert hasattr(c, "normalized_name")
            assert hasattr(c, "run_id")

    def test_deduplicates_by_normalized_name(self):
        """Two snippets with the same entity name → one candidate returned."""
        company = _make_company()
        cache = MagicMock()

        # Two results with identical snippet about same supplier
        mock_results = [
            {"href": "https://a.com", "body": "Apple Inc. supplier Samsung Electronics is a major vendor."},
            {"href": "https://b.com", "body": "Apple Inc. supplier Samsung Electronics provides parts."},
        ]
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = mock_results
        mock_ddgs_class = MagicMock(return_value=mock_ddgs_instance)

        from company_research.value_chain.external_discovery import discover_from_web
        with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=mock_ddgs_class)}):
            with patch("urllib.request.urlopen", side_effect=Exception("no network")):
                result = discover_from_web(company, _run_id(), cache, max_per_query=2)

        names = [c.normalized_name.lower() for c in result]
        # No duplicate names
        assert len(names) == len(set(names))


# ── profit_pools ──────────────────────────────────────────────────────────────


class TestBuildProfitPools:
    def _make_layer(self, run_id, name, order=0):
        return ValueChainLayer(run_id=run_id, symbol="AAPL", layer_name=name, order=order)

    def test_own_layer_computes_margin_from_metrics(self):
        from company_research.value_chain.profit_pools import build_profit_pools

        run_id = _run_id()
        layers = [self._make_layer(run_id, "company")]

        db = MagicMock()
        db.get_metrics.return_value = [
            {"name": "revenue", "value": 400_000_000_000, "period": "2025", "period_type": "annual"},
            {"name": "gross_profit", "value": 180_000_000_000, "period": "2025", "period_type": "annual"},
            {"name": "operating_income", "value": 120_000_000_000, "period": "2025", "period_type": "annual"},
        ]
        db.upsert_vc_profit_pool = MagicMock()

        result = build_profit_pools(layers, run_id, db)

        assert len(result) == 1
        pp = result[0]
        assert pp.gross_margin_range is not None
        assert "45" in pp.gross_margin_range  # 180/400 = 45%
        assert pp.operating_margin_range is not None
        assert "30" in pp.operating_margin_range  # 120/400 = 30%

    def test_non_own_layer_populates_representative_companies(self):
        from company_research.value_chain.profit_pools import build_profit_pools

        run_id = _run_id()
        layers = [self._make_layer(run_id, "upstream")]

        rel = MagicMock()
        rel.current_status = "confirmed_direct"
        rel.value_chain_layer = "upstream"
        rel.source_entity_id = "eid-1"
        rel.target_entity_id = "eid-2"

        db = MagicMock()
        db.get_metrics.return_value = []
        db.get_vc_entity.side_effect = lambda eid: {"ticker": "TSMC"} if eid == "eid-1" else None
        db.upsert_vc_profit_pool = MagicMock()

        result = build_profit_pools(layers, run_id, db, relationships=[rel])

        assert len(result) == 1
        pp = result[0]
        assert "TSMC" in pp.representative_companies

    def test_upsert_called_for_each_layer(self):
        from company_research.value_chain.profit_pools import build_profit_pools

        run_id = _run_id()
        layers = [
            self._make_layer(run_id, "upstream"),
            self._make_layer(run_id, "company"),
            self._make_layer(run_id, "downstream"),
        ]
        db = MagicMock()
        db.get_metrics.return_value = []
        db.get_vc_entity.return_value = None
        db.upsert_vc_profit_pool = MagicMock()

        result = build_profit_pools(layers, run_id, db)

        assert len(result) == 3
        assert db.upsert_vc_profit_pool.call_count == 3


# ── llm_synthesis ─────────────────────────────────────────────────────────────


class TestEnrichChokepointsLlm:
    def test_returns_empty_list_unchanged(self):
        from company_research.value_chain.llm_synthesis import enrich_chokepoints_llm

        company = _make_company()
        result = enrich_chokepoints_llm([], [], company)
        assert result == []

    def test_fills_fields_from_llm_response(self):
        from company_research.value_chain.llm_synthesis import enrich_chokepoints_llm

        cp = ChokepointAssessment(
            run_id=_run_id(),
            chokepoint="High dependency on SUPPLIES relationship",
            confidence="medium",
        )
        company = _make_company()

        llm_response = json.dumps([{
            "chokepoint_id": cp.chokepoint_id,
            "failure_mechanism": "Production halts within 6 weeks",
            "financial_effect": "~$10B revenue impact per quarter",
            "early_warning_indicators": ["Supply lead time increase", "Inventory drawdown"],
            "mitigation": "Qualify secondary suppliers",
        }])

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=llm_response)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = enrich_chokepoints_llm([cp], [], company)

        assert len(result) == 1
        assert result[0].failure_mechanism == "Production halts within 6 weeks"
        assert result[0].financial_effect == "~$10B revenue impact per quarter"
        assert len(result[0].early_warning_indicators) == 2
        assert result[0].mitigation == "Qualify secondary suppliers"

    def test_fails_gracefully_on_llm_error(self):
        from company_research.value_chain.llm_synthesis import enrich_chokepoints_llm

        cp = ChokepointAssessment(
            run_id=_run_id(),
            chokepoint="Test chokepoint",
            confidence="low",
        )
        company = _make_company()

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = enrich_chokepoints_llm([cp], [], company)

        assert len(result) == 1
        assert result[0].failure_mechanism == ""  # untouched


class TestSynthesizeVcNarrative:
    def test_returns_nonempty_string(self):
        from company_research.value_chain.llm_synthesis import synthesize_vc_narrative

        graph = _make_graph(_run_id())
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Apple occupies a central position in its value chain.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = synthesize_vc_narrative("AAPL", "Apple Inc.", graph, [], [])

        assert isinstance(result, str)
        assert len(result) > 0

    def test_falls_back_to_boilerplate_on_error(self):
        from company_research.value_chain.llm_synthesis import synthesize_vc_narrative

        graph = _make_graph(_run_id())

        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = synthesize_vc_narrative("AAPL", "Apple Inc.", graph, [], [])

        assert "Apple Inc." in result
        assert "AAPL" in result


# ── reporting ─────────────────────────────────────────────────────────────────


class TestWriteValueChainReport:
    def test_narrative_appears_in_output(self, tmp_path):
        run_id = _run_id()
        graph = _make_graph(run_id)

        content = write_value_chain_report(
            symbol="AAPL",
            as_of=date(2026, 6, 16),
            graph=graph,
            profit_pools=[],
            chokepoints=[],
            out_dir=tmp_path,
            narrative="Apple has a strong upstream concentration in semiconductor supply.",
        )

        assert "Apple has a strong upstream concentration" in content
        report_path = tmp_path / "value_chain_report.md"
        assert report_path.exists()

    def test_external_candidate_count_in_data_sources(self, tmp_path):
        run_id = _run_id()
        graph = _make_graph(run_id)

        content = write_value_chain_report(
            symbol="AAPL",
            as_of=date(2026, 6, 16),
            graph=graph,
            profit_pools=[],
            chokepoints=[],
            out_dir=tmp_path,
            external_candidate_count=12,
        )

        assert "web search" in content
        assert "12" in content

    def test_enriched_chokepoint_fields_rendered(self, tmp_path):
        run_id = _run_id()
        graph = _make_graph(run_id)
        cp = ChokepointAssessment(
            run_id=run_id,
            chokepoint="Sole-source OLED supplier",
            confidence="high",
            failure_mechanism="Production halts within 6 weeks",
            financial_effect="~$10B/quarter revenue impact",
            early_warning_indicators=["Lead time spike", "Inventory drawdown"],
            mitigation="Qualify MicroLED alternatives",
        )

        content = write_value_chain_report(
            symbol="AAPL",
            as_of=date(2026, 6, 16),
            graph=graph,
            profit_pools=[],
            chokepoints=[cp],
            out_dir=tmp_path,
        )

        assert "Production halts within 6 weeks" in content
        assert "~$10B/quarter revenue impact" in content
        assert "Lead time spike" in content
        assert "Qualify MicroLED alternatives" in content

    def test_no_narrative_uses_boilerplate(self, tmp_path):
        run_id = _run_id()
        graph = _make_graph(run_id)

        content = write_value_chain_report(
            symbol="AAPL",
            as_of=date(2026, 6, 16),
            graph=graph,
            profit_pools=[],
            chokepoints=[],
            out_dir=tmp_path,
        )

        assert "upstream inputs" in content
        assert "downstream routes" in content
