"""Investor-relations page adapter — fetches company IR site and sub-pages."""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import date

import httpx
from bs4 import BeautifulSoup

from company_research.config import settings
from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument, RawDocument, SourceRecord
from company_research.parsing.html import parse_html
from company_research.storage.cache import RawCache

log = logging.getLogger(__name__)

_FETCH_DELAY = 1.5

_IR_KEYWORDS = {
    "press-release", "press_release", "pressrelease",
    "earnings", "investor", "investor-relations", "ir",
    "annual-report", "annual_report", "annualreport",
    "presentation", "transcript", "webcasts",
}

_IR_SOURCE_TYPE_MAP = {
    "earnings": "earnings_release",
    "press": "press_release",
    "presentation": "investor_presentation",
    "investor": "ir_page",
    "annual": "investor_presentation",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class IRPageAdapter:
    """Fetch the company IR website and discover sub-pages (press releases, presentations)."""

    def __init__(self, cache: RawCache, max_pages: int = 3) -> None:
        self.cache = cache
        self.max_pages = max_pages

    # ── SourceAdapter protocol ────────────────────────────────────────────────

    def search(self, company: CompanyIdentity, cutoff: date) -> list[SourceRecord]:
        if not company.ir_url:
            log.debug("No ir_url for %s — skipping IRPageAdapter", company.symbol)
            return []

        base_url = company.ir_url.rstrip("/")
        sources: list[SourceRecord] = []
        seen: set[str] = set()

        # Root IR page
        root_source = SourceRecord(
            title=f"{company.issuer_name} — Investor Relations",
            publisher=company.issuer_name,
            url=base_url,
            source_type="ir_page",
            primary_or_secondary="secondary",
            company_or_external="company",
            reliability_tier=5,
        )
        sources.append(root_source)
        seen.add(base_url)

        # Fetch the root page to discover sub-links
        try:
            html = _fetch_bytes(base_url)
        except Exception as e:
            log.warning("Failed to fetch IR root %s: %s", base_url, e)
            return sources

        sub_links = _discover_ir_links(html, base_url)
        for url, label in sub_links:
            if len(sources) >= self.max_pages or url in seen:
                break
            seen.add(url)
            source_type = _classify_source_type(url, label)
            sources.append(
                SourceRecord(
                    title=f"{company.issuer_name} — {label}",
                    publisher=company.issuer_name,
                    url=url,
                    source_type=source_type,
                    primary_or_secondary="secondary",
                    company_or_external="company",
                    reliability_tier=5,
                )
            )

        log.info("IRPageAdapter found %d pages for %s", len(sources), company.symbol)
        return sources

    def fetch(self, source: SourceRecord) -> RawDocument:
        time.sleep(_FETCH_DELAY)
        try:
            data = _fetch_bytes(source.url)
        except Exception as e:
            log.warning("Failed to fetch IR page %s: %s", source.url, e)
            data = b""
        return self.cache.store_bytes(data, source.source_id, "text/html")

    def normalize(self, document: RawDocument) -> NormalizedDocument:
        raw = self.cache.read(document.content_hash)
        return parse_html(document, raw)


# ── helpers ───────────────────────────────────────────────────────────────────


def _fetch_bytes(url: str) -> bytes:
    r = httpx.get(
        url,
        headers={"User-Agent": _BROWSER_UA},
        timeout=30,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.content


def _discover_ir_links(html: bytes, base_url: str) -> list[tuple[str, str]]:
    """Return (absolute_url, link_text) pairs for IR-relevant sub-links."""
    soup = BeautifulSoup(html, "lxml")
    base_parsed = urllib.parse.urlparse(base_url)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href: str = a["href"].strip()
        text: str = a.get_text(strip=True)

        # Resolve to absolute URL
        abs_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(abs_url)

        # Only follow same-domain links
        if parsed.netloc and parsed.netloc != base_parsed.netloc:
            continue
        # Skip anchors, javascript, mailto
        if not parsed.scheme.startswith("http"):
            continue
        # Normalise (strip fragment)
        clean_url = abs_url.split("#")[0].rstrip("/")
        if clean_url in seen:
            continue

        href_lower = href.lower()
        text_lower = text.lower()
        if any(kw in href_lower or kw in text_lower for kw in _IR_KEYWORDS):
            seen.add(clean_url)
            found.append((clean_url, text or href))

    return found


def _classify_source_type(url: str, label: str) -> str:
    combined = (url + " " + label).lower()
    for kw, stype in _IR_SOURCE_TYPE_MAP.items():
        if kw in combined:
            return stype
    return "ir_page"
