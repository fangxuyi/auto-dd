from __future__ import annotations

from typing import Literal

from company_research.identity.edgar import get_submissions, lookup_cik
from company_research.models.identity import CompanyIdentity


class AmbiguousTickerError(Exception):
    def __init__(self, symbol: str, matches: list[dict]) -> None:
        self.symbol = symbol
        self.matches = matches
        names = ", ".join(m.get("title", "?") for m in matches)
        super().__init__(
            f"Ticker '{symbol}' is ambiguous — {len(matches)} matches: {names}"
        )


class TickerNotFoundError(Exception):
    pass


def _detect_security_type(
    submissions: dict,
) -> Literal["operating_company", "ADR", "fund", "shell", "partnership", "unknown"]:
    category = submissions.get("category", "")
    sic = str(submissions.get("sic", ""))
    name = submissions.get("name", "").upper()

    if "ADR" in name or "AMERICAN DEPOSITARY" in name:
        return "ADR"
    if "FUND" in name or sic == "6726":
        return "fund"
    if "PARTNERSHIP" in name or "L.P." in name or " LP" in name:
        return "partnership"
    if sic in ("6770", "6719"):
        return "shell"
    if sic:
        return "operating_company"
    return "unknown"


def _detect_jurisdiction(submissions: dict) -> str:
    stateOfIncorporation = submissions.get("stateOfIncorporation", "")
    # Foreign private issuers file 20-F; domestic file 10-K
    # submissions["filings"]["recent"]["form"] is a list of strings, not dicts
    recent_forms = submissions.get("filings", {}).get("recent", {}).get("form", [])
    if "20-F" in recent_forms:
        return "foreign_private_issuer"
    if stateOfIncorporation and stateOfIncorporation not in ("", "0"):
        return "US"
    return "unknown"


def resolve(symbol: str) -> CompanyIdentity:
    """Resolve a ticker symbol to a CompanyIdentity.

    Raises AmbiguousTickerError if multiple CIKs match.
    Raises TickerNotFoundError if no match found.
    """
    matches = lookup_cik(symbol)

    if not matches:
        raise TickerNotFoundError(
            f"Ticker '{symbol}' not found in SEC EDGAR. "
            "Verify the symbol is listed on a US exchange or files with the SEC."
        )
    if len(matches) > 1:
        raise AmbiguousTickerError(symbol, matches)

    match = matches[0]
    cik = str(match["cik_str"]).zfill(10)

    submissions = get_submissions(cik)

    # Fiscal year end from most recent 10-K or best-guess from submissions
    fy_end = submissions.get("fiscalYearEnd", "")  # e.g. "1231" or "0930"
    if len(fy_end) == 4:
        fiscal_year_end = f"{fy_end[:2]}-{fy_end[2:]}"
    else:
        fiscal_year_end = "12-31"  # default if unknown

    # IR URL: best-effort from company website field
    website = submissions.get("website", None)

    exchange_raw = match.get("exchange", submissions.get("exchanges", [""])[0] if submissions.get("exchanges") else "")

    return CompanyIdentity(
        symbol=symbol.upper(),
        exchange=exchange_raw or "UNKNOWN",
        issuer_name=submissions.get("name", match.get("title", symbol)),
        cik=cik,
        lei=None,
        isin=None,
        fiscal_year_end=fiscal_year_end,
        currency="USD",  # default; override for foreign filers
        ir_url=website,
        filing_jurisdiction=_detect_jurisdiction(submissions),
        security_type=_detect_security_type(submissions),
    )
