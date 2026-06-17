"""Diff two value chain graphs and produce a VCGraphDiff."""
from __future__ import annotations

import logging
from datetime import date

from company_research.models.value_chain import ValueChainGraph
from company_research.models.value_chain_diff import VCGraphDiff, VCRelationshipChange

log = logging.getLogger(__name__)


def diff_graphs(
    prior: ValueChainGraph,
    current: ValueChainGraph,
    as_of: date,
) -> VCGraphDiff:
    """
    Compare two graphs for the same symbol and return a VCGraphDiff.
    Matches edges by (source_entity_name, target_entity_name, relationship_type).
    """
    diff = VCGraphDiff(
        symbol=current.symbol,
        prior_run_id=prior.run_id,
        new_run_id=current.run_id,
        as_of_date=as_of,
    )

    prior_node_names = {n.entity_name for n in prior.nodes}
    current_node_names = {n.entity_name for n in current.nodes}
    diff.new_node_names = sorted(current_node_names - prior_node_names)
    diff.removed_node_names = sorted(prior_node_names - current_node_names)

    prior_node_map = {n.node_id: n.entity_name for n in prior.nodes}
    current_node_map = {n.node_id: n.entity_name for n in current.nodes}

    def _edge_key(edge, node_map):
        src = node_map.get(edge.source_node_id, edge.source_node_id)
        tgt = node_map.get(edge.target_node_id, edge.target_node_id)
        return (src, tgt, edge.relationship_type)

    prior_edges = {_edge_key(e, prior_node_map): e for e in prior.edges}
    current_edges = {_edge_key(e, current_node_map): e for e in current.edges}

    all_keys = set(prior_edges) | set(current_edges)
    for key in sorted(all_keys, key=lambda k: k[0]):
        src_name, tgt_name, rel_type = key
        entity_label = f"{src_name} → {tgt_name}"
        p = prior_edges.get(key)
        c = current_edges.get(key)

        if p is None and c is not None:
            diff.changes.append(VCRelationshipChange(
                change_type="added",
                entity_name=entity_label,
                relationship_type=rel_type,
                product_or_service=c.product_or_service,
                new_status=c.status,
                new_confidence=c.confidence,
                new_materiality=c.materiality,
            ))
        elif p is not None and c is None:
            diff.changes.append(VCRelationshipChange(
                change_type="removed",
                entity_name=entity_label,
                relationship_type=rel_type,
                product_or_service=p.product_or_service,
                prior_status=p.status,
                prior_confidence=p.confidence,
                prior_materiality=p.materiality,
            ))
        elif p is not None and c is not None:
            if p.status != c.status:
                diff.changes.append(VCRelationshipChange(
                    change_type="status_changed",
                    entity_name=entity_label,
                    relationship_type=rel_type,
                    prior_status=p.status,
                    new_status=c.status,
                    prior_confidence=p.confidence,
                    new_confidence=c.confidence,
                ))
            elif p.confidence != c.confidence:
                diff.changes.append(VCRelationshipChange(
                    change_type="confidence_changed",
                    entity_name=entity_label,
                    relationship_type=rel_type,
                    prior_confidence=p.confidence,
                    new_confidence=c.confidence,
                    prior_status=p.status,
                    new_status=c.status,
                ))
            elif p.materiality != c.materiality:
                diff.changes.append(VCRelationshipChange(
                    change_type="materiality_changed",
                    entity_name=entity_label,
                    relationship_type=rel_type,
                    prior_materiality=p.materiality,
                    new_materiality=c.materiality,
                ))

    log.info(
        "Graph diff %s: %d changes, %d new nodes, %d removed nodes",
        current.symbol, len(diff.changes), len(diff.new_node_names), len(diff.removed_node_names),
    )
    return diff
