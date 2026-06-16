"""Relationship candidate discovery — mines EDGAR filings for supplier/customer mentions."""
from __future__ import annotations

import logging
import re
from datetime import date

from company_research.models.identity import CompanyIdentity
from company_research.models.value_chain import EntityCandidate
from company_research.storage.cache import RawCache
from company_research.storage.database import Database
from company_research.value_chain.html_extraction import extract_text

log = logging.getLogger(__name__)

# Patterns for extracting named entities near relationship keywords in filing text.
# Matches 1-5 title-case word sequences following a relationship keyword.
_ENTITY_PATTERN = re.compile(
    r"(?:supplier|customer|vendor|partner|distributor|reseller|integrator|licensee|licensors?|"
    r"manufacturer|provider|counterparty)[,\s]+(?:is\s+|are\s+|include[s]?\s+|such\s+as\s+)?"
    r"([A-Z][A-Za-z0-9&,\.\s]{3,60}?)(?:,|\.|;|\(|\band\b|$)",
    re.MULTILINE | re.IGNORECASE,
)

_SIGNIFICANT_CUSTOMER_PATTERN = re.compile(
    r"(?:significant|major|largest|principal|material)\s+customer[s]?\s+(?:include[s]?\s+|such\s+as\s+|is\s+|are\s+)?"
    r"([A-Z][A-Za-z0-9&,\.\s]{3,60}?)(?:,|\.|;|\(|\band\b)",
    re.MULTILINE | re.IGNORECASE,
)


def _clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip().strip(",.:;")


def discover_from_text(
    text: str,
    run_id: str,
    source_id: str,
    min_name_len: int = 4,
    max_candidates: int = 50,
) -> list[EntityCandidate]:
    """
    Extract relationship candidates from a block of text (e.g. a 10-K section).
    Returns EntityCandidate objects with resolution_status='unresolved'.
    """
    found: list[EntityCandidate] = []
    seen_names: set[str] = set()

    for pattern in (_ENTITY_PATTERN, _SIGNIFICANT_CUSTOMER_PATTERN):
        for m in pattern.finditer(text):
            raw = m.group(1)
            # Require captured entity name to start with an uppercase letter in the source text.
            # IGNORECASE on the full pattern makes [A-Z] match lowercase too, so filter here.
            if not raw or not raw[0].isupper():
                continue
            name = _clean_name(raw)
            if len(name) < min_name_len:
                continue
            if name.lower() in seen_names:
                continue
            # Exclude generic phrases
            if re.match(r"^(the|a|an|its|our|their|these|those|this|that)\b", name, re.I):
                continue
            seen_names.add(name.lower())
            # Capture a short excerpt around the match
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            excerpt = text[start:end].replace("\n", " ")
            found.append(
                EntityCandidate(
                    run_id=run_id,
                    raw_name=raw,
                    normalized_name=name,
                    source_id=source_id,
                    source_excerpt=excerpt,
                )
            )
            if len(found) >= max_candidates:
                break
        if len(found) >= max_candidates:
            break

    return found


def discover_from_sources(
    run_id: str,
    db: Database,
    cache: RawCache,
    max_per_source: int = 20,
) -> list[EntityCandidate]:
    """
    Iterate all primary EDGAR filing sources for this run, read cached raw bytes,
    and extract entity candidates.
    """
    sources = db.get_sources(run_id)
    filing_sources = [
        s for s in sources
        if s.get("primary_or_secondary") == "primary" and s.get("reliability_tier", 9) == 1
    ]
    log.info(
        "Scanning %d primary EDGAR sources for relationship candidates", len(filing_sources)
    )

    all_candidates: list[EntityCandidate] = []
    seen_globally: set[str] = set()  # deduplicate across sources by normalized name
    for src in filing_sources:
        # Try direct source_id match first; fall back to URL match across all runs.
        doc = db.get_document_by_source_id(src["source_id"])
        if doc is None and src.get("url"):
            doc = db.get_document_by_url(src["url"])
        if doc is None:
            log.debug("No cached document for source %s (%s)", src["source_id"], src.get("url"))
            continue
        try:
            raw_bytes = cache.read(doc["content_hash"])
            # Use clean HTML extraction so entity patterns run on prose, not XBRL markup.
            text = extract_text(raw_bytes)
        except (FileNotFoundError, Exception) as e:
            log.debug("Cache miss for source %s: %s", src["source_id"], e)
            continue

        candidates = discover_from_text(
            text=text,
            run_id=run_id,
            source_id=src["source_id"],
            max_candidates=max_per_source,
        )
        new_candidates = [c for c in candidates if c.normalized_name.lower() not in seen_globally]
        for c in new_candidates:
            seen_globally.add(c.normalized_name.lower())
        all_candidates.extend(new_candidates)
        log.debug(
            "  [%s] %d candidates (%d new)",
            src.get("title", src["source_id"])[:60],
            len(candidates),
            len(new_candidates),
        )

    log.info("Total candidates discovered: %d", len(all_candidates))
    return all_candidates
