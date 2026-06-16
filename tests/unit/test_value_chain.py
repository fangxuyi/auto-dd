"""Unit tests for VC-M1: models, templates, discovery, graph, validation."""
from __future__ import annotations

from datetime import date

import pytest

from company_research.models.value_chain import (
    ChokepointAssessment,
    CompanyRelationship,
    DependencyAssessment,
    EntityCandidate,
    GraphEdge,
    GraphNode,
    ProfitPoolAssessment,
    PublicEntityIdentity,
    RelationshipEvidence,
    ValueChainGraph,
    ValueChainLayer,
)
from company_research.value_chain.discovery import discover_from_text
from company_research.value_chain.graph import build_graph
from company_research.value_chain.templates import infer_template, list_templates, load_template
from company_research.value_chain.validation import run_vc_qa
from company_research.value_chain.verification import (
    evidence_status_to_confidence,
    relationship_status_from_evidence,
)


# ── PublicEntityIdentity ──────────────────────────────────────────────────────


class TestPublicEntityIdentity:
    def test_defaults(self):
        e = PublicEntityIdentity(legal_name="Apple Inc.")
        assert e.active_listing is True
        assert e.primary_listing is True
        assert e.adr_status is False
        assert e.entity_id  # uuid generated

    def test_full_fields(self):
        e = PublicEntityIdentity(
            legal_name="TSMC",
            common_name="Taiwan Semiconductor",
            ticker="TSM",
            exchange="NYSE",
            country="TW",
            adr_status=True,
            regulator_id="0000230463",
        )
        assert e.adr_status is True
        assert e.ticker == "TSM"

    def test_serialization(self):
        e = PublicEntityIdentity(legal_name="Test Corp", ticker="TEST")
        raw = e.model_dump_json()
        e2 = PublicEntityIdentity.model_validate_json(raw)
        assert e2.ticker == "TEST"


# ── CompanyRelationship ───────────────────────────────────────────────────────


class TestCompanyRelationship:
    def test_defaults(self):
        rel = CompanyRelationship(
            run_id="run-1",
            source_entity_id="e1",
            target_entity_id="e2",
            relationship_type="SUPPLIES",
        )
        assert rel.current_status == "unverified_candidate"
        assert rel.confidence == "unknown"
        assert rel.reverse_verified is False

    def test_directional(self):
        rel = CompanyRelationship(
            run_id="run-1",
            source_entity_id="supplier",
            target_entity_id="buyer",
            relationship_type="CUSTOMER_OF",
        )
        assert rel.source_entity_id != rel.target_entity_id

    def test_serialization_roundtrip(self):
        rel = CompanyRelationship(
            run_id="r",
            source_entity_id="a",
            target_entity_id="b",
            relationship_type="HOSTS",
            confidence="high",
            current_status="confirmed_direct",
        )
        r2 = CompanyRelationship.model_validate_json(rel.model_dump_json())
        assert r2.confidence == "high"
        assert r2.current_status == "confirmed_direct"


# ── ValueChainGraph ───────────────────────────────────────────────────────────


class TestValueChainGraph:
    def _make_node(self, entity_id: str, run_id: str = "r") -> GraphNode:
        return GraphNode(run_id=run_id, entity_id=entity_id, entity_name=entity_id)

    def _make_edge(
        self, src: str, tgt: str, status: str = "confirmed_direct", run_id: str = "r"
    ) -> GraphEdge:
        return GraphEdge(
            run_id=run_id,
            source_node_id=src,
            target_node_id=tgt,
            relationship_type="SUPPLIES",
            status=status,
        )

    def test_empty_graph(self):
        g = ValueChainGraph(run_id="r", symbol="AAPL", as_of_date=date(2026, 6, 16))
        assert g.nodes == []
        assert g.edges == []
        assert g.confirmed_edges == []

    def test_confirmed_edges_filter(self):
        n1 = self._make_node("n1")
        n2 = self._make_node("n2")
        e_confirmed = self._make_edge(n1.node_id, n2.node_id, "confirmed_direct")
        e_unverified = self._make_edge(n1.node_id, n2.node_id, "unverified_candidate")
        g = ValueChainGraph(
            run_id="r", symbol="X", as_of_date=date(2026, 1, 1),
            nodes=[n1, n2], edges=[e_confirmed, e_unverified],
        )
        assert len(g.confirmed_edges) == 1
        assert g.confirmed_edges[0].status == "confirmed_direct"


