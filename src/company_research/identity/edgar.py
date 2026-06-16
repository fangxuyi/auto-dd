from __future__ import annotations

import time
from typing import Any

import httpx

from company_research.config import settings


_BASE = "https://data.sec.gov"
_SEARCH = "https://efts.sec.gov/LATEST/search-index"

_tickers_cache: dict | None = None


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.edgar_user_agent, "Accept": "application/json"}


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    time.sleep(0.11)  # EDGAR fair-access: max ~10 req/s
    r = httpx.get(url, params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _all_tickers() -> dict[str, Any]:
    """Download and process-cache company_tickers.json (one fetch per process)."""
    global _tickers_cache
    if _tickers_cache is None:
        _tickers_cache = _get("https://www.sec.gov/files/company_tickers.json")
    return _tickers_cache


def lookup_cik(symbol: str) -> list[dict[str, Any]]:
    """Return list of matching company dicts from EDGAR ticker→CIK map."""
    symbol_upper = symbol.upper()
    return [
        v for v in _all_tickers().values()
        if v.get("ticker", "").upper() == symbol_upper
    ]


def lookup_by_name(name: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fuzzy-match company name against EDGAR ticker list. Case-insensitive substring."""
    name_lower = name.lower().strip()
    if len(name_lower) < 3:
        return []
    matches = []
    for v in _all_tickers().values():
        title = v.get("title", "").lower()
        if name_lower in title or title.startswith(name_lower):
            matches.append(v)
    # Sort by title length — shorter name = more exact match
    matches.sort(key=lambda x: len(x.get("title", "")))
    return matches[:max_results]


def get_submissions(cik: str) -> dict[str, Any]:
    """Fetch full submissions JSON for a CIK (zero-padded 10 digits)."""
    return _get(f"{_BASE}/submissions/CIK{cik}.json")


def get_company_facts(cik: str) -> dict[str, Any]:
    """Fetch XBRL company facts (structured financials) for a CIK."""
    return _get(f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
