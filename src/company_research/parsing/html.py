from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from company_research.models.sources import (
    DocumentSection,
    DocumentTable,
    NormalizedDocument,
    RawDocument,
)

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {"p", "div", "li", "td", "th", "span"}


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_tables(soup: BeautifulSoup) -> list[DocumentTable]:
    tables: list[DocumentTable] = []
    for table_tag in soup.find_all("table"):
        rows_raw = table_tag.find_all("tr")
        if not rows_raw:
            continue

        headers: list[str] = []
        rows: list[list[str]] = []

        for i, tr in enumerate(rows_raw):
            cells = [_clean(td.get_text()) for td in tr.find_all(["th", "td"])]
            if not any(cells):
                continue
            if i == 0 or tr.find("th"):
                if not headers:
                    headers = cells
                    continue
            rows.append(cells)

        if not headers and rows:
            headers = rows.pop(0)

        caption_tag = table_tag.find("caption")
        caption = _clean(caption_tag.get_text()) if caption_tag else None

        tables.append(
            DocumentTable(caption=caption, headers=headers, rows=rows)
        )
    return tables


def _extract_sections(
    soup: BeautifulSoup, full_text: str
) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    current_heading = "Introduction"
    current_parts: list[str] = []
    current_offset = 0

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        tag_name = tag.name.lower() if tag.name else ""
        if tag_name in _HEADING_TAGS:
            if current_parts:
                body = " ".join(current_parts).strip()
                if body:
                    # Find offset in full text
                    offset = full_text.find(current_heading)
                    sections.append(
                        DocumentSection(
                            heading=current_heading,
                            text=body,
                            char_offset=max(offset, 0),
                        )
                    )
            current_heading = _clean(tag.get_text())
            current_parts = []
        elif tag_name in {"p", "li"}:
            text = _clean(tag.get_text())
            if text:
                current_parts.append(text)

    if current_parts:
        body = " ".join(current_parts).strip()
        if body:
            offset = full_text.find(current_heading)
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    text=body,
                    char_offset=max(offset, 0),
                )
            )

    return sections


def parse_html(document: RawDocument, raw_bytes: bytes) -> NormalizedDocument:
    encoding = "utf-8"
    html = raw_bytes.decode(encoding, errors="replace")
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    full_text = _clean(soup.get_text(separator=" "))
    sections = _extract_sections(soup, full_text)
    tables = _extract_tables(soup)

    title_tag = soup.find("title")
    title = _clean(title_tag.get_text()) if title_tag else ""

    return NormalizedDocument(
        doc_id=document.doc_id,
        source_id=document.source_id,
        text=full_text,
        sections=sections,
        tables=tables,
        metadata={"title": title, "encoding": encoding, "parser": "html"},
    )
