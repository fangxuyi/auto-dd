from __future__ import annotations

from typing import Protocol, runtime_checkable

from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun
from company_research.models.sources import NormalizedDocument


@runtime_checkable
class ReasoningProvider(Protocol):
    def extract_facts(
        self,
        doc: NormalizedDocument,
        context: CompanyIdentity,
        run_id: str,
        topic: str = "business_model",
        source_location: str = "",
    ) -> list[EvidenceFact]: ...

    def analyze_section(
        self,
        section: str,
        facts: list[EvidenceFact],
        run: ResearchRun,
        section_guidance: str = "",
    ) -> SectionConclusion: ...

    def detect_counterevidence(
        self,
        facts: list[EvidenceFact],
        run_id: str,
    ) -> list[Contradiction]: ...

    def synthesize_report(
        self,
        conclusions: list[dict],
        run: ResearchRun,
        company: CompanyIdentity,
    ) -> str: ...
