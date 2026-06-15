from __future__ import annotations

import time
from typing import Any

import httpx

from company_research.config import settings


_BASE = "https://data.sec.gov"
_SEARCH = "https://efts.sec.gov/LATEST/search-index"


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.edgar_user_agent, "Accept": "application/json"}


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    time.sleep(0.11)  # EDGAR fair-access: max ~10 req/s
    r = httpx.get(url, params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def lookup_cik(symbol: str) -> list[dict[str, Any]]:
    """Return list of matching company dicts from EDGAR ticker→CIK map."""
    data = _get(f"{_BASE}/files/company_tickers.json")
    symbol_upper = symbol.upper()
    matches = [
        v for v in data.values()
        if v.get("ticker", "").upper() == symbol_upper
    ]
    return matches


def get_submissions(cik: str) -> dict[str, Any]:
    """Fetch full submissions JSON for a CIK (zero-padded 10 digits)."""
    return _get(f"{_BASE}/submissions/CIK{cik}.json")


def get_company_facts(cik: str) -> dict[str, Any]:
    """Fetch XBRL company facts (structured financials) for a CIK."""
    return _get(f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
