from __future__ import annotations

import logging

from company_research.llm.base import ReasoningProvider
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument
from company_research.storage.database import Database

log = logging.getLogger(__name__)

# Template section → topic mapping for focused extraction
SECTION_TOPICS: dict[str, str] = {
    "company_snapshot": "business_model",
    "core_product": "product",
    "product_market_fit": "customers",
    "customer_base": "customers",
    "market_structure": "market",
    "competitive_landscape": "competition",
    "competitive_advantage": "competition",
    "revenue_model": "revenue",
    "financial_quality": "financials",
    "management_governance": "management",
    "current_challenges": "risk",
    "growth_opportunities": "business_model",
    "key_risks": "risk",
    "scenarios": "financials",
}


def extract_and_store(
    doc: NormalizedDocument,
    context: CompanyIdentity,
    run_id: str,
    db: Database,
    llm: ReasoningProvider,
    section: str = "company_snapshot",
    source_location: str = "",
) -> list[EvidenceFact]:
    """Extract facts from a document section and write them to the evidence store."""
    topic = SECTION_TOPICS.get(section, "business_model")

    log.info(
        "Extracting facts for section '%s' from doc %s (source %s)",
        section, doc.doc_id, doc.source_id,
    )

    facts = llm.extract_facts(
        doc=doc,
        context=context,
        run_id=run_id,
        topic=topic,
        source_location=source_location,
    )

    for fact in facts:
        db.insert_fact(fact)

    log.info("Stored %d facts from doc %s", len(facts), doc.doc_id)
    return facts
