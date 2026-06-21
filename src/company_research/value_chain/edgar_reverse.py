"""EDGAR full-text search — reverse lookup for companies that name the target company."""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import date

import httpx

from company_research.config import settings
from company_research.models.value_chain import EntityCandidate, PublicEntityIdentity
from company_research.storage.database import Database

log = logging.getLogger(__name__)

_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_FILING_BASE = "https://www.sec.gov/Archives/edgar/data"
_MAX_RATE_SLEEP = 0.12  # EDGAR fair-use: ~8 req/s
_EXCERPT_WINDOW = 400  # chars around the keyword match to return

# Parse EDGAR display_names format: "Company Name  (TICKER)  (CIK 0000xxxxxxx)"
_DISPLAY_RE = re.compile(r"^(.*?)\s+\(([A-Z0-9.]+)\)\s+\(CIK\s+(\d+)\)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _fetch_filing_excerpt(
    cik: str,
    hit_id: str,
    target_name: str,
    keyword: str,
) -> str:
    """Fetch an EDGAR filing and return a text window containing target_name near keyword.

    hit_id format: "{adsh}:{filename}"  e.g. "0001628280-26-012906:ain-20251231.htm"
    Returns empty string on failure or if no relevant passage is found.
    """
    parts = hit_id.split(":", 1)
    if len(parts) != 2:
        return ""
    adsh, filename = parts
    adsh_nodash = adsh.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for URL
    url = f"{_FILING_BASE}/{cik_int}/{adsh_nodash}/{filename}"

    try:
        time.sleep(_MAX_RATE_SLEEP)
        chunks: list[bytes] = []
        total = 0
        with httpx.stream("GET", url, headers=_headers(), timeout=30) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(chunk_size=16_384):
                chunks.append(chunk)
                total += len(chunk)

        raw = b"".join(chunks).decode("utf-8", errors="replace")
        text = _strip_html(raw)
        text_lower = text.lower()
        keyword_lower = keyword.lower()

        # Build search variants: full legal name + first two words (e.g. "micron technology")
        name_variants = [target_name.lower()]
        words = target_name.split()
        if len(words) >= 2:
            name_variants.append(" ".join(words[:2]).lower())

        # Find the target name occurrence closest to the keyword
        best_excerpt = ""
        best_distance = float("inf")

        for target_lower in name_variants:
            search_from = 0
            while True:
                idx = text_lower.find(target_lower, search_from)
                if idx == -1:
                    break

                # Look for keyword within ±500 chars of target name
                window_lo = max(0, idx - 500)
                window_hi = min(len(text), idx + len(target_lower) + 500)
                window = text_lower[window_lo:window_hi]
                kw_pos = window.find(keyword_lower)

                if kw_pos != -1:
                    distance = abs(kw_pos - (idx - window_lo))
                    if distance < best_distance:
                        best_distance = distance
                        excerpt_lo = max(0, idx - 150)
                        excerpt_hi = min(len(text), idx + len(target_lower) + _EXCERPT_WINDOW)
                        best_excerpt = text[excerpt_lo:excerpt_hi].strip()

                search_from = idx + 1

        if best_excerpt:
            log.debug("Fetched real excerpt for %s from %s (%d bytes read)", target_name, url, total)
        else:
            log.debug("No keyword match found in %s (%d bytes read)", url, total)

        return best_excerpt[:500]

    except Exception as exc:
        log.debug("Failed to fetch filing excerpt from %s: %s", url, exc)
        return ""



def _headers() -> dict[str, str]:
    return {"User-Agent": settings.edgar_user_agent, "Accept": "application/json"}


