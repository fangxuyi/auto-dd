"""Product and pricing page adapter — discovers and fetches company product pages."""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import date

import httpx
from bs4 import BeautifulSoup

from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument, RawDocument, SourceRecord
from company_research.parsing.html import parse_html
from company_research.storage.cache import RawCache

log = logging.getLogger(__name__)

_FETCH_DELAY = 1.5

_PRODUCT_KEYWORDS = {
    "product", "products", "solutions", "platform", "features",
    "pricing", "plans", "shop", "store", "services",
}

_PRICING_KEYWORDS = {"pricing", "plans", "price", "cost", "subscribe", "buy"}

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ProductPageAdapter:
    """Discover and fetch product/pricing pages from the company's website."""

    def __init__(self, cache: RawCache, max_pages: int = 2) -> None:
        self.cache = cache
        self.max_pages = max_pages

    # ── SourceAdapter protocol ────────────────────────────────────────────────

    def search(self, company: CompanyIdentity, cutoff: date) -> list[SourceRecord]:
        if not company.ir_url:
            log.debug("No ir_url for %s — skipping ProductPageAdapter", company.symbol)
            return []

        base_url = company.ir_url.rstrip("/")
        sources: list[SourceRecord] = []
        seen: set[str] = set()

        try:
            html = _fetch_bytes(base_url)
        except Exception as e:
            log.warning("Failed to fetch company root %s: %s", base_url, e)
            return []

        links = _discover_product_links(html, base_url)
        for url, label, is_pricing in links:
            if len(sources) >= self.max_pages or url in seen:
                break
            seen.add(url)
            source_type = "pricing_page" if is_pricing else "product_page"
            sources.append(
                SourceRecord(
                    title=f"{company.issuer_name} — {label}",
                    publisher=company.issuer_name,
                    url=url,
                    source_type=source_type,
                    primary_or_secondary="secondary",
                    company_or_external="company",
                    reliability_tier=2,
                )
            )

        log.info("ProductPage found %d pages for %s", len(sources), company.symbol)
        return sources

    def fetch(self, source: SourceRecord) -> RawDocument:
        time.sleep(_FETCH_DELAY)
        try:
            data = _fetch_bytes(source.url)
        except Exception as e:
            log.warning("Failed to fetch product page %s: %s", source.url, e)
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


def _discover_product_links(html: bytes, base_url: str) -> list[tuple[str, str, bool]]:
    """Return (absolute_url, label, is_pricing) tuples for product/pricing links."""
    soup = BeautifulSoup(html, "lxml")
    base_parsed = urllib.parse.urlparse(base_url)
    found: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href: str = a["href"].strip()
        text: str = a.get_text(strip=True)

        abs_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(abs_url)

        if parsed.netloc and parsed.netloc != base_parsed.netloc:
            continue
        if not parsed.scheme.startswith("http"):
            continue
        clean_url = abs_url.split("#")[0].rstrip("/")
        if clean_url in seen or clean_url == base_url.rstrip("/"):
            continue

        href_lower = href.lower()
        text_lower = text.lower()
        combined = href_lower + " " + text_lower

        if not any(kw in combined for kw in _PRODUCT_KEYWORDS):
            continue

        is_pricing = any(kw in combined for kw in _PRICING_KEYWORDS)
        seen.add(clean_url)
        found.append((clean_url, text or href, is_pricing))

    # Prioritise pricing pages first
    found.sort(key=lambda x: (0 if x[2] else 1, len(x[0])))
    return found
