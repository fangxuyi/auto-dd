"""EDGAR full-text search — reverse lookup for companies that name the target company."""
from __future__ import annotations

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
_MAX_RATE_SLEEP = 0.12  # EDGAR fair-use: ~8 req/s

# Parse EDGAR display_names format: "Company Name  (TICKER)  (CIK 0000xxxxxxx)"
_DISPLAY_RE = re.compile(r"^(.*?)\s+\(([A-Z0-9.]+)\)\s+\(CIK\s+(\d+)\)", re.IGNORECASE)


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

    for query, rel_type in queries:
        hits = _fts_search(query=query, forms=forms, start_dt=start_dt, end_dt=end_dt, max_hits=max_results)

        for hit in hits:
            src = hit.get("_source", {})
            ciks = src.get("ciks", [])

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