def _fts_search(
    query: str,
    forms: list[str],
    start_dt: str,
    end_dt: str,
    max_hits: int = 30,
) -> list[dict]:
    """
    Query EDGAR full-text search and return raw hit dicts.
    Response fields: ciks (list), display_names (list), root_forms, file_date, adsh.
    """
    params: dict = {
        "q": query,
        "forms": ",".join(forms),
        "dateRange": "custom",
        "startdt": start_dt,
        "enddt": end_dt,
        "from": 0,
        "size": max_hits,
    }
    time.sleep(_MAX_RATE_SLEEP)
    try:
        r = httpx.get(_FTS_URL, params=params, headers=_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("hits", {}).get("hits", [])
    except Exception as e:
        log.warning("EDGAR FTS search failed for %r: %s", query, e)
        return []


def _parse_display_name(display_name: str) -> tuple[str, str, str] | None:
    """
    Parse EDGAR display_name into (company_name, ticker, zero_padded_cik).
    Returns None if format doesn't match.
    """
    m = _DISPLAY_RE.search(display_name.strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2), m.group(3).zfill(10)


def discover_reverse_mentions(
    company_name: str,
    run_id: str,
    as_of: date,
    db: Database,
    target_cik: str | None = None,
    forms: list[str] | None = None,
    lookback_years: int = 2,
    max_results: int = 30,
) -> list[EntityCandidate]:
    """
    Find companies whose recent SEC filings mention *company_name* as a customer,
    implying they supply to or serve the target.

    Uses two EDGAR FTS queries:
    - "<company_name>" AND "customer"   → suppliers/vendors naming us as customer
    - "<company_name>" AND "supplier"   → customers naming us as supplier (e.g. distributors)

    Filters out the target company's own CIK so its own filings are excluded.

    Returns EntityCandidate objects with:
    - resolution_status = "resolved"
    - proposed_relationship_type = "SUPPLIES" (filer supplies to / serves our target)
    - source_id = "edgar_reverse:<CIK>"
    """
    if forms is None:
        forms = ["10-K", "20-F"]

    end_dt = as_of.isoformat()
    start_dt = f"{as_of.year - lookback_years}-01-01"

    # Normalize target CIK for exclusion
    target_cik_norm = target_cik.zfill(10) if target_cik else None

    log.info(
        "Reverse EDGAR lookup: '%s' in %s (%s–%s)",
        company_name, "/".join(forms), start_dt, end_dt,
    )

    # Two passes:
    #   "customer" → filer names target as customer → filer supplies TO target (SUPPLIES)
    #   "supplier" → filer names target as supplier → filer is downstream customer OF target (CUSTOMER_OF)
    queries = [
        (f'"{company_name}" "customer"', "SUPPLIES"),
        (f'"{company_name}" "supplier"', "CUSTOMER_OF"),
    ]

    seen_ciks: set[str] = set()
    candidates: list[EntityCandidate] = []

    keyword_for_rel = {"SUPPLIES": "customer", "CUSTOMER_OF": "supplier"}

    for query, rel_type in queries:
        hits = _fts_search(query=query, forms=forms, start_dt=start_dt, end_dt=end_dt, max_hits=max_results)
        keyword = keyword_for_rel[rel_type]

        for hit in hits:
            src = hit.get("_source", {})
            ciks = src.get("ciks", [])
            hit_id = hit.get("_id", "")

            # Exclude the target company's own filings
            if target_cik_norm and any(c.zfill(10) == target_cik_norm for c in ciks):
                continue

            display_names = src.get("display_names", [])
            for dn in display_names:
                parsed = _parse_display_name(dn)
                if not parsed:
                    continue
                filer_name, ticker, cik = parsed
                if cik in seen_ciks:
                    continue
                if target_cik_norm and cik == target_cik_norm:
                    continue
                seen_ciks.add(cik)

                entity = PublicEntityIdentity(
                    legal_name=filer_name,
                    common_name=filer_name,
                    ticker=ticker if ticker else None,
                    regulator_id=cik,
                    active_listing=True,
                )
                db.upsert_vc_entity(entity)

                file_date = src.get("file_date", "")
                form = src.get("form", "")
                ctx_phrase = "as a customer" if rel_type == "SUPPLIES" else "as a supplier"

                # Try to fetch a real excerpt from the filing; fall back to synthetic
                excerpt = _fetch_filing_excerpt(
                    cik=cik,
                    hit_id=hit_id,
                    target_name=company_name,
                    keyword=keyword,
                )
                if not excerpt:
                    excerpt = (
                        f"{filer_name} ({ticker}) filed {form} ({file_date}) "
                        f"mentioning '{company_name}' {ctx_phrase}"
                    )

                candidate = EntityCandidate(
                    run_id=run_id,
                    raw_name=filer_name,
                    normalized_name=filer_name,
                    source_id=f"edgar_reverse:{cik}",
                    source_excerpt=excerpt,
                    resolution_status="resolved",
                    resolved_entity_id=entity.entity_id,
                    proposed_relationship_type=rel_type,
                )
                candidates.append(candidate)
                log.debug(
                    "Reverse hit: %s (%s) CIK=%s via %s on %s",
                    filer_name, ticker, cik, form, file_date,
                )

    log.info(
        "Reverse EDGAR lookup: %d unique filer candidates for '%s'",
        len(candidates), company_name,
    )
    return candidates
