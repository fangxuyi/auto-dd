from __future__ import annotations

import logging

from company_research.extraction.topic_queries import TOPIC_QUERIES
from company_research.llm.base import ReasoningProvider
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity
from company_research.storage.database import Database
from company_research.storage.vectorstore import VectorStore

log = logging.getLogger(__name__)

# Template section → evidence topic mapping
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
    "monitoring_dashboard": "business_model",
}


def extract_and_store(
    vector_store: VectorStore,
    context: CompanyIdentity,
    run_id: str,
    db: Database,
    llm: ReasoningProvider,
    section: str = "company_snapshot",
    k: int = 12,
) -> list[EvidenceFact]:
    """Retrieve relevant chunks for a section and extract facts into the evidence store."""
    topic = SECTION_TOPICS.get(section, "business_model")
    query = TOPIC_QUERIES.get(topic, topic)

    log.info("Retrieving top-%d chunks for section '%s' (topic: %s)...", k, section, topic)
    chunks = vector_store.retrieve(query, k=k)

    if not chunks:
        log.warning("No chunks retrieved for section '%s' — skipping extraction.", section)
        return []

    log.info(
        "Extracting facts for section '%s' from %d chunks (top score=%.3f)...",
        section, len(chunks), chunks[0]["score"],
    )

    facts = llm.extract_facts(
        chunks=chunks,
        context=context,
        run_id=run_id,
        topic=topic,
    )

    for fact in facts:
        db.insert_fact(fact)

    log.info("Extracted and stored %d facts for section '%s'", len(facts), section)
    return facts