# ── Templates ─────────────────────────────────────────────────────────────────


class TestTemplates:
    def test_list_templates(self):
        templates = list_templates()
        assert "software_cloud" in templates
        assert "semiconductors" in templates
        assert len(templates) >= 7

    def test_load_software_cloud(self):
        t = load_template("software_cloud")
        assert t["name"] == "software_cloud"
        assert "layers" in t
        assert any(layer.get("is_target") for layer in t["layers"])

    def test_load_semiconductors(self):
        t = load_template("semiconductors")
        layers = {l["name"] for l in t["layers"]}
        assert "foundry" in layers
        assert "eda_and_ip" in layers

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_template("does_not_exist")

    def test_infer_software(self):
        assert infer_template(None, "Salesforce Inc") == "software_cloud"
        assert infer_template(None, "Snowflake Computing") == "software_cloud"

    def test_infer_semiconductor(self):
        assert infer_template(None, "NVIDIA Corporation semiconductor") == "semiconductors"

    def test_infer_healthcare(self):
        assert infer_template(None, "Eli Lilly pharmaceutical drug") == "healthcare"

    def test_infer_default(self):
        assert infer_template(None, "Acme Widgets Inc") == "software_cloud"


# ── Discovery ─────────────────────────────────────────────────────────────────


class TestDiscoverFromText:
    def test_finds_supplier_mention(self):
        text = "Our primary supplier, Foxconn Technology, provides assembly services."
        candidates = discover_from_text(text, run_id="r", source_id="s1")
        names = [c.normalized_name for c in candidates]
        assert any("Foxconn" in n for n in names)

    def test_finds_customer_mention(self):
        text = "Significant customers include Apple Inc. and Microsoft Corporation."
        candidates = discover_from_text(text, run_id="r", source_id="s1")
        names = [c.normalized_name for c in candidates]
        assert any("Apple" in n for n in names)

    def test_excludes_short_names(self):
        text = "Our supplier, IBM, provides services."
        candidates = discover_from_text(text, run_id="r", source_id="s1", min_name_len=5)
        # "IBM" is only 3 chars — should be excluded at min_name_len=5
        assert all(len(c.normalized_name) >= 5 for c in candidates)

    def test_deduplicates(self):
        text = "Supplier, TSMC Corp, is our foundry. We rely on TSMC Corp for all wafers."
        candidates = discover_from_text(text, run_id="r", source_id="s1")
        names = [c.normalized_name.lower() for c in candidates]
        # Should not have duplicate entries for same name
        assert len(names) == len(set(names))

    def test_empty_text(self):
        assert discover_from_text("", run_id="r", source_id="s") == []

    def test_captures_excerpt(self):
        text = "Our largest supplier, Corning Incorporated, provides glass substrates for display."
        candidates = discover_from_text(text, run_id="r", source_id="s1")
        assert any(c.source_excerpt for c in candidates)

    def test_max_candidates_limit(self):
        text = " ".join(
            f"Our supplier, Company{i} Inc, provides part {i}." for i in range(100)
        )
        candidates = discover_from_text(text, run_id="r", source_id="s1", max_candidates=5)
        assert len(candidates) <= 5


# ── Verification helpers ──────────────────────────────────────────────────────


