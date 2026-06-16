"""Relationship verification — resolves candidates to EDGAR entities and checks both directions."""
from __future__ import annotations

import logging

from company_research.identity.edgar import lookup_by_name
from company_research.identity.resolver import lookup_cik
from company_research.models.value_chain import (
    EntityCandidate,
    PublicEntityIdentity,
    RelationshipStatus,
    VCConfidence,
)
from company_research.storage.database import Database

log = logging.getLogger(__name__)


def resolve_candidates(
    candidates: list[EntityCandidate],
    db: Database,
    max_resolve: int = 50,
) -> list[tuple[EntityCandidate, PublicEntityIdentity | None]]:
    """
    Attempt to resolve each candidate to a public EDGAR entity.
    Returns (candidate, resolved_entity_or_None) pairs.
    Only the first max_resolve candidates are attempted.
    """
    results: list[tuple[EntityCandidate, PublicEntityIdentity | None]] = []
    seen_names: set[str] = set()

    for candidate in candidates[:max_resolve]:
        norm = candidate.normalized_name.lower()
        if norm in seen_names:
            continue
        seen_names.add(norm)

        # Pre-resolved (e.g. by reverse lookup) — load entity from DB and pass through
        if candidate.resolution_status == "resolved" and candidate.resolved_entity_id:
            db_row = db.get_vc_entity(candidate.resolved_entity_id)
            if db_row:
                entity = PublicEntityIdentity(
                    entity_id=db_row["entity_id"],
                    legal_name=db_row["legal_name"],
                    common_name=db_row.get("common_name") or "",
                    ticker=db_row.get("ticker"),
                    regulator_id=db_row.get("regulator_id"),
                    active_listing=bool(db_row.get("active_listing", 1)),
                )
                results.append((candidate, entity))
            else:
                results.append((candidate, None))
            continue

        match: dict | None = None
        try:
            # First: exact ticker match (highest confidence)
            exact = lookup_cik(candidate.normalized_name)
            if len(exact) == 1:
                match = exact[0]
            elif not exact:
                # Fallback: fuzzy name search (lower confidence — mark ambiguous if >1)
                name_hits = lookup_by_name(candidate.normalized_name, max_results=3)
                if len(name_hits) == 1:
                    match = name_hits[0]
                    log.debug(
                        "Fuzzy-resolved '%s' → %s", candidate.normalized_name, match.get("title")
                    )
        except Exception as e:
            log.debug("CIK lookup failed for '%s': %s", candidate.normalized_name, e)
            candidate.resolution_status = "rejected"
            results.append((candidate, None))
            continue

        if match is None:
            candidate.resolution_status = "unresolved"
            results.append((candidate, None))
        else:
            entity = PublicEntityIdentity(
                legal_name=match.get("title", candidate.normalized_name),
                common_name=candidate.normalized_name,
                ticker=match.get("ticker"),
                regulator_id=str(match.get("cik", "")).zfill(10),
                active_listing=True,
            )
            candidate.resolved_entity_id = entity.entity_id
            candidate.resolution_status = "resolved"
            db.upsert_vc_entity(entity)
            results.append((candidate, entity))
            log.debug(
                "Resolved '%s' → %s (CIK %s)",
                candidate.normalized_name, entity.legal_name, entity.regulator_id,
            )

    return results


def evidence_status_to_confidence(
    target_confirmed: bool, counterparty_confirmed: bool
) -> VCConfidence:
    """Determine confidence level from dual-direction verification."""
    if target_confirmed and counterparty_confirmed:
        return "high"
    if target_confirmed or counterparty_confirmed:
        return "medium"
    return "low"


def relationship_status_from_evidence(
    evidence_status: str, reverse_verified: bool
) -> RelationshipStatus:
    if evidence_status == "confirmed_primary" and reverse_verified:
        return "confirmed_direct"
    if evidence_status in ("confirmed_primary", "confirmed_secondary"):
        return "confirmed_direct"
    if evidence_status == "inferred":
        return "inferred_likely"
    if evidence_status == "historical":
        return "historical"
    if evidence_status == "contradicted":
        return "contradicted"
    return "unverified_candidate"
