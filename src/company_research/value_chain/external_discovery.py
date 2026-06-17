"""External relationship discovery — DDG web search for additional relationship candidates."""
from __future__ import annotations

import logging

from company_research.models.identity import CompanyIdentity
from company_research.models.value_chain import EntityCandidate
from company_research.storage.cache import RawCache
from company_research.value_chain.discovery import discover_from_text
from company_research.value_chain.html_extraction import extract_text

log = logging.getLogger(__name__)

_QUERIES = [
    '"{name}" supplier partnership agreement',
    '"{name}" major customer partner',
    '"{name}" distributor reseller integrator',
]


def discover_from_web(
    company: CompanyIdentity,
    run_id: str,
    cache: RawCache,
    max_per_query: int = 8,
) -> list[EntityCandidate]:
    """
    Search DuckDuckGo for supplier/customer/partner mentions and extract candidates.
    Returns EntityCandidate objects (unresolved) with source_excerpt context.
    Failures are silently skipped (network errors, CAPTCHA) — returns empty list.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("ddgs not installed — skipping web discovery")
        return []

    candidates: list[EntityCandidate] = []
    seen_urls: set[str] = set()

    for query_tpl in _QUERIES:
        query = query_tpl.format(name=company.issuer_name)
        try:
            results = list(DDGS().text(query, max_results=max_per_query))
        except Exception as exc:
            log.warning("DDG search failed for %r: %s", query, exc)
            continue

        for r in results:
            url = r.get("href") or r.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Use snippet text first (fast, no fetch needed)
            snippet = (r.get("body") or r.get("description") or "").strip()
            if snippet:
                new = discover_from_text(snippet, run_id=run_id, source_id=url, max_candidates=5)
                candidates.extend(new)

            # Fetch and parse the page via cache (store_bytes + read pattern)
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; auto-dd research bot)"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read()
                raw_doc = cache.store_bytes(raw, source_id=url, mime_type="text/html")
                page_text = extract_text(raw)
                new = discover_from_text(page_text, run_id=run_id, source_id=url, max_candidates=10)
                candidates.extend(new)
            except Exception as exc:
                log.debug("Failed to fetch/parse %s: %s", url, exc)

    # Deduplicate by normalized_name
    seen: set[str] = set()
    unique: list[EntityCandidate] = []
    for c in candidates:
        key = c.normalized_name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    log.info("External discovery found %d unique candidates for %s", len(unique), company.symbol)
    return unique