class TestVerificationHelpers:
    def test_confidence_both_confirmed(self):
        assert evidence_status_to_confidence(True, True) == "high"

    def test_confidence_one_confirmed(self):
        assert evidence_status_to_confidence(True, False) == "medium"
        assert evidence_status_to_confidence(False, True) == "medium"

    def test_confidence_neither(self):
        assert evidence_status_to_confidence(False, False) == "low"

    def test_status_from_primary_and_reverse(self):
        assert relationship_status_from_evidence("confirmed_primary", True) == "confirmed_direct"

    def test_status_from_primary_no_reverse(self):
        assert relationship_status_from_evidence("confirmed_primary", False) == "confirmed_direct"

    def test_status_from_inferred(self):
        assert relationship_status_from_evidence("inferred", False) == "inferred_likely"

    def test_status_from_historical(self):
        assert relationship_status_from_evidence("historical", False) == "historical"

    def test_status_from_contradicted(self):
        assert relationship_status_from_evidence("contradicted", False) == "contradicted"

    def test_status_from_unverified(self):
        assert relationship_status_from_evidence("unverified", False) == "unverified_candidate"


# ── Graph builder ─────────────────────────────────────────────────────────────


class TestBuildGraph:
    def _entity(self, ticker: str) -> PublicEntityIdentity:
        return PublicEntityIdentity(legal_name=f"{ticker} Inc", ticker=ticker, active_listing=True)

    def _relationship(self, src_id: str, tgt_id: str, status: str = "confirmed_direct") -> CompanyRelationship:
        return CompanyRelationship(
            run_id="run-1",
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            relationship_type="SUPPLIES",
            current_status=status,
        )

    def test_empty_relationships(self):
        g = build_graph("r", "AAPL", date(2026, 6, 16), [], {})
        assert g.nodes == []
        assert g.edges == []

    def test_confirmed_edge_creates_nodes(self):
        e1 = self._entity("TSMC")
        e2 = self._entity("AAPL")
        entities = {e1.entity_id: e1, e2.entity_id: e2}
        rel = self._relationship(e1.entity_id, e2.entity_id, "confirmed_direct")
        g = build_graph("r", "AAPL", date(2026, 6, 16), [rel], entities)
        assert len(g.nodes) == 2
        assert len(g.edges) == 1

    def test_unverified_excluded(self):
        e1 = self._entity("TSMC")
        e2 = self._entity("AAPL")
        entities = {e1.entity_id: e1, e2.entity_id: e2}
        rel = self._relationship(e1.entity_id, e2.entity_id, "unverified_candidate")
        g = build_graph("r", "AAPL", date(2026, 6, 16), [rel], entities)
        assert len(g.edges) == 0
        assert len(g.nodes) == 0

    def test_contradicted_excluded(self):
        e1 = self._entity("X")
        e2 = self._entity("Y")
        entities = {e1.entity_id: e1, e2.entity_id: e2}
        rel = self._relationship(e1.entity_id, e2.entity_id, "contradicted")
        g = build_graph("r", "Z", date(2026, 6, 16), [rel], entities)
        assert len(g.edges) == 0


# ── VC QA ─────────────────────────────────────────────────────────────────────


class TestVCQA:
    def test_empty_passes(self):
        g = ValueChainGraph(run_id="r", symbol="X", as_of_date=date(2026, 6, 16))
        result = run_vc_qa(g, [])
        assert result.passed

    def test_confirmed_without_source_fails(self):
        g = ValueChainGraph(run_id="r", symbol="X", as_of_date=date(2026, 6, 16))
        rel = CompanyRelationship(
            run_id="r",
            source_entity_id="a",
            target_entity_id="b",
            relationship_type="SUPPLIES",
            current_status="confirmed_direct",
            source_ids=[],  # no source = critical failure
        )
        result = run_vc_qa(g, [rel])
        assert not result.passed
        assert "confirmed_relationships_have_sources" in result.critical_failures

    def test_unverified_in_graph_fails(self):
        edge = GraphEdge(
            run_id="r",
            source_node_id="n1",
            target_node_id="n2",
            relationship_type="SUPPLIES",
            status="unverified_candidate",
        )
        g = ValueChainGraph(
            run_id="r", symbol="X", as_of_date=date(2026, 6, 16), edges=[edge]
        )
        result = run_vc_qa(g, [])
        assert not result.passed
        assert "unverified_candidates_excluded_from_graph" in result.critical_failures
