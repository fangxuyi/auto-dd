from __future__ import annotations

import logging

from company_research.llm.base import ReasoningProvider
from company_research.models.identity import CompanyIdentity, ResearchRun
from company_research.storage.database import Database

log = logging.getLogger(__name__)


def generate_report(
    run: ResearchRun,
    company: CompanyIdentity,
    db: Database,
    llm: ReasoningProvider,
) -> str:
    """Synthesize the full markdown report from stored section conclusions.

    Reads only from the SQLite evidence store — never from the web or cache.
    Returns the raw markdown string.
    """
    conclusions = db.get_conclusions(run.run_id)
    if not conclusions:
        log.warning("No section conclusions found for run %s — report will be empty.", run.run_id)
        return _empty_report(run, company)

    log.info("Synthesizing report from %d section conclusions...", len(conclusions))
    report_md = llm.synthesize_report(
        conclusions=conclusions,
        run=run,
        company=company,
    )
    log.info("Report synthesis complete (%d chars).", len(report_md))
    return report_md


def _empty_report(run: ResearchRun, company: CompanyIdentity) -> str:
    return (
        f"# {company.issuer_name} ({company.symbol}) — Product and Business Fundamentals\n\n"
        f"**As of:** {run.as_of_date}\n"
        f"**Research depth:** {run.depth}\n\n"
        f"*No section conclusions were generated. "
        "Insufficient evidence was collected for this run.*\n"
    )
