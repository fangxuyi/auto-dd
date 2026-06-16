"""Value chain QA gates — validates graph and relationship artifacts."""
from __future__ import annotations

from company_research.models.value_chain import CompanyRelationship, ValueChainGraph


class VCQAResult:
    def __init__(self) -> None:
        self.checks: dict[str, bool] = {}
        self.critical_failures: list[str] = []

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def check(self, name: str, result: bool, critical: bool = False) -> None:
        self.checks[name] = result
        if not result and critical:
            self.critical_failures.append(name)


def run_vc_qa(
    graph: ValueChainGraph,
    relationships: list[CompanyRelationship],
) -> VCQAResult:
    result = VCQAResult()

    confirmed = [r for r in relationships if r.current_status == "confirmed_direct"]
    unverified_in_graph = [
        e for e in graph.edges if e.status == "unverified_candidate"
    ]

    # All confirmed direct relationships must have at least one source
    result.check(
        "confirmed_relationships_have_sources",
        all(len(r.source_ids) > 0 for r in confirmed),
        critical=True,
    )

    # Unverified candidates must not appear in the default graph
    result.check(
        "unverified_candidates_excluded_from_graph",
        len(unverified_in_graph) == 0,
        critical=True,
    )

    # Graph and relationship lists must be consistent
    graph_edge_count = len([e for e in graph.edges if e.status != "unverified_candidate"])
    non_unverified_rels = len([
        r for r in relationships
        if r.current_status not in ("unverified_candidate", "contradicted")
    ])
    result.check(
        "graph_and_relationships_consistent",
        graph_edge_count == non_unverified_rels,
    )

    # No confirmed relationship should be without a direction
    result.check(
        "relationship_direction_defined",
        all(r.source_entity_id != r.target_entity_id for r in confirmed),
        critical=True,
    )

    return result
