"""Dependency and bargaining power assessment (deterministic scoring skeleton)."""
from __future__ import annotations

import logging

from company_research.models.value_chain import (
    CompanyRelationship,
    DependencyAssessment,
    VCConfidence,
)
from company_research.storage.database import Database

log = logging.getLogger(__name__)


def assess_dependency(
    relationship: CompanyRelationship,
    run_id: str,
    db: Database,
) -> DependencyAssessment:
    """
    Placeholder deterministic dependency scorer.
    In VC-M3, this will use LLM analysis over evidence excerpts.
    For now it returns unknown confidence and null scores.
    """
    assessment = DependencyAssessment(
        run_id=run_id,
        relationship_id=relationship.relationship_id,
        confidence="unknown",
    )
    db.upsert_vc_dependency(assessment)
    return assessment
