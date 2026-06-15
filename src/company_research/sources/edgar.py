from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from company_research.config import settings
from company_research.identity.edgar import get_submissions
from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument, RawDocument, SourceRecord
from company_research.storage.cache import RawCache

_FORM_TYPE_MAP: dict[str, str] = {
    "10-K": "10-K",
    "10-K/A": "10-K",
    "10-Q": "10-Q",
    "10-Q/A": "10-Q",
    "8-K": "8-K",
    "8-K/A": "8-K",
    "DEF 14A": "DEF14A",
    "20-F": "20-F",
    "20-F/A": "20-F",
    "6-K": "6-K",
    "SC 13D": "13D",
    "SC 13G": "13G",
    "4": "Form4",
    "S-1": "S-1",
    "S-1/A": "S-1",
}

# Lower number = higher priority; Form4 and minor forms pushed to end
_FORM_PRIORITY: dict[str, int] = {
    "10-K": 0,
    "20-F": 1,
    "10-Q": 2,
    "S-1": 3,
    "DEF14A": 4,
    "8-K": 5,
    "6-K": 6,
    "13D": 7,
    "13G": 8,
    "Form4": 99,
}

_TARGET_FORMS = set(_FORM_TYPE_MAP.keys())


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.edgar_user_agent}


def _get_bytes(url: str) -> bytes:
    time.sleep(0.11)
    r = httpx.get(url, headers=_headers(), timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _filing_index_url(cik: str, accession: str) -> str:
    acc_no_dash = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}"
        f"/{acc_no_dash}/{accession}-index.htm"
    )


def _primary_doc_url(cik: str, accession: str, filename: str) -> str:
    acc_no_dash = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}"
        f"/{acc_no_dash}/{filename}"
    )


class EdgarAdapter:
    """SEC EDGAR source adapter for 10-K, 10-Q, 8-K, DEF14A, and related forms."""

    def __init__(self, cache: RawCache, max_filings: int = 20) -> None:
        self.cache = cache
        self.max_filings = max_filings

    def search(self, company: CompanyIdentity, cutoff: date) -> list[SourceRecord]:
        submissions = get_submissions(company.cik)
        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        records: list[SourceRecord] = []
        for form, acc, filing_date, primary_doc, desc in zip(
            forms, accessions, dates, primary_docs, descriptions
        ):
            if form not in _TARGET_FORMS:
                continue
            try:
                fd = date.fromisoformat(filing_date)
            except ValueError:
                continue
            if fd > cutoff:
                continue

            source_type = _FORM_TYPE_MAP[form]
            url = _primary_doc_url(company.cik, acc, primary_doc)

            records.append(
                SourceRecord(
                    title=f"{company.issuer_name} {form} ({filing_date})",
                    publisher="SEC EDGAR",
                    url=url,
                    published_date=fd,
                    source_type=source_type,  # type: ignore[arg-type]
                    primary_or_secondary="primary",
                    period_covered=filing_date[:7],  # YYYY-MM approximation
                    company_or_external="regulator",
                    reliability_tier=1,
                )
            )

        # Prioritize substantive filings (10-K, 10-Q) over high-frequency minor forms (Form 4)
        records.sort(key=lambda r: _FORM_PRIORITY.get(r.source_type, 50))
        return records[: self.max_filings]

    def fetch(self, source: SourceRecord) -> RawDocument:
        data = _get_bytes(source.url)
        mime = "text/html" if source.url.endswith((".htm", ".html")) else "application/octet-stream"
        if source.url.endswith(".pdf"):
            mime = "application/pdf"
        return self.cache.store_bytes(data, source.source_id, mime)

    def normalize(self, document: RawDocument) -> NormalizedDocument:
        # Dispatch to the appropriate parser based on mime type
        from company_research.parsing.html import parse_html
        from company_research.parsing.pdf import parse_pdf

        raw_bytes = self.cache.read(document.content_hash)

        if document.mime_type == "application/pdf":
            return parse_pdf(document, raw_bytes)
        return parse_html(document, raw_bytes)
