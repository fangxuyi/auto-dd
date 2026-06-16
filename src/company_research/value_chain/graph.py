"""Graph builder — assembles ValueChainGraph from relationships and entities."""
from __future__ import annotations

import csv
import json
import logging
from datetime import date
from pathlib import Path

from company_research.models.value_chain import (
    CompanyRelationship,
    GraphEdge,
    GraphNode,
    PublicEntityIdentity,
    ValueChainGraph,
)

log = logging.getLogger(__name__)


def build_graph(
    run_id: str,
    symbol: str,
    as_of: date,
    relationships: list[CompanyRelationship],
    entities: dict[str, PublicEntityIdentity],  # entity_id → entity
) -> ValueChainGraph:
    """
    Assemble a ValueChainGraph from confirmed + inferred relationships.
    Unverified candidates are excluded from the default graph.
    """
    graph = ValueChainGraph(run_id=run_id, symbol=symbol, as_of_date=as_of)

    # Collect entity_ids actually referenced
    referenced_ids: set[str] = set()
    for rel in relationships:
        if rel.current_status not in ("unverified_candidate", "contradicted"):
            referenced_ids.add(rel.source_entity_id)
            referenced_ids.add(rel.target_entity_id)

    # Build nodes
    node_map: dict[str, str] = {}  # entity_id → node_id
    for entity_id in referenced_ids:
        entity = entities.get(entity_id)
        if entity is None:
            continue
        node = GraphNode(
            run_id=run_id,
            entity_id=entity_id,
            entity_name=entity.common_name or entity.legal_name,
            public_status="public" if entity.active_listing else "unknown",
            ticker=entity.ticker,
            exchange=entity.exchange,
            country=entity.country,
            ultimate_public_parent=entity.ultimate_public_parent,
        )
        graph.nodes.append(node)
        node_map[entity_id] = node.node_id

    # Build edges
    for rel in relationships:
        if rel.current_status in ("unverified_candidate", "contradicted"):
            continue
        src_node = node_map.get(rel.source_entity_id)
        tgt_node = node_map.get(rel.target_entity_id)
        if src_node is None or tgt_node is None:
            continue
        edge = GraphEdge(
            run_id=run_id,
            source_node_id=src_node,
            target_node_id=tgt_node,
            relationship_type=rel.relationship_type,
            product_or_service=rel.product_or_service,
            status=rel.current_status,
            confidence=rel.confidence,
            materiality=rel.materiality,
            start_date=rel.start_date,
            end_date=rel.end_date,
            source_ids=rel.source_ids,
            last_verified_date=rel.last_verified_date,
        )
        graph.edges.append(edge)

    log.info(
        "Built graph: %d nodes, %d edges (%d confirmed)",
        len(graph.nodes), len(graph.edges), len(graph.confirmed_edges),
    )
    return graph


def export_graph(graph: ValueChainGraph, out_dir: Path) -> None:
    """Write graph JSON, nodes CSV, and edges CSV to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # value_chain_graph.json
    (out_dir / "value_chain_graph.json").write_text(
        graph.model_dump_json(indent=2), encoding="utf-8"
    )

    # value_chain_nodes.csv
    if graph.nodes:
        node_keys = ["node_id", "entity_name", "ticker", "exchange", "country",
                     "public_status", "ultimate_public_parent"]
        with (out_dir / "value_chain_nodes.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=node_keys, extrasaction="ignore")
            w.writeheader()
            for node in graph.nodes:
                w.writerow(node.model_dump())

    # value_chain_edges.csv
    if graph.edges:
        edge_keys = ["edge_id", "source_node_id", "target_node_id", "relationship_type",
                     "status", "confidence", "materiality", "last_verified_date"]
        with (out_dir / "value_chain_edges.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=edge_keys, extrasaction="ignore")
            w.writeheader()
            for edge in graph.edges:
                row = edge.model_dump()
                row["last_verified_date"] = str(row["last_verified_date"]) if row["last_verified_date"] else ""
                w.writerow(row)

    log.info("Graph exported to %s", out_dir)
