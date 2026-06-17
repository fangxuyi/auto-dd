"""Unit tests for VC-M4: graph diff, monitoring indicators, update pipeline."""
from __future__ import annotations

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
    ValueChainGraph,
)
from company_research.models.value_chain_diff import VCGraphDiff, VCMonitoringIndicator
from company_research.value_chain.graph_diff import diff_graphs
from company_research.value_chain.monitoring import extract_monitoring_indicators


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_id() -> str:
    return str(uuid.uuid4())


def _node(run_id: str, name: str, ticker: str | None = None) -> GraphNode:
    eid = str(uuid.uuid4())
    node = GraphNode(
        run_id=run_id,
        entity_id=eid,
        entity_name=name,
        public_status="public",
        ticker=ticker,
    )
    return node


def _edge(run_id: str, src_node_id: str, tgt_node_id: str,
          rel_type: str = "SUPPLIES", status: str = "confirmed_direct",
          confidence: str = "high", materiality: str = "significant") -> GraphEdge:
    return GraphEdge(
        run_id=run_id,
        source_node_id=src_node_id,
        target_node_id=tgt_node_id,
        relationship_type=rel_type,
        status=status,
        confidence=confidence,
        materiality=materiality,
    )


def _graph(run_id: str, symbol: str = "AAPL",
           nodes: list | None = None, edges: list | None = None) -> ValueChainGraph:
    g = ValueChainGraph(run_id=run_id, symbol=symbol, as_of_date=date(2026, 6, 16))
    g.nodes = nodes or []
    g.edges = edges or []
    return g


# ── VCGraphDiff model ──────────────────────────────────────────────────────────


class TestVCGraphDiffModel:
    def test_has_changes_false_when_empty(self):
        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
        )
        assert not diff.has_changes

    def test_has_changes_true_with_changes(self):
        from company_research.models.value_chain_diff import VCRelationshipChange
        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
            changes=[VCRelationshipChange(
                change_type="added",
                entity_name="A → B",
                relationship_type="SUPPLIES",
            )],
        )
        assert diff.has_changes

    def test_has_changes_true_with_new_nodes(self):
        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
            new_node_names=["Qualcomm"],
        )
        assert diff.has_changes

    def test_has_changes_true_with_removed_nodes(self):
        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
            removed_node_names=["Intel"],
        )
        assert diff.has_changes


# ── diff_graphs ────────────────────────────────────────────────────────────────


