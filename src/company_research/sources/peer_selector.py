"""Peer company selector — discovers competitors and fetches their EDGAR filings."""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from company_research.identity.edgar import _all_tickers, lookup_by_name
from company_research.models.identity import CompanyIdentity
from company_research.models.sources import SourceRecord
from company_research.sources.edgar import EdgarAdapter
from company_research.storage.cache import RawCache

log = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Minimum candidate length and word count to attempt EDGAR resolution
_MIN_NAME_LEN = 4
_MIN_MEANINGFUL_WORDS = 2

# Words that should not be counted toward _MIN_MEANINGFUL_WORDS.
# Company suffixes (Inc, Corp, etc.) are intentionally excluded so "Microsoft Corp"
# counts as 2 meaningful words and passes the threshold.
# Includes generic English words that commonly appear Title Case in business sentences
# but are not company-name identifiers (e.g. "Old Market", "New Capital").
_STOP_WORDS = {
    # articles, prepositions, conjunctions
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "by", "for", "with",
    # pronouns
    "its", "their", "our", "your", "my",
    # comparison / relational
    "vs", "versus", "compared", "like", "such", "than",
    # common English adjectives that appear Title Case but are not brand identifiers
    "old", "new", "big", "small", "large", "major", "key", "main", "top",
    "best", "leading", "global", "national", "american", "digital", "traditional",
    "primary", "secondary", "current", "former", "recent", "next", "first", "second",
    # generic business/market nouns
    "market", "capital", "technology", "tech", "industry", "business", "company",
    "companies", "product", "service", "solution", "platform", "sector",
    "stock", "share", "shares", "value", "growth", "revenue", "profit",
}


class PeerSelector:
    """
    Discover and resolve peer companies for a given CompanyIdentity.

    Stage 1 — Discovery: DuckDuckGo search for competitors.
    Stage 2 — Resolution: Match candidate names against EDGAR ticker list.
    Stage 3 — Acquisition: Fetch top EDGAR filings per resolved peer.
    """

    def __init__(self, cache: RawCache, max_peers: int = 5, max_peer_filings: int = 3) -> None:
        self.cache = cache
        self.max_peers = max_peers
        self.max_peer_filings = max_peer_filings

    def select(
        self, company: CompanyIdentity, cutoff: date
    ) -> list[tuple[CompanyIdentity, list[SourceRecord]]]:
        """Return list of (peer_identity, peer_sources) pairs."""
        candidates = self._discover_candidates(company)
        log.info(
            "PeerSelector: %d raw candidates for %s", len(candidates), company.symbol
        )

        resolved = self._resolve_candidates(candidates, company)
        log.info(
            "PeerSelector: %d resolved peers for %s (limit=%d)",
            len(resolved), company.symbol, self.max_peers,
        )

        results: list[tuple[CompanyIdentity, list[SourceRecord]]] = []
        edgar = EdgarAdapter(cache=self.cache, max_filings=self.max_peer_filings)

        for peer_identity in resolved[: self.max_peers]:
            try:
                peer_sources = edgar.search(peer_identity, cutoff=cutoff)
                results.append((peer_identity, peer_sources))
                log.debug(
                    "Peer %s: %d filings", peer_identity.symbol, len(peer_sources)
                )
            except Exception as e:
                log.warning(
                    "Failed to fetch EDGAR filings for peer %s: %s",
                    peer_identity.symbol, e,
                )

        return results

    # ── stage 1: candidate discovery ────────────────────────────────────────

    def _discover_candidates(self, company: CompanyIdentity) -> list[str]:
        name = company.issuer_name
        year = date.today().year
        queries = [
            f'"{name}" main competitors {year}',
            f'"{name}" competitor comparison alternatives',
        ]

        seen: set[str] = set()
        candidates: list[str] = []

        for query in queries:
            try:
                snippets = _ddg_snippets(query)
            except Exception as e:
                log.warning("DDG competitor search failed for %r: %s", query, e)
                continue

            for text in snippets:
                for name_candidate in _extract_company_names(text):
                    norm = name_candidate.strip()
                    if norm and norm not in seen and norm.lower() != name.lower():
                        seen.add(norm)
                        candidates.append(norm)

        return candidates

    # ── stage 2: EDGAR resolution ────────────────────────────────────────────

    def _resolve_candidates(
        self, candidates: list[str], target: CompanyIdentity
    ) -> list[CompanyIdentity]:
        resolved: list[CompanyIdentity] = []
        seen_tickers: set[str] = {target.symbol.upper()}

        for candidate in candidates:
            if len(resolved) >= self.max_peers:
                break

            matches = lookup_by_name(candidate, max_results=3)
            if not matches:
                continue

            best = matches[0]
            ticker = best.get("ticker", "").upper()
            if not ticker or ticker in seen_tickers:
                continue

            # Reject if the candidate is not a meaningful substring of the matched title
            # (prevents "Technology" from matching "DXC Technology Co" accidentally)
            candidate_words = [
                w for w in candidate.lower().split() if w not in _STOP_WORDS
            ]
            matched_title = best.get("title", "").lower()
            overlap = sum(1 for w in candidate_words if w in matched_title)
            if len(candidate_words) > 0 and overlap / len(candidate_words) < 0.5:
                log.debug("Skipping low-overlap match: %r → %r", candidate, best.get("title"))
                continue

            seen_tickers.add(ticker)
            cik = str(best.get("cik_str", best.get("cik", ""))).zfill(10)
            peer = CompanyIdentity(
                symbol=ticker,
                exchange="",
                issuer_name=best.get("title", candidate),
                cik=cik,
                fiscal_year_end="12-31",
                currency="USD",
                filing_jurisdiction="US",
            )
            resolved.append(peer)

        return resolved


# ── helpers ───────────────────────────────────────────────────────────────────


def _ddg_snippets(query: str) -> list[str]:
    """Return snippet/title texts from a DuckDuckGo HTML search.

    Tries the standard endpoint first; falls back to Lite on CAPTCHA (HTTP 202).
    """
    for url in (_DDG_URL, _DDG_LITE_URL):
        time.sleep(1.5)
        r = httpx.post(
            url,
            data={"q": query, "kl": "us-en", "ia": "web"},
            headers={
                "User-Agent": _BROWSER_UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html",
            },
            timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()
        if r.status_code == 202:
            log.warning("DDG CAPTCHA at %s for query %r — trying fallback", url, query)
            continue

        soup = BeautifulSoup(r.content, "lxml")
        texts = [
            el.get_text(strip=True)
            for el in soup.select("a.result__a, .result__snippet, td.result-link, td.result-snippet")
            if el.get_text(strip=True)
        ]
        if texts:
            return texts

    return []


_COMPANY_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4}"  # Title-case sequence 1–5 words
    r"(?:\s+(?:Inc|Corp|Co|Ltd|LLC|PLC|Group|Holdings)\.?)?)\b"
)


def _extract_company_names(text: str) -> list[str]:
    """Extract plausible company names from text (Title Case sequences)."""
    names: list[str] = []
    for m in _COMPANY_RE.finditer(text):
        name = m.group(1).strip()
        words = name.lower().split()
        # Filter out pure stop-word matches
        meaningful = [w for w in words if w not in _STOP_WORDS]
        if len(meaningful) >= _MIN_MEANINGFUL_WORDS and len(name) >= _MIN_NAME_LEN:
            names.append(name)
    return names
