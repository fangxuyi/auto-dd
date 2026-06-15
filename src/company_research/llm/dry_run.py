from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from company_research.llm import prompts
from company_research.llm.anthropic import _format_excerpts
from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun

log = logging.getLogger(__name__)


class DryRunProvider:
    """ReasoningProvider that writes prompts to files instead of calling the API.

    Every method builds the prompt exactly as AnthropicProvider would, saves it
    to {prompts_dir}/{step_index:02d}_{name}.txt, then returns an empty / stub
    response so the rest of the pipeline can continue.
    """

    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def _save(self, name: str, prompt: str) -> Path:
        self._counter += 1
        path = self._dir / f"{self._counter:02d}_{name}.txt"
        path.write_text(prompt, encoding="utf-8")
        log.info("[dry-run] Prompt saved → %s (%d chars)", path.name, len(prompt))
        return path

    def extract_facts(
        self,
        chunks: list[dict[str, Any]],
        context: CompanyIdentity,
        run_id: str,
        topic: str = "business_model",
    ) -> list[EvidenceFact]:
        excerpts = _format_excerpts(chunks)
        prompt = prompts.load(
            "extract_facts",
            company_name=context.issuer_name,
            symbol=context.symbol,
            topic=topic,
            excerpts=excerpts,
        )
        self._save(f"extract_{topic}", prompt)
        return []

    def analyze_section(
        self,
        section: str,
        facts: list[EvidenceFact],
        run: ResearchRun,
        section_guidance: str = "",
    ) -> SectionConclusion:
        from company_research.extraction.guidance import get_section_guidance
        facts_json = json.dumps([f.model_dump() for f in facts], indent=2, default=str)
        guidance = section_guidance or get_section_guidance(section)
        prompt = prompts.load(
            "analyze_section",
            company_name=run.symbol,
            symbol=run.symbol,
            run_id=run.run_id,
            as_of_date=str(run.as_of_date),
            section_name=section,
            facts_json=facts_json,
            section_guidance=guidance,
        )
        self._save(f"analyze_{section}", prompt)
        return SectionConclusion(
            run_id=run.run_id,
            section=section,
            conclusion="[dry-run — no API call made]",
            confidence="unknown",
        )

    def detect_counterevidence(
        self,
        facts: list[EvidenceFact],
        run_id: str,
    ) -> list[Contradiction]:
        facts_json = json.dumps([f.model_dump() for f in facts], indent=2, default=str)
        prompt = prompts.load("detect_counterevidence", facts_json=facts_json)
        self._save("detect_counterevidence", prompt)
        return []

    def synthesize_report(
        self,
        conclusions: list[dict],
        run: ResearchRun,
        company: CompanyIdentity,
    ) -> str:
        conclusions_json = json.dumps(conclusions, indent=2, default=str)
        prompt = prompts.load(
            "synthesize_report",
            company_name=company.issuer_name,
            symbol=company.symbol,
            as_of_date=str(run.as_of_date),
            depth=run.depth,
            exchange=company.exchange,
            currency=company.currency,
            fiscal_year_end=company.fiscal_year_end,
            conclusions_json=conclusions_json,
        )
        self._save("synthesize_report", prompt)
        return f"# {company.issuer_name} ({company.symbol})\n\n[dry-run — no API call made]\n"
