"""Chokepoint identification — flags high-dependency single-source relationships."""
from __future__ import annotations

import logging

from company_research.models.value_chain import (
    ChokepointAssessment,
    CompanyRelationship,
    DependencyAssessment,
)
from company_research.storage.database import Database

log = logging.getLogger(__name__)

_HIGH_DEPENDENCY_THRESHOLD = 4  # score ≥ 4 out of 5 triggers chokepoint flag


def identify_chokepoints(
    relationships: list[CompanyRelationship],
    dependencies: list[DependencyAssessment],
    run_id: str,
    db: Database,
) -> list[ChokepointAssessment]:
    """
    Flag relationships with high dependency scores as chokepoints.
    VC-M3 will enrich these with failure mechanisms and financial effects via LLM.
    """
    dep_by_rel = {d.relationship_id: d for d in dependencies}
    chokepoints: list[ChokepointAssessment] = []

    for rel in relationships:
        dep = dep_by_rel.get(rel.relationship_id)
        if dep is None:
            continue
        score = dep.target_dependency_score
        if score is not None and score >= _HIGH_DEPENDENCY_THRESHOLD:
            cp = ChokepointAssessment(
                run_id=run_id,
                chokepoint=f"High dependency on {rel.relationship_type} relationship",
                confidence=dep.confidence,
            )
            db.upsert_vc_chokepoint(cp)
            chokepoints.append(cp)

    log.info("Identified %d chokepoints for run %s", len(chokepoints), run_id)
    return chokepoints
