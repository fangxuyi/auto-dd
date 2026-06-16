"""Value chain report generator — writes value_chain_report.md from graph and assessments."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from company_research.models.value_chain import (
    ChokepointAssessment,
    ProfitPoolAssessment,
    ValueChainGraph,
)

log = logging.getLogger(__name__)


def write_value_chain_report(
    symbol: str,
    as_of: date,
    graph: ValueChainGraph,
    profit_pools: list[ProfitPoolAssessment],
    chokepoints: list[ChokepointAssessment],
    out_dir: Path,
) -> str:
    """Generate value_chain_report.md and return its content."""
    out_dir.mkdir(parents=True, exist_ok=True)

    confirmed = graph.confirmed_edges
    all_edges = graph.edges

    lines: list[str] = [
        f"# {symbol} — Value Chain Analysis",
        "",
        f"**As of:** {as_of}  ",
        f"**Confirmed relationships:** {len(confirmed)}  ",
        f"**Total graph edges:** {len(all_edges)}  ",
        f"**Nodes:** {len(graph.nodes)}  ",
        "",
        "---",
        "",
        "## Value Chain Executive Summary",
        "",
        f"This report maps {symbol}'s upstream inputs and downstream routes to market "
        f"based on SEC filings and other primary sources. "
        f"Only confirmed and inferred relationships are included in the headline graph.",
        "",
    ]

    # Layer overview (nodes grouped by entity)
    if graph.nodes:
        lines += [
            "## Value Chain Nodes",
            "",
            "| Entity | Ticker | Status | Confidence |",
            "|---|---|---|---|",
        ]
        for node in graph.nodes:
            ticker = node.ticker or "—"
            lines.append(f"| {node.entity_name} | {ticker} | {node.public_status} | — |")
        lines.append("")

    # Upstream relationships
    upstream_edges = [e for e in confirmed if e.relationship_type in (
        "SUPPLIES", "CONTRACT_MANUFACTURES_FOR", "HOSTS", "PROVIDES_DATA_TO",
        "LICENSES_IP_TO", "LOGISTICS_PROVIDER_TO",
    )]
    if upstream_edges:
        lines += ["## Upstream Relationships", ""]
        lines += ["| Entity | Type | Confidence | Last Verified |", "|---|---|---|---|"]
        node_by_id = {n.node_id: n for n in graph.nodes}
        for edge in upstream_edges:
            node = node_by_id.get(edge.source_node_id)
            name = node.entity_name if node else edge.source_node_id
            verified = str(edge.last_verified_date) if edge.last_verified_date else "—"
            lines.append(f"| {name} | {edge.relationship_type} | {edge.confidence} | {verified} |")
        lines.append("")

    # Downstream relationships
    downstream_edges = [e for e in confirmed if e.relationship_type in (
        "CUSTOMER_OF", "OEM_CUSTOMER_OF", "DISTRIBUTES", "RESELLS",
        "INTEGRATES", "CHANNEL_PARTNER_OF", "MARKETPLACE_FOR",
    )]
    if downstream_edges:
        lines += ["## Downstream Relationships", ""]
        lines += ["| Entity | Type | Confidence | Last Verified |", "|---|---|---|---|"]
        for edge in downstream_edges:
            node = node_by_id.get(edge.target_node_id) if 'node_by_id' in dir() else None
            name = node.entity_name if node else edge.target_node_id
            verified = str(edge.last_verified_date) if edge.last_verified_date else "—"
            lines.append(f"| {name} | {edge.relationship_type} | {edge.confidence} | {verified} |")
        lines.append("")

    # Profit pools
    if profit_pools:
        lines += ["## Profit Pools", "", "| Layer | Gross Margin | Operating Margin | Capital Intensity | Pricing Power |", "|---|---|---|---|---|"]
        for pp in profit_pools:
            lines.append(
                f"| {pp.layer_name} | {pp.gross_margin_range or '—'} | {pp.operating_margin_range or '—'} | {pp.capital_intensity} | {pp.pricing_power} |"
            )
        lines.append("")

    # Chokepoints
    if chokepoints:
        lines += ["## Bottlenecks and Chokepoints", ""]
        for cp in chokepoints:
            lines.append(f"- **{cp.chokepoint}** (confidence: {cp.confidence})")
            if cp.failure_mechanism:
                lines.append(f"  - Failure mechanism: {cp.failure_mechanism}")
            if cp.mitigation:
                lines.append(f"  - Mitigation: {cp.mitigation}")
        lines.append("")

    # Missing evidence note
    unverified_count = sum(1 for e in all_edges if e.status == "unverified_candidate")
    if unverified_count:
        lines += [
            "## Missing Evidence",
            "",
            f"- {unverified_count} candidate relationships could not be confirmed and are excluded from headline findings.",
            "- Reverse-direction verification (counterparty filings) is pending (VC-M3).",
            "",
        ]

    # QA checklist
    lines += [
        "## QA Status",
        "",
        f"- [ ] All direct relationships have citations  ",
        f"- [ ] Reverse-direction verification performed  ",
        f"- [ ] Public listings resolved  ",
        f"- [{'x' if not unverified_count else ' '}] Unverified candidates excluded from headline  ",
        "",
    ]

    content = "\n".join(lines)
    (out_dir / "value_chain_report.md").write_text(content, encoding="utf-8")
    log.info("Value chain report written to %s", out_dir / "value_chain_report.md")
    return content
