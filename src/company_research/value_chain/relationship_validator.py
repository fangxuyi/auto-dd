"""LLM-based validation of reverse EDGAR lookup candidates.

Filters out false positives (competitor mentions, unrelated industries,
litigation references) using Haiku before relationship building.
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from company_research.config import settings
from company_research.llm.prompts import load as load_prompt
from company_research.models.value_chain import EntityCandidate

log = logging.getLogger(__name__)

_MAX_TOKENS = 120


def _parse_bool_response(text: str) -> tuple[bool, str]:
    """Extract is_genuine + reason from Haiku JSON response."""
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return bool(data.get("is_genuine", False)), data.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        pass
    # Fallback: look for true/false in plain text
    lower = text.lower()
    if '"is_genuine": true' in lower or "'is_genuine': true" in lower:
        return True, ""
    return False, ""


def validate_reverse_candidates(
    candidates: list[EntityCandidate],
    target_name: str,
) -> list[EntityCandidate]:
    """Filter reverse-lookup candidates using LLM plausibility check.

    Calls Haiku once per candidate. Candidates that fail validation are
    dropped and logged at DEBUG level. On any API error the candidate is
    kept (fail-open) so a transient error doesn't silently drop real edges.
    """
    if not candidates:
        return candidates

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = settings.extraction_model_id

    validated: list[EntityCandidate] = []
    dropped = 0
    pre_dropped = 0

    # Drop candidates with synthetic excerpts before LLM validation.
    # A synthetic excerpt means _fetch_filing_excerpt found no match in the filing's
    # main document — the FTS hit was likely in an exhibit we can't fetch, or the
    # filing uses a short form of the company name we didn't search for.
    # Without real text evidence we cannot confirm the relationship, so we drop
    # rather than let the LLM guess from company names alone.
    real_candidates: list[EntityCandidate] = []
    for candidate in candidates:
        if "mentioning" in (candidate.source_excerpt or ""):
            pre_dropped += 1
            log.debug(
                "VC validate SKIP (no real excerpt)  %s → %s",
                candidate.normalized_name, target_name,
            )
        else:
            real_candidates.append(candidate)

    if pre_dropped:
        log.info(
            "validate_reverse_candidates: pre-dropped %d synthetic-excerpt candidates for '%s'",
            pre_dropped, target_name,
        )

    for candidate in real_candidates:
        filer_name = candidate.normalized_name
        # Try to extract ticker from source_id (edgar_reverse:CIK) or raw_name
        filer_ticker = ""
        # Ticker is often embedded in the synthetic excerpt: "NAME (TICK) filed"
        m = re.search(r"\(([A-Z]{1,5})\)", candidate.source_excerpt or "")
        if m:
            filer_ticker = m.group(1)

        rel_type = candidate.proposed_relationship_type or "SUPPLIES"
        if rel_type == "SUPPLIES":
            relationship_description = f"{filer_name} supplies products/services to {target_name}"
            relationship_check = f"{filer_name} sells products or services to {target_name}"
        else:
            relationship_description = f"{filer_name} is a customer of {target_name}"
            relationship_check = f"{target_name} sells products or services to {filer_name}"

        prompt = load_prompt(
            "validate_vc_relationship",
            filer_name=filer_name,
            filer_ticker=filer_ticker or "unknown",
            target_name=target_name,
            relationship_description=relationship_description,
            relationship_check=relationship_check,
            excerpt=candidate.source_excerpt or "No excerpt available.",
        )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            is_genuine, reason = _parse_bool_response(text)

            if is_genuine:
                validated.append(candidate)
                log.debug("VC validate KEEP  %s → %s: %s", filer_name, target_name, reason)
            else:
                dropped += 1
                log.debug("VC validate DROP  %s → %s: %s", filer_name, target_name, reason)

        except Exception as exc:
            log.warning("VC relationship validation failed for %s (%s): %s — keeping candidate", filer_name, candidate.source_id, exc)
            validated.append(candidate)

    log.info(
        "validate_reverse_candidates: kept %d / %d for '%s' (pre-dropped %d synthetic, LLM-dropped %d)",
        len(validated), len(candidates), target_name, pre_dropped, dropped,
    )
    return validated