class TestDiffGraphs:
    def test_identical_graphs_produce_no_changes(self):
        rid = _run_id()
        n1 = _node(rid, "Apple Inc.", "AAPL")
        n2 = _node(rid, "TSMC", "TSM")
        e = _edge(rid, n1.node_id, n2.node_id)

        prior = _graph(rid, nodes=[n1, n2], edges=[e])
        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        n2c = GraphNode(**{**n2.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        ec = GraphEdge(**{**e.model_dump(), "run_id": current_rid, "edge_id": str(uuid.uuid4()),
                          "source_node_id": n1c.node_id, "target_node_id": n2c.node_id})
        current = _graph(current_rid, nodes=[n1c, n2c], edges=[ec])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert not diff.has_changes
        assert diff.changes == []
        assert diff.new_node_names == []
        assert diff.removed_node_names == []

    def test_added_node_detected(self):
        prior_rid = _run_id()
        n1 = _node(prior_rid, "Apple Inc.", "AAPL")
        prior = _graph(prior_rid, nodes=[n1], edges=[])

        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        n_new = _node(current_rid, "Qualcomm", "QCOM")
        current = _graph(current_rid, nodes=[n1c, n_new], edges=[])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert "Qualcomm" in diff.new_node_names
        assert diff.removed_node_names == []

    def test_removed_node_detected(self):
        prior_rid = _run_id()
        n1 = _node(prior_rid, "Apple Inc.", "AAPL")
        n2 = _node(prior_rid, "Samsung", "005930.KS")
        prior = _graph(prior_rid, nodes=[n1, n2], edges=[])

        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        current = _graph(current_rid, nodes=[n1c], edges=[])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert "Samsung" in diff.removed_node_names

    def test_added_edge_detected(self):
        prior_rid = _run_id()
        n1 = _node(prior_rid, "Apple Inc.", "AAPL")
        n2 = _node(prior_rid, "TSMC", "TSM")
        prior = _graph(prior_rid, nodes=[n1, n2], edges=[])

        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        n2c = GraphNode(**{**n2.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        ec = _edge(current_rid, n1c.node_id, n2c.node_id, rel_type="SUPPLIES")
        current = _graph(current_rid, nodes=[n1c, n2c], edges=[ec])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert len(diff.changes) == 1
        assert diff.changes[0].change_type == "added"
        assert diff.changes[0].relationship_type == "SUPPLIES"

    def test_removed_edge_detected(self):
        prior_rid = _run_id()
        n1 = _node(prior_rid, "Apple Inc.", "AAPL")
        n2 = _node(prior_rid, "TSMC", "TSM")
        ep = _edge(prior_rid, n1.node_id, n2.node_id, rel_type="SUPPLIES")
        prior = _graph(prior_rid, nodes=[n1, n2], edges=[ep])

        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        n2c = GraphNode(**{**n2.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        current = _graph(current_rid, nodes=[n1c, n2c], edges=[])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert len(diff.changes) == 1
        assert diff.changes[0].change_type == "removed"

    def test_status_change_detected(self):
        prior_rid = _run_id()
        n1 = _node(prior_rid, "Apple Inc.", "AAPL")
        n2 = _node(prior_rid, "TSMC", "TSM")
        ep = _edge(prior_rid, n1.node_id, n2.node_id, status="inferred_likely")
        prior = _graph(prior_rid, nodes=[n1, n2], edges=[ep])

        current_rid = _run_id()
        n1c = GraphNode(**{**n1.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        n2c = GraphNode(**{**n2.model_dump(), "run_id": current_rid, "node_id": str(uuid.uuid4())})
        ec = _edge(current_rid, n1c.node_id, n2c.node_id, status="confirmed_direct")
        current = _graph(current_rid, nodes=[n1c, n2c], edges=[ec])

        diff = diff_graphs(prior, current, date(2026, 6, 16))

        assert len(diff.changes) == 1
        assert diff.changes[0].change_type == "status_changed"
        assert diff.changes[0].prior_status == "inferred_likely"
        assert diff.changes[0].new_status == "confirmed_direct"


# ── extract_monitoring_indicators ─────────────────────────────────────────────


class TestExtractMonitoringIndicators:
    def _make_rel(self, run_id, materiality="critical", rel_type="SUPPLIES",
                  source_entity_id=None, target_entity_id=None):
        return CompanyRelationship(
            run_id=run_id,
            source_entity_id=source_entity_id or str(uuid.uuid4()),
            target_entity_id=target_entity_id or str(uuid.uuid4()),
            relationship_type=rel_type,
            materiality=materiality,
            current_status="confirmed_direct",
        )

    def test_high_materiality_supplies_generates_high_urgency_indicator(self):
        rid = _run_id()
        n1 = _node(rid, "TSMC", "TSM")
        g = _graph(rid, nodes=[n1])
        rel = self._make_rel(rid, materiality="critical", rel_type="SUPPLIES",
                             source_entity_id=n1.node_id)

        indicators = extract_monitoring_indicators(rid, "AAPL", g, [rel], [])

        assert len(indicators) >= 1
        assert indicators[0].urgency == "high"
        assert "TSMC" in indicators[0].entity_name

    def test_significant_materiality_generates_medium_urgency(self):
        rid = _run_id()
        n1 = _node(rid, "Foxconn", "2317.TW")
        g = _graph(rid, nodes=[n1])
        rel = self._make_rel(rid, materiality="significant", rel_type="CONTRACT_MANUFACTURES_FOR",
                             source_entity_id=n1.node_id)

        indicators = extract_monitoring_indicators(rid, "AAPL", g, [rel], [])

        assert any(ind.urgency == "medium" for ind in indicators)

    def test_chokepoint_early_warning_generates_indicator(self):
        rid = _run_id()
        g = _graph(rid)
        cp = ChokepointAssessment(
            run_id=rid,
            chokepoint="Sole-source OLED supplier",
            confidence="high",
            failure_mechanism="Production halt within 6 weeks",
            early_warning_indicators=["Lead time increase", "Inventory drawdown"],
        )

        indicators = extract_monitoring_indicators(rid, "AAPL", g, [], [cp])

        # Should get 2 indicators from the 2 early_warning_indicators (capped at [:2])
        assert len(indicators) == 2
        texts = [i.indicator for i in indicators]
        assert any("Lead time" in t for t in texts)
        assert any("Inventory" in t for t in texts)

    def test_non_high_materiality_ignored(self):
        rid = _run_id()
        g = _graph(rid)
        rel = self._make_rel(rid, materiality="minor", rel_type="SUPPLIES")

        indicators = extract_monitoring_indicators(rid, "AAPL", g, [rel], [])

        assert indicators == []

    def test_non_high_dep_type_ignored(self):
        rid = _run_id()
        g = _graph(rid)
        rel = self._make_rel(rid, materiality="critical", rel_type="COMPETES_WITH")

        indicators = extract_monitoring_indicators(rid, "AAPL", g, [rel], [])

        assert indicators == []


# ── _write_vc_diff_report ─────────────────────────────────────────────────────


class TestWriteVcDiffReport:
    def test_no_changes_message(self, tmp_path):
        from company_research.pipeline_value_chain import _write_vc_diff_report

        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
        )
        _write_vc_diff_report("AAPL", date(2026, 6, 16), diff, [], tmp_path)

        report = (tmp_path / "value_chain_diff.md").read_text()
        assert "No Changes Detected" in report

    def test_new_entity_in_report(self, tmp_path):
        from company_research.pipeline_value_chain import _write_vc_diff_report

        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
            new_node_names=["Qualcomm"],
        )
        _write_vc_diff_report("AAPL", date(2026, 6, 16), diff, [], tmp_path)

        report = (tmp_path / "value_chain_diff.md").read_text()
        assert "Qualcomm" in report
        assert "New Entities" in report

    def test_monitoring_indicators_in_report(self, tmp_path):
        from company_research.pipeline_value_chain import _write_vc_diff_report

        diff = VCGraphDiff(
            symbol="AAPL",
            prior_run_id=_run_id(),
            new_run_id=_run_id(),
            as_of_date=date(2026, 6, 16),
        )
        ind = VCMonitoringIndicator(
            run_id=_run_id(),
            symbol="AAPL",
            entity_name="TSMC",
            relationship_type="SUPPLIES",
            indicator="Monitor TSMC supply lead times",
            trigger="Lead time increase > 20%",
            urgency="high",
        )
        _write_vc_diff_report("AAPL", date(2026, 6, 16), diff, [ind], tmp_path)

        report = (tmp_path / "value_chain_diff.md").read_text()
        assert "Monitoring Indicators" in report
        assert "TSMC" in report
        assert "[HIGH]" in report
