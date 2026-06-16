"""DuckDuckGo web-search adapter — no API key required."""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import date

import httpx

from company_research.config import settings
from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument, RawDocument, SourceRecord
from company_research.parsing.html import parse_html
from company_research.storage.cache import RawCache

log = logging.getLogger(__name__)

_FETCH_DELAY = 1.5  # seconds between external page fetches (polite crawling)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WebSearchAdapter:
    """Fetch web search results via DuckDuckGo HTML (no API key)."""

    def __init__(self, cache: RawCache, max_results: int = 3) -> None:
        self.cache = cache
        self.max_results = max_results

    # ── SourceAdapter protocol ────────────────────────────────────────────────

    def search(self, company: CompanyIdentity, cutoff: date) -> list[SourceRecord]:
        queries = _build_queries(company)
        sources: list[SourceRecord] = []
        seen_urls: set[str] = set()

        for query in queries:
            try:
                results = _ddg_search(query, max_results=self.max_results)
            except Exception as e:
                log.warning("DDG search failed for %r: %s", query, e)
                continue

            for r in results:
                url = r["url"]
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                tier = _reliability_tier(url)
                sources.append(
                    SourceRecord(
                        title=r["title"] or url,
                        publisher=_domain(url),
                        url=url,
                        source_type="web_search",
                        primary_or_secondary="secondary",
                        company_or_external="external",
                        reliability_tier=tier,
                    )
                )

        log.info("WebSearch found %d unique URLs for %s", len(sources), company.symbol)
        return sources

    def fetch(self, source: SourceRecord) -> RawDocument:
        time.sleep(_FETCH_DELAY)
        try:
            r = httpx.get(
                source.url,
                headers={"User-Agent": _BROWSER_UA},
                timeout=30,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.content
        except Exception as e:
            log.warning("Failed to fetch %s: %s", source.url, e)
            data = b""
        mime = "text/html"
        return self.cache.store_bytes(data, source.source_id, mime)

    def normalize(self, document: RawDocument) -> NormalizedDocument:
        raw = self.cache.read(document.content_hash)
        return parse_html(document, raw)


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_queries(company: CompanyIdentity) -> list[str]:
    name = company.issuer_name
    return [
        f'"{name}" competitive analysis product review',
        f'"{name}" competitors comparison alternatives',
        f'"{name}" investor presentation annual report',
    ]


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Search DuckDuckGo via the ddgs library and return list of {title, url, snippet}."""
    try:
        from ddgs import DDGS
    except ImportError:
        log.warning("ddgs library not installed — DDG search disabled. Run: pip install ddgs")
        return []

    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        return [{"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")} for h in hits]
    except Exception as e:
        log.warning("DDG search failed for %r: %s", query, e)
        return []


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return url


def _reliability_tier(url: str) -> int:
    domain = _domain(url).lower()
    if any(x in domain for x in ("sec.gov", "investor.", "ir.", "annualreport")):
        return 4  # credible primary/secondary
    if any(x in domain for x in ("bloomberg", "reuters", "ft.com", "wsj.com", "economist")):
        return 4
    if any(x in domain for x in ("seekingalpha", "motleyfool", "barrons")):
        return 5
    return 6  # general media / unknown
