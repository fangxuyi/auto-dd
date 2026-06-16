"""Clean text extraction from EDGAR HTML/XBRL filings for entity mining."""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Tags whose text content is not human-readable prose
_SKIP_TAGS = {
    "script", "style", "head", "meta", "link", "noscript",
    "xbrli:context", "xbrli:unit", "xbrli:xbrl",
    "ix:header", "ix:hidden",
}

# Paragraph-level tags worth extracting as discrete text chunks
_BLOCK_TAGS = {"p", "div", "li", "td", "th", "span", "section", "article"}

# Minimum word count for a block to be worth mining
_MIN_WORDS = 8


def extract_text(raw_bytes: bytes) -> str:
    """
    Return clean plain text from a raw EDGAR HTML/XBRL filing.

    Strips all markup, XBRL inline tags, scripts, and style blocks.
    Joins remaining text blocks with newlines so sentence-level context is preserved.
    """
    try:
        soup = BeautifulSoup(raw_bytes, "html.parser")
    except Exception:
        return raw_bytes.decode("utf-8", errors="replace")

    for tag in soup.find_all(True):
        if tag.name in _SKIP_TAGS:
            tag.decompose()

    # Collect text block by block to preserve paragraph breaks
    blocks: list[str] = []
    for tag in soup.find_all(_BLOCK_TAGS):
        text = tag.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()
        if len(words) >= _MIN_WORDS:
            blocks.append(text)

    if blocks:
        return "\n".join(blocks)

    # Fallback: get_text on the whole document
    return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))
