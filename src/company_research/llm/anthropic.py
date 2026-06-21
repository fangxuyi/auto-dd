from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from company_research.config import settings
from company_research.llm import prompts
from company_research.llm.retry import LLMStructuredOutputError, call_with_retry
from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import CompanyIdentity, ResearchRun

log = logging.getLogger(__name__)

_MAX_TOKENS = 16000  # 24 chunks × 2800 chars can produce 100+ facts; 8192 caused truncation


class AnthropicProvider:
    """ReasoningProvider implementation using Anthropic Claude."""

    def __init__(self, model_id: str | None = None, log_dir: Path | None = None) -> None:
        self.model_id = model_id or settings.model_id
        self._extraction_model_id = settings.extraction_model_id
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._call_log: Path | None = None
        if log_dir is not None:
            self._call_log = Path(log_dir) / "llm_calls.jsonl"
            self._call_log.parent.mkdir(parents=True, exist_ok=True)

    def _call(self, prompt: str, call_type: str = "unknown", extra: dict | None = None, model: str | None = None) -> str:
        effective_model = model or self.model_id
        log.debug("API call → model=%s call_type=%s prompt_chars=%d", effective_model, call_type, len(prompt))
        response = self._client.messages.create(
            model=effective_model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        log.debug(
            "API response ← input_tokens=%d output_tokens=%d stop_reason=%s",
            usage.input_tokens, usage.output_tokens, response.stop_reason,
        )
        text = response.content[0].text  # type: ignore[index]
        if self._call_log is not None:
            entry: dict[str, Any] = {
                "ts": datetime.utcnow().isoformat(),
                "call_type": call_type,
                "model": effective_model,
                "prompt_chars": len(prompt),
                "prompt": prompt,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "stop_reason": response.stop_reason,
            }
            if extra:
                entry.update(extra)
            with self._call_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return text

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
            call_fn=lambda p: self._call(p, call_type="extract_facts", extra={"topic": topic}, model=self._extraction_model_id),
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
                    log.debug("Unknown source_id %r — using fallback %s", sid, fallback_source_id)
                    sid = fallback_source_id
                fact = EvidenceFact(
                    run_id=run_id,
                    source_id=sid,
                    **{k: v for k, v in raw.items() if k in EvidenceFact.model_fields},
                )
                all_facts.append(fact)
            except Exception as e:
                log.warning("Skipping malformed fact: %s — %s", raw, e)

        log.info(
            "extract_facts topic=%s → %d facts from %d chunks (model=%s)",
            topic, len(all_facts), len(chunks), self._extraction_model_id,
        )
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
            call_fn=lambda p: self._call(p, call_type="analyze_section", extra={"section": section}),
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
        log.info(
            "synthesize_report symbol=%s depth=%s conclusions=%d",
            company.symbol, run.depth, len(conclusions),
        )
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
        result = self._call(prompt, call_type="synthesize_report")
        log.info("synthesize_report complete (%d chars)", len(result))
        return result

    def detect_counterevidence(
        self,
        facts: list[EvidenceFact],
        run_id: str,
    ) -> list[Contradiction]:
        if not facts:
            return []

        log.info("detect_counterevidence: scanning %d facts for contradictions", len(facts))
        facts_json = json.dumps(
            [f.model_dump() for f in facts], indent=2, default=str
        )
        prompt = prompts.load("detect_counterevidence", facts_json=facts_json)

        raw_list: list[dict] = call_with_retry(
            call_fn=lambda p: self._call(p, call_type="detect_counterevidence", model=self._extraction_model_id),
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
        log.info("detect_counterevidence → %d contradictions", len(contradictions))
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
