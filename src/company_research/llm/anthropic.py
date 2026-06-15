from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from company_research.config import settings
from company_research.llm import prompts
from company_research.llm.retry import LLMStructuredOutputError, call_with_retry
from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun

log = logging.getLogger(__name__)

_MAX_TOKENS = 8192  # raised to avoid mid-JSON truncation


class AnthropicProvider:
    """ReasoningProvider implementation using Anthropic Claude."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or settings.model_id
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _call(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model_id,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text  # type: ignore[index]

    def _repair(self, previous: str, errors: str, schema_desc: str) -> str:
        return prompts.load(
            "repair_output",
            validation_errors=errors,
            schema_description=schema_desc,
            previous_response=previous,
        )

    def extract_facts(
        self,
        chunks: list[dict[str, Any]],
        context: CompanyIdentity,
        run_id: str,
        topic: str = "business_model",
    ) -> list[EvidenceFact]:
        """Extract facts from retrieved vector-store chunks.

        Each chunk is a dict with keys: text, metadata (source_id, title,
        source_type, period_covered, published_date), score.
        """
        if not chunks:
            return []

        excerpts = _format_excerpts(chunks)

        prompt = prompts.load(
            "extract_facts",
            company_name=context.issuer_name,
            symbol=context.symbol,
            topic=topic,
            excerpts=excerpts,
        )

        raw_facts: list[dict] = call_with_retry(
            call_fn=self._call,
            repair_fn=self._repair,
            prompt=prompt,
            model_class=None,
            is_list=True,
        )

        # Build a lookup: source_id → source_id for validation
        valid_source_ids = {c["metadata"].get("source_id", "") for c in chunks}
        # fallback source_id = highest-scoring chunk's source_id
        fallback_source_id = chunks[0]["metadata"].get("source_id", "") if chunks else ""

        all_facts: list[EvidenceFact] = []
        for raw in raw_facts:
            try:
                sid = raw.pop("source_id", None)
                if sid not in valid_source_ids:
                    sid = fallback_source_id
                fact = EvidenceFact(
                    run_id=run_id,
                    source_id=sid,
                    **{k: v for k, v in raw.items() if k in EvidenceFact.model_fields},
                )
                all_facts.append(fact)
            except Exception as e:
                log.warning("Skipping malformed fact: %s — %s", raw, e)

        return all_facts

    def analyze_section(
        self,
        section: str,
        facts: list[EvidenceFact],
        run: ResearchRun,
        section_guidance: str = "",
    ) -> SectionConclusion:
        facts_json = json.dumps(
            [f.model_dump() for f in facts], indent=2, default=str
        )
        prompt = prompts.load(
            "analyze_section",
            company_name=run.symbol,
            symbol=run.symbol,
            run_id=run.run_id,
            as_of_date=str(run.as_of_date),
            section_name=section,
            facts_json=facts_json,
            section_guidance=section_guidance,
        )

        result: SectionConclusion = call_with_retry(
            call_fn=self._call,
            repair_fn=self._repair,
            prompt=prompt,
            model_class=SectionConclusion,
            is_list=False,
        )
        result.run_id = run.run_id
        return result

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
        return self._call(prompt)

    def detect_counterevidence(
        self,
        facts: list[EvidenceFact],
        run_id: str,
    ) -> list[Contradiction]:
        if not facts:
            return []

        facts_json = json.dumps(
            [f.model_dump() for f in facts], indent=2, default=str
        )
        prompt = prompts.load("detect_counterevidence", facts_json=facts_json)

        raw_list: list[dict] = call_with_retry(
            call_fn=self._call,
            repair_fn=self._repair,
            prompt=prompt,
            model_class=None,
            is_list=True,
        )

        contradictions: list[Contradiction] = []
        for raw in raw_list:
            try:
                c = Contradiction(run_id=run_id, **raw)
                contradictions.append(c)
            except Exception as e:
                log.warning("Skipping malformed contradiction: %s — %s", raw, e)
        return contradictions


def _format_excerpts(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a labelled multi-source excerpt block."""
    parts: list[str] = []
    for chunk in chunks:
        meta = chunk["metadata"]
        source_id = meta.get("source_id", "unknown")
        title = meta.get("title", "unknown source")
        period = meta.get("period_covered", "")
        header = f"### [source_id: {source_id}] {title}" + (f" — {period}" if period else "")
        parts.append(f"{header}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)
