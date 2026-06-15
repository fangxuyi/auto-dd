from __future__ import annotations

import logging

from company_research.extraction.guidance import get_section_guidance
from company_research.extraction.facts import SECTION_TOPICS
from company_research.llm.base import ReasoningProvider
from company_research.models.analysis import SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import ResearchRun
from company_research.models.qa import OpenQuestion
from company_research.storage.database import Database

log = logging.getLogger(__name__)

_MIN_FACTS_FOR_ANALYSIS = 2


def analyze_all_sections(
    sections: list[str],
    facts: list[EvidenceFact],
    run: ResearchRun,
    db: Database,
    llm: ReasoningProvider,
) -> list[SectionConclusion]:
    """Run section analysis for every requested section.

    Sections with fewer than _MIN_FACTS_FOR_ANALYSIS supporting facts are
    recorded as open questions instead of conclusions.
    """
    conclusions: list[SectionConclusion] = []

    for section in sections:
        topic = SECTION_TOPICS.get(section, "")
        section_facts = [f for f in facts if f.topic == topic] if topic else facts

        if len(section_facts) < _MIN_FACTS_FOR_ANALYSIS:
            log.warning(
                "Section '%s' has only %d facts (need %d) — recording as open question",
                section, len(section_facts), _MIN_FACTS_FOR_ANALYSIS,
            )
            q = OpenQuestion(
                run_id=run.run_id,
                question=f"Insufficient evidence to analyze section: {section}",
                why_it_matters=f"Section '{section}' could not be completed — only {len(section_facts)} facts found.",
                best_source="10-K Item 1, proxy statement, product pages",
            )
            db.insert_question(q)
            continue

        guidance = get_section_guidance(section)
        log.info(
            "Analyzing section '%s' with %d facts...", section, len(section_facts)
        )
        try:
            conclusion = llm.analyze_section(
                section=section,
                facts=section_facts,
                run=run,
                section_guidance=guidance,
            )
            db.insert_conclusion(conclusion)
            conclusions.append(conclusion)
            log.info(
                "Section '%s' concluded with confidence=%s",
                section, conclusion.confidence,
            )
        except Exception as e:
            log.error("Section analysis failed for '%s': %s", section, e)

    return conclusions
