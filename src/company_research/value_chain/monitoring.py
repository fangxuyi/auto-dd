"""Value chain monitoring indicators — what to watch between runs."""
from __future__ import annotations

import logging

from company_research.models.value_chain import (
    ChokepointAssessment,
    CompanyRelationship,
    ValueChainGraph,
)
from company_research.models.value_chain_diff import VCMonitoringIndicator

log = logging.getLogger(__name__)

_HIGH_MATERIALITY = {"critical", "significant"}
_HIGH_DEP_TYPES = {"SUPPLIES", "CONTRACT_MANUFACTURES_FOR", "LICENSES_IP_TO", "HOSTS"}


def extract_monitoring_indicators(
    run_id: str,
    symbol: str,
    graph: ValueChainGraph,
    relationships: list[CompanyRelationship],
    chokepoints: list[ChokepointAssessment],
) -> list[VCMonitoringIndicator]:
    """
    Generate monitoring indicators from high-materiality relationships and chokepoints.
    These are the signals that would change the value chain assessment between runs.
    """
    indicators: list[VCMonitoringIndicator] = []
    node_by_id = {n.node_id: n for n in graph.nodes}

    for rel in relationships:
        if rel.materiality not in _HIGH_MATERIALITY:
            continue
        if rel.relationship_type not in _HIGH_DEP_TYPES:
            continue
        src_node = node_by_id.get(rel.source_entity_id) or node_by_id.get(rel.target_entity_id)
        entity_name = src_node.entity_name if src_node else rel.product_or_service or "unknown"

        indicators.append(VCMonitoringIndicator(
            run_id=run_id,
            symbol=symbol,
            entity_name=entity_name,
            relationship_type=rel.relationship_type,
            indicator=(
                f"Monitor {entity_name} ({rel.relationship_type.lower().replace('_', ' ')}) "
                f"for supply continuity"
            ),
            trigger=(
                f"Any public statement of capacity reduction, contract renegotiation, "
                f"or SEC filing mentioning supply disruption from {entity_name}"
            ),
            urgency="high" if rel.materiality == "critical" else "medium",
        ))

    for cp in chokepoints:
        for ew in cp.early_warning_indicators[:2]:
            indicators.append(VCMonitoringIndicator(
                run_id=run_id,
                symbol=symbol,
                entity_name=cp.owner_or_controller or "unknown",
                relationship_type="CHOKEPOINT",
                indicator=ew,
                trigger=cp.failure_mechanism or "See chokepoint assessment",
                urgency="high" if cp.confidence in ("high", "medium") else "medium",
            ))

    log.info("Generated %d monitoring indicators for %s", len(indicators), symbol)
    return indicators
