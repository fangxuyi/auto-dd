"""Relationship builder — converts resolved candidates into CompanyRelationship records."""
from __future__ import annotations

import logging
from datetime import date

from company_research.models.identity import CompanyIdentity
from company_research.models.value_chain import (
    CompanyRelationship,
    EntityCandidate,
    PublicEntityIdentity,
    RelationshipEvidence,
)
from company_research.storage.database import Database
from company_research.value_chain.verification import (
    relationship_status_from_evidence,
    evidence_status_to_confidence,
)

log = logging.getLogger(__name__)


def build_relationships(
    target: CompanyIdentity,
    target_entity_id: str,
    resolved_pairs: list[tuple[EntityCandidate, PublicEntityIdentity | None]],
    run_id: str,
    db: Database,
    as_of: date,
) -> list[CompanyRelationship]:
    """
    Build and persist CompanyRelationship records from resolved candidate pairs.
    Only candidates with resolution_status='resolved' produce relationships.
    """
    relationships: list[CompanyRelationship] = []

    for candidate, entity in resolved_pairs:
        if candidate.resolution_status != "resolved" or entity is None:
            continue

        if entity.entity_id == target_entity_id:
            continue  # don't create self-relationship

        rel_type = candidate.proposed_relationship_type or "CATEGORY_PARTICIPANT"

        # Reverse-lookup source: the counterparty's filing named us — strong secondary evidence
        is_reverse = candidate.source_id.startswith("edgar_reverse:")
        evidence_status = (
            "confirmed_secondary" if is_reverse
            else ("confirmed_primary" if candidate.source_id else "inferred")
        )

        rel = CompanyRelationship(
            run_id=run_id,
            source_entity_id=entity.entity_id,
            target_entity_id=target_entity_id,
            relationship_type=rel_type,
            value_chain_layer=candidate.proposed_layer,
            last_verified_date=as_of,
            evidence_status=evidence_status,
            source_ids=[candidate.source_id] if candidate.source_id else [],
        )
        rel.current_status = relationship_status_from_evidence(
            rel.evidence_status, reverse_verified=is_reverse
        )
        rel.confidence = evidence_status_to_confidence(
            target_confirmed=not is_reverse and bool(candidate.source_id),
            counterparty_confirmed=is_reverse,
        )

        db.upsert_vc_relationship(rel)

        if candidate.source_id and candidate.source_excerpt:
            evidence = RelationshipEvidence(
                relationship_id=rel.relationship_id,
                source_id=candidate.source_id,
                source_location="",
                excerpt=candidate.source_excerpt[:500],
                evidence_status=rel.evidence_status,
                direction="target_first",
                verified_date=as_of,
            )
            db.upsert_vc_relationship_evidence(evidence)

        relationships.append(rel)
        log.debug(
            "Built relationship: %s → %s [%s] confidence=%s",
            entity.common_name or entity.legal_name,
            target.symbol,
            rel_type,
            rel.confidence,
        )

    log.info("Built %d relationships for %s", len(relationships), target.symbol)
    return relationships
