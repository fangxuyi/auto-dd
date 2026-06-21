"""Enrich value chain relationships with product_or_service labels via Haiku 4.5."""
from __future__ import annotations

import logging

import anthropic

from company_research.llm.prompts import load as load_prompt
from company_research.models.value_chain import CompanyRelationship
from company_research.storage.database import Database

log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 30
_SYSTEM = (
    "You extract product or service labels from SEC filing text. "
    "Reply with 3-7 words ONLY — no punctuation, no explanation. "
    "If genuinely unclear reply with the single word: unknown"
)


def extract_products(
    relationships: list[CompanyRelationship],
    db: Database,
    target_name: str,
) -> None:
    """
    Enrich each relationship with a product_or_service label.

    Calls Haiku 4.5 once per relationship that has a non-synthetic evidence
    excerpt. Updates DB in place; individual failures are logged and skipped.
    """
    if not relationships:
        return

    client = anthropic.Anthropic()

    # Batch-fetch evidence excerpts
    evidence_map: dict[str, str] = {}
    with db._conn() as conn:
        for rel in relationships:
            row = conn.execute(
                "SELECT excerpt FROM vc_relationship_evidence WHERE relationship_id=? LIMIT 1",
                (rel.relationship_id,),
            ).fetchone()
            if row:
                evidence_map[rel.relationship_id] = row[0]

    # Batch-fetch entity display names
    entity_names: dict[str, str] = {}
    with db._conn() as conn:
        for row in conn.execute("SELECT entity_id, legal_name, common_name FROM vc_entities"):
            entity_names[row[0]] = row[2] or row[1]

    updated = 0
    for rel in relationships:
        excerpt = evidence_map.get(rel.relationship_id, "")
        if not excerpt:
            continue

        filer_name = entity_names.get(rel.source_entity_id, rel.source_entity_id)
        rel_type = rel.relationship_type or "SUPPLIES"
        direction = (
            f"{filer_name} supplies to {target_name}"
            if rel_type == "SUPPLIES"
            else f"{filer_name} is a customer of {target_name}"
        )

        prompt = load_prompt(
            "extract_product_or_service",
            excerpt=excerpt[:400],
            filer_name=filer_name,
            target_name=target_name,
            direction=direction,
        )

        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            label = response.content[0].text.strip().lower()
            if label and label != "unknown":
                rel.product_or_service = label
                db.update_relationship_product(rel.relationship_id, label)
                updated += 1
                log.debug("product label [%s → %s]: %s", filer_name, target_name, label)
        except Exception as exc:
            log.warning("Product extraction failed for %s (%s): %s", filer_name, rel.relationship_id, exc)

    log.info(
        "extract_products: enriched %d / %d relationships for %s",
        updated, len(relationships), target_name,
    )
