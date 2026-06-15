from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun


@runtime_checkable
class ReasoningProvider(Protocol):
    def extract_facts(
        self,
        chunks: list[dict[str, Any]],
        context: CompanyIdentity,
        run_id: str,
        topic: str = "business_model",
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
