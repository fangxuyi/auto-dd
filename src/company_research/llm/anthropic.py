from __future__ import annotations

import json
import logging

import anthropic

from company_research.config import settings
from company_research.llm import prompts
from company_research.llm.retry import LLMStructuredOutputError, call_with_retry
from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun
from company_research.models.sources import NormalizedDocument

log = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_EXTRACT_FACTS_CHUNK = 12_000  # chars per chunk to stay within context


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
        doc: NormalizedDocument,
        context: CompanyIdentity,
        run_id: str,
        topic: str = "business_model",
        source_location: str = "",
    ) -> list[EvidenceFact]:
        # Chunk large documents to stay within context limits
        text = doc.text
        chunks = [
            text[i : i + _EXTRACT_FACTS_CHUNK]
            for i in range(0, len(text), _EXTRACT_FACTS_CHUNK)
        ]

        all_facts: list[EvidenceFact] = []
        for chunk_idx, chunk in enumerate(chunks[:5]):  # cap at 5 chunks per doc
            prompt = prompts.load(
                "extract_facts",
                company_name=context.issuer_name,
                symbol=context.symbol,
                source_title=doc.metadata.get("title", ""),
                source_type=doc.metadata.get("parser", "unknown"),
                published_date=str(doc.metadata.get("published_date", "")),
                source_id=doc.source_id,
                source_location=source_location or f"chunk {chunk_idx + 1}",
                topic=topic,
                text=chunk,
            )

            raw_facts: list[dict] = call_with_retry(
                call_fn=self._call,
                repair_fn=self._repair,
                prompt=prompt,
                model_class=None,
                is_list=True,
            )

            for raw in raw_facts:
                try:
                    fact = EvidenceFact(
                        run_id=run_id,
                        source_id=doc.source_id,
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
