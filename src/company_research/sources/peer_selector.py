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
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Minimum candidate length to attempt EDGAR resolution
_MIN_NAME_LEN = 4

# Words to strip from extracted candidate names before EDGAR lookup
_STOP_WORDS = {
    "inc", "corp", "co", "ltd", "llc", "plc", "group", "holdings",
    "the", "a", "an", "and", "or", "of", "in", "on",
    "its", "their", "vs", "versus", "compared", "like", "such",
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
    """Return snippet/title texts from a DuckDuckGo HTML search."""
    time.sleep(1.0)
    r = httpx.post(
        _DDG_URL,
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

    soup = BeautifulSoup(r.content, "lxml")
    texts: list[str] = []
    for el in soup.select("a.result__a, .result__snippet"):
        t = el.get_text(strip=True)
        if t:
            texts.append(t)
    return texts


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
        if meaningful and len(name) >= _MIN_NAME_LEN:
            names.append(name)
    return names
